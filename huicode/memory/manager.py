from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from huicode.agent_events import AgentMode, AgentState
from huicode.config import LLMConfig, MemoryConfig
from huicode.context import ContextManager
from huicode.memory.index import MemoryIndex
from huicode.memory.instructions import InstructionLoader
from huicode.memory.notes import NoteStore
from huicode.memory.sessions import SessionRecorder, SessionStore
from huicode.memory.types import MemoryStatus, MemoryUpdateReport, ResumeReport
from huicode.memory.updater import MemoryUpdater
from huicode.providers.base import ConversationMessage, Provider
from huicode.tools.base import ToolContext


class MemoryManager:
    def __init__(
        self,
        workspace: Path,
        settings: MemoryConfig,
        config: LLMConfig,
        provider: Provider,
        synchronous_updates: bool = False,
    ) -> None:
        self.workspace = workspace
        self.settings = settings
        self.config = config
        self.provider = provider
        self.session_store = SessionStore(workspace, settings)
        self.note_store = NoteStore(workspace)
        self.memory_index = MemoryIndex(workspace, settings, self.note_store)
        self.updater = MemoryUpdater(workspace, settings, config, self.note_store, self.memory_index)
        self.recorder: SessionRecorder | None = None
        self.executor: ThreadPoolExecutor | None = None if synchronous_updates else ThreadPoolExecutor(max_workers=1)
        self.futures: list[Future[MemoryUpdateReport]] = []
        self.synchronous_updates = synchronous_updates

    def start(self, state: AgentState) -> list[str]:
        if not self.settings.enabled:
            return []
        self.recorder = self.session_store.open()
        state.memory.session_id = self.recorder.session_id
        warnings: list[str] = []
        try:
            removed = self.session_store.cleanup_expired(self.recorder.session_id)
            if removed:
                warnings.append(f"已清理 {removed} 个过期会话")
        except OSError as exc:
            warnings.append(f"清理过期会话失败: {exc}")
        self.refresh_prompt_memory(state)
        state.memory.warnings.extend(warnings)
        return warnings

    def refresh_prompt_memory(self, state: AgentState) -> None:
        if not self.settings.enabled:
            return
        result = InstructionLoader(self.workspace, self.settings).load()
        state.memory.instructions_text = result.text
        state.memory.memory_index_text = self.memory_index.load_text()
        state.memory.warnings = list(result.warnings)

    def record_message(self, state: AgentState, message: ConversationMessage) -> None:
        if not self.settings.enabled or self.recorder is None:
            return
        try:
            self.recorder.append_message(message)
        except OSError as exc:
            state.memory.last_error = f"会话写入失败: {exc}"

    def schedule_update_after_final(
        self,
        state: AgentState,
        mode: AgentMode,
        turn_start: int,
    ) -> MemoryUpdateReport:
        if not self.settings.enabled or not self.settings.auto_update:
            return MemoryUpdateReport(ok=True, message="自动记忆未启用", noop=True)
        turn_messages = list(state.messages[turn_start:])
        if not turn_messages:
            return MemoryUpdateReport(ok=True, message="没有可整理内容", noop=True)
        state.memory.pending_updates += 1

        def run_update() -> MemoryUpdateReport:
            report = self.updater.update_from_turn(
                self.provider,
                state.memory.session_id,
                mode,
                turn_messages,
                state.memory.memory_index_text,
            )
            state.memory.pending_updates = max(0, state.memory.pending_updates - 1)
            if report.ok:
                state.memory.last_update_at = datetime.now().astimezone().isoformat(timespec="seconds")
                state.memory.last_error = ""
                state.memory.memory_index_text = self.memory_index.load_text()
            else:
                state.memory.last_error = report.message
            return report

        if self.synchronous_updates or self.executor is None:
            return run_update()
        self.futures.append(self.executor.submit(run_update))
        # 自动整理在后台静默完成，失败可通过 /memory 查看，不能打断主交互。
        return MemoryUpdateReport(ok=True, message="", noop=True)

    def update_now(self, state: AgentState, mode: AgentMode = "chat") -> MemoryUpdateReport:
        start = max(0, len(state.messages) - 6)
        return self.updater.update_from_turn(
            self.provider,
            state.memory.session_id,
            mode,
            state.messages[start:],
            state.memory.memory_index_text,
        )

    def rebuild_index(self, state: AgentState) -> str:
        result = self.memory_index.rebuild()
        state.memory.memory_index_text = self.memory_index.load_text()
        return f"记忆索引已重建: lines={result.lines} bytes={result.bytes} notes={result.note_count}"

    def list_sessions(self):
        return self.session_store.list_sessions()

    def resume_session(
        self,
        session_id: str,
        state: AgentState,
        context_manager: ContextManager,
        tool_context: ToolContext,
        config: LLMConfig,
    ) -> ResumeReport:
        recovered = self.session_store.recover(session_id)
        if not recovered.messages and recovered.warnings:
            return ResumeReport(False, session_id, recovered.warnings[0], warnings=recovered.warnings)
        state.messages[:] = recovered.messages
        if self.recorder is not None:
            self.recorder.close()
        self.recorder = self.session_store.open(session_id)
        state.memory.session_id = session_id
        self.refresh_prompt_memory(state)
        compacted = False
        estimate = context_manager.estimator.estimate_messages(state.messages)
        threshold = config.context.window_tokens - config.context.manual_margin_tokens
        if estimate.tokens >= threshold:
            report = context_manager.manual_compact(self.provider, state, tool_context, config, None, [])
            compacted = report.kind == "summary"
        return ResumeReport(
            True,
            session_id,
            f"已恢复会话 {session_id}",
            restored_messages=len(state.messages),
            skipped_bad_lines=recovered.skipped_bad_lines,
            truncated=recovered.truncated,
            time_gap_inserted=recovered.time_gap_inserted,
            compacted=compacted,
            warnings=recovered.warnings,
        )

    def clear_current_session(self, state: AgentState) -> None:
        if self.recorder is not None:
            self.recorder.append_event("clear")
            self.recorder.close()
        self.recorder = self.session_store.open()
        state.memory.session_id = self.recorder.session_id
        state.memory.last_error = ""

    def cleanup_sessions(self, state: AgentState) -> int:
        return self.session_store.cleanup_expired(state.memory.session_id)

    def status(self, state: AgentState) -> MemoryStatus:
        project_notes = len(self.note_store.list_notes("project"))
        user_notes = len(self.note_store.list_notes("user"))
        index_text = state.memory.memory_index_text
        return MemoryStatus(
            enabled=self.settings.enabled,
            session_id=state.memory.session_id,
            project_notes=project_notes,
            user_notes=user_notes,
            index_lines=len(index_text.splitlines()) if index_text else 0,
            index_bytes=len(index_text.encode("utf-8")) if index_text else 0,
            pending_updates=state.memory.pending_updates,
            last_update_at=state.memory.last_update_at,
            last_error=state.memory.last_error,
            warnings=tuple(state.memory.warnings),
        )

    def close(self) -> None:
        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None
        if self.executor is not None:
            self.executor.shutdown(wait=True)
