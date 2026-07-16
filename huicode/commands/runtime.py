from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import TextIO

from huicode.agent_events import AgentMode, AgentState
from huicode.config import LLMConfig
from huicode.context import ContextLifecycleCallbacks, ContextManager
from huicode.hooks import HookManager
from huicode.hooks.events import context_data, make_event
from huicode.memory.manager import MemoryManager
from huicode.mcp import MCPManager
from huicode.permissions import PermissionContext
from huicode.providers.base import Provider
from huicode.providers.base import ConversationMessage
from huicode.skills.manager import SkillManager
from huicode.skills.types import SkillRunResult
from huicode.subagents.catalog import AgentCatalog
from huicode.subagents.manager import SubagentManager
from huicode.tools.base import ToolContext
from huicode.tools.registry import ToolRegistry

from .ui import CommandMode


SendUserMessage = Callable[[str, AgentMode, bool], None]


class CLICommandRuntime:
    def __init__(
        self,
        *,
        provider: Provider,
        config: LLMConfig,
        tool_registry: ToolRegistry,
        tool_context: ToolContext,
        state: AgentState,
        context_manager: ContextManager,
        permission_context: PermissionContext,
        send_user_message: SendUserMessage,
        memory_manager: MemoryManager | None = None,
        mcp_manager: MCPManager | None = None,
        skill_manager: SkillManager | None = None,
        isolated_skill_runner: Callable[[str, str], SkillRunResult] | None = None,
        hook_manager: HookManager | None = None,
        agent_catalog: AgentCatalog | None = None,
        subagent_manager: SubagentManager | None = None,
        output: TextIO | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.tool_registry = tool_registry
        self.tool_context = tool_context
        self.state = state
        self.context_manager = context_manager
        self.permission_context = permission_context
        self.memory_manager = memory_manager
        self.mcp_manager = mcp_manager
        self.skill_manager = skill_manager
        self.isolated_skill_runner = isolated_skill_runner
        self.hook_manager = hook_manager
        self.agent_catalog = agent_catalog
        self.subagent_manager = subagent_manager
        self.output = output or sys.stdout
        self._send_user_message = send_user_message
        self._mode: CommandMode = "default"
        self.show_usage = config.show_usage
        self.exit_requested = False
        self._refresh_callback: Callable[[], None] | None = None

    def show_message(self, message: str, *, error: bool = False) -> None:
        print(message, file=self.output)

    def send_user_message(self, message: str) -> None:
        mode: AgentMode = "plan" if self._mode == "plan" else "chat"
        try:
            self._send_user_message(message, mode, self.show_usage)
        finally:
            self.refresh_status()

    def get_mode(self) -> CommandMode:
        return self._mode

    def set_mode(self, mode: CommandMode) -> None:
        self._mode = mode

    def get_token_status(self) -> dict[str, object]:
        last = self.state.context.last_input_tokens
        if last is None:
            last = self.state.context.last_estimated_request_tokens
        return {
            "last": last,
            "window": self.config.context.window_tokens,
            "summary_count": self.state.context.summary_count,
            "fuse": self.state.context.summary_fuse_open,
        }

    def refresh_status(self) -> None:
        if self._refresh_callback is not None:
            try:
                self._refresh_callback()
            except Exception:
                pass

    def set_refresh_callback(self, callback: Callable[[], None] | None) -> None:
        self._refresh_callback = callback

    def compact(self) -> str:
        report = self.context_manager.manual_compact(
            provider=self.provider,
            state=self.state,
            context=self.tool_context,
            config=self.config,
            prompt=None,
            tools=[],
            callbacks=self._context_callbacks(),
        )
        self.refresh_status()
        if report.kind == "summary":
            return f"上下文摘要已生成: {report.tokens_before} -> {report.tokens_after} tokens"
        if report.kind == "failure":
            return f"上下文压缩失败: {report.message}"
        if report.kind == "fuse":
            return report.message or "上下文摘要已熔断"
        if report.kind == "lightweight":
            return f"上下文已整理: 释放约 {report.tokens_freed} tokens"
        return f"上下文压缩跳过: {report.message}"

    def clear(self) -> str:
        self.state.messages.clear()
        self.state.last_plan = ""
        self.state.cancel_requested = False
        self.state.unknown_tool_count = 0
        self.state.iterations = 0
        self.context_manager.reset(self.state)
        if self.skill_manager is not None:
            self.skill_manager.clear_state(self.state.skills)
        if self.hook_manager is not None:
            self.hook_manager.clear_transient(self.state.hooks)
        if self.subagent_manager is not None:
            self.subagent_manager.clear()
        if self.memory_manager is not None:
            self.memory_manager.clear_current_session(self.state)
        self._mode = "default"
        self.refresh_status()
        return "本次工作上下文和计划状态已清空，已开启新会话。"

    def agent_status(self, arguments: str) -> str:
        if self.agent_catalog is None:
            return "子 Agent 系统未启用"
        target = arguments.strip().lower()
        if target:
            definition = self.agent_catalog.get(target)
            if definition is None:
                return f"未知子 Agent 角色: {arguments}"
            return "\n".join(
                [
                    f"agent: {definition.name}",
                    f"description: {definition.description}",
                    f"source: {definition.source}",
                    f"model: {definition.model}",
                    f"max_iterations: {definition.max_iterations}",
                    f"permission: {definition.permission_mode}",
                    f"allowed_tools: {', '.join(definition.allowed_tools) or 'none'}",
                    f"denied_tools: {', '.join(definition.denied_tools) or 'none'}",
                    f"entry: {definition.source_path}",
                ]
            )
        lines = ["agents:"]
        for definition in self.agent_catalog.list():
            lines.append(
                f"- {definition.name} [{definition.source}/{definition.model}] "
                f"{definition.description}"
            )
        if len(lines) == 1:
            lines.append("- none")
        lines.append("使用 /agents <name> 查看安全元数据。")
        return "\n".join(lines)

    def task_status(self, arguments: str) -> str:
        if self.subagent_manager is None:
            return "子 Agent 系统未启用"
        target = arguments.strip()
        if target:
            task = self.subagent_manager.task_detail(target)
            if task is None:
                return f"未知子 Agent 任务: {target}"
            return "\n".join(
                [
                    f"task: {task.id}",
                    f"type: {task.type}",
                    f"role: {task.role or 'none'}",
                    f"status: {task.status}",
                    f"background: {str(task.background).lower()}",
                    f"iterations: {task.iterations}",
                    f"stop_reason: {task.stop_reason or 'none'}",
                    f"usage: {json.dumps(task.usage, ensure_ascii=False, sort_keys=True)}",
                    f"summary: {task.summary or 'none'}",
                    f"error: {task.error or 'none'}",
                ]
            )
        tasks = self.subagent_manager.list_tasks()
        lines = ["tasks:"]
        for task in tasks:
            summary = (task.summary or task.task).replace("\n", " ")[:100]
            lines.append(
                f"- {task.id} [{task.status}/{task.type}] role={task.role or 'none'} {summary}"
            )
        if not tasks:
            lines.append("- none")
        return "\n".join(lines)

    def run_skill(self, name: str, arguments: str) -> str:
        if self.skill_manager is None:
            return "Skill 系统未启用"
        definition = self.skill_manager.get(name)
        if definition is None:
            return f"Skill {name} 已不存在，请重试。"
        if definition.mode == "shared":
            self.skill_manager.activate_shared(self.state.skills, name, arguments)
            task = arguments or f"执行 Skill {name}"
            self.send_user_message(task)
            return ""
        if self.isolated_skill_runner is None:
            return f"Skill {name} 的隔离执行器不可用"
        turn_start = len(self.state.messages)
        request = ConversationMessage(
            role="user",
            content=f'<huicode_context type="skill_request" name="{name}">{arguments}</huicode_context>',
        )
        self.state.messages.append(request)
        if self.memory_manager is not None:
            self.memory_manager.record_message(self.state, request)
        result = self.isolated_skill_runner(name, arguments)
        response = ConversationMessage(role="assistant", content=result.summary)
        self.state.messages.append(response)
        if self.memory_manager is not None:
            self.memory_manager.record_message(self.state, response)
            if result.ok:
                mode = "plan" if self._mode == "plan" else "chat"
                self.memory_manager.schedule_update_after_final(self.state, mode, turn_start)
        self.refresh_status()
        prefix = "完成" if result.ok else "失败"
        return f"Skill {name} {prefix}: {result.summary}"

    def skill_status(self, arguments: str) -> str:
        if self.skill_manager is None:
            return "Skill 系统未启用"
        target = arguments.strip().lower()
        if target:
            definition = self.skill_manager.get(target)
            if definition is None:
                return f"未加载 Skill: {arguments}"
            active = "yes" if target in self.state.skills.active else "no"
            tools = ", ".join(definition.allowed_tools) or "none"
            return "\n".join(
                [
                    f"skill: {definition.name}",
                    f"description: {definition.description}",
                    f"mode: {definition.mode}",
                    f"source: {definition.source}",
                    f"active: {active}",
                    f"allowed_tools: {tools}",
                    f"entry: {definition.entry_path}",
                ]
            )
        lines = ["skills:"]
        for definition in self.skill_manager.snapshot.definitions.values():
            marker = "*" if definition.name in self.state.skills.active else "-"
            lines.append(
                f"{marker} {definition.name} [{definition.mode}/{definition.source}] "
                f"{definition.description}"
            )
        if len(lines) == 1:
            lines.append("- none")
        lines.append("使用 /skill <name> 查看详情；使用 /<name> [arguments] 执行。")
        return "\n".join(lines)

    def session(self, arguments: str) -> str:
        if self.memory_manager is None:
            return "记忆系统未启用"
        if not arguments:
            return self._format_sessions()
        if arguments == "clean":
            removed = self.memory_manager.cleanup_sessions(self.state)
            return f"已清理过期会话 {removed} 个"
        if arguments.startswith("resume "):
            session_id = arguments.split(maxsplit=1)[1].strip()
            report = self.memory_manager.resume_session(
                session_id,
                self.state,
                self.context_manager,
                self.tool_context,
                self.config,
            )
            self.refresh_status()
            return self._format_resume_report(report)
        return "用法: /session [resume <session-id>|clean]"

    def memory(self, arguments: str) -> str:
        if self.memory_manager is None:
            return "记忆系统未启用"
        if arguments == "update":
            mode: AgentMode = "plan" if self._mode == "plan" else "chat"
            report = self.memory_manager.update_now(self.state, mode)
            self.refresh_status()
            return report.message
        if arguments == "rebuild":
            message = self.memory_manager.rebuild_index(self.state)
            self.refresh_status()
            return message
        return self._format_memory_summary()

    def permission(self, arguments: str) -> str:
        if arguments:
            self.permission_context.mode = arguments  # type: ignore[assignment]
        return self._format_permission_summary()

    def status(self) -> str:
        tokens = self.get_token_status()
        lines = [
            f"mode: {self.mode_label()}",
            f"provider: {self.provider.name} / {self.provider.model}",
            (
                "context: "
                f"last={tokens['last'] if tokens['last'] is not None else '-'} "
                f"window={tokens['window']} summaries={tokens['summary_count']} "
                f"fuse={str(tokens['fuse']).lower()}"
            ),
            f"permission: {self._format_permission_summary()}",
            f"mcp: {self._format_mcp_summary()}",
            f"memory: {self._format_memory_summary(compact=True)}",
            f"skills: {self._format_skill_summary()}",
            f"hooks: {self._format_hook_summary()}",
            f"subagents: {self._format_subagent_summary()}",
        ]
        return "\n".join(lines)

    def _format_subagent_summary(self) -> str:
        if self.subagent_manager is None:
            return "queued=0 running=0 ready=0 failed=0"
        status = self.subagent_manager.summary()
        return " ".join(f"{key}={status[key]}" for key in ("queued", "running", "ready", "failed"))

    def _format_skill_summary(self) -> str:
        if self.skill_manager is None:
            return "enabled=false"
        snapshot = self.skill_manager.snapshot
        active = ",".join(self.state.skills.active) or "none"
        allowed = self.skill_manager.active_allowed_tools(self.state.skills)
        tools = ",".join(sorted(allowed)) if allowed is not None else "base"
        return (
            f"discovered={len(snapshot.definitions)} active={active} "
            f"reload_errors={self.skill_manager.reload_errors} tools={tools}"
        )

    def _format_hook_summary(self) -> str:
        if self.hook_manager is None:
            return "effective=0 pending=0 failed=0"
        status = self.hook_manager.summary()
        return (
            f"effective={status.effective} disabled={status.disabled} pending={status.pending} "
            f"failed={status.failed} denied={status.denied} log={status.log_path}"
        )

    def _context_callbacks(self) -> ContextLifecycleCallbacks | None:
        if self.hook_manager is None:
            return None
        manager = self.hook_manager
        mode: AgentMode = "plan" if self._mode == "plan" else "chat"

        def before(values: dict[str, object]) -> None:
            manager.dispatch(
                make_event(
                    "context_before_compact",
                    session_id=manager.session_id,
                    workspace=self.tool_context.workspace,
                    mode=mode,
                    turn_id=self.state.hooks.turn_id or None,
                    iteration=self.state.iterations,
                    data=context_data(**values),
                ),
                self.state.hooks,
            )

        def after(report) -> None:  # noqa: ANN001
            manager.dispatch(
                make_event(
                    "context_after_compact",
                    session_id=manager.session_id,
                    workspace=self.tool_context.workspace,
                    mode=mode,
                    turn_id=self.state.hooks.turn_id or None,
                    iteration=self.state.iterations,
                    data=context_data(report),
                ),
                self.state.hooks,
            )

        return ContextLifecycleCallbacks(before_compact=before, after_compact=after)

    def context_status(self) -> str:
        state = self.state.context
        settings = self.config.context
        return (
            f"context enabled={str(settings.enabled).lower()}"
            f" window={settings.window_tokens}"
            f" auto_margin={settings.auto_margin_tokens}"
            f" manual_margin={settings.manual_margin_tokens}"
            f" last_input_tokens={state.last_input_tokens}"
            f" last_estimated_request_tokens={state.last_estimated_request_tokens}"
            f" summary_count={state.summary_count}"
            f" failure_count={state.summary_failure_count}"
            f" fuse={str(state.summary_fuse_open).lower()}"
        )

    def toggle_verbose(self) -> str:
        self.show_usage = not self.show_usage
        return f"详细用量显示已{'开启' if self.show_usage else '关闭'}。"

    def last(self, arguments: str) -> str:
        count = self._parse_last_count(arguments)
        tool_messages = [
            message
            for message in self.state.messages
            if message.role == "tool" and message.tool_result is not None
        ]
        if not tool_messages:
            return "还没有可展开的工具结果。"
        selected = tool_messages[-count:]
        return "\n\n".join(
            self._format_tool_message(message, index)
            for index, message in enumerate(selected, start=1)
        )

    def request_exit(self) -> None:
        self.exit_requested = True

    def mode_label(self) -> str:
        return "[PLAN]" if self._mode == "plan" else "[DEFAULT]"

    def input_prompt(self) -> str:
        return f"\n{self.mode_label()} You> "

    def toolbar_text(self) -> str:
        tokens = self.get_token_status()
        last = tokens["last"] if tokens["last"] is not None else "-"
        return (
            f"{self.mode_label()}  tokens: {last}/{tokens['window']}  "
            f"permission: {self.permission_context.mode}  memory: {self._memory_toolbar_status()} "
            f"skills: {len(self.state.skills.active)}  tasks: {self._task_toolbar_status()}"
        )

    def _task_toolbar_status(self) -> str:
        if self.subagent_manager is None:
            return "0/0"
        status = self.subagent_manager.summary()
        return f"{status['running'] + status['queued']}/{status['ready']}"

    def _memory_toolbar_status(self) -> str:
        if self.memory_manager is None:
            return "off"
        if self.state.memory.last_error:
            return "error"
        if self.state.memory.pending_updates:
            return "updating"
        return "ready"

    def _format_permission_summary(self) -> str:
        sources: dict[str, int] = {}
        rules = self.permission_context.session_rules + self.permission_context.rules
        for rule in rules:
            sources[rule.source] = sources.get(rule.source, 0) + 1
        source_text = ", ".join(
            f"{source}={count}" for source, count in sorted(sources.items())
        ) or "none"
        return f"mode={self.permission_context.mode} rules={len(rules)} sources={source_text}"

    def _format_mcp_summary(self) -> str:
        if self.mcp_manager is None:
            return "servers=0/0 tools=0 errors=0"
        return (
            f"servers={self.mcp_manager.active_server_count}/{self.mcp_manager.server_count}"
            f" tools={self.mcp_manager.tool_count} errors={len(self.mcp_manager.errors)}"
        )

    def _format_memory_summary(self, compact: bool = False) -> str:
        if self.memory_manager is None:
            return "enabled=false"
        status = self.memory_manager.status(self.state)
        error = status.last_error or "none"
        base = (
            f"enabled={str(status.enabled).lower()} session={status.session_id}"
            f" project_notes={status.project_notes} user_notes={status.user_notes}"
            f" index_bytes={status.index_bytes} pending={status.pending_updates} error={error}"
        )
        if compact:
            return base
        warnings = "; ".join(status.warnings) if status.warnings else "none"
        return (
            f"memory {base} index_lines={status.index_lines}"
            f" last_update={status.last_update_at or 'none'} warnings={warnings}"
        )

    def _format_sessions(self) -> str:
        sessions = self.memory_manager.list_sessions() if self.memory_manager else []
        if not sessions:
            return "暂无会话存档\n使用 /session resume <session-id> 恢复指定会话。"
        lines = ["sessions:"]
        for session in sessions[:20]:
            warning_text = f" warnings={len(session.warnings)}" if session.warnings else ""
            lines.append(
                f"- {session.session_id} messages={session.message_count}"
                f" updated={session.updated_at or 'unknown'} title={session.title}{warning_text}"
            )
        lines.append("使用 /session resume <session-id> 恢复指定会话。")
        return "\n".join(lines)

    @staticmethod
    def _format_resume_report(report) -> str:  # noqa: ANN001
        lines = [report.message]
        if report.ok:
            lines.append(
                " ".join(
                    [
                        f"restored={report.restored_messages}",
                        f"bad_lines={report.skipped_bad_lines}",
                        f"truncated={str(report.truncated).lower()}",
                        f"time_gap={str(report.time_gap_inserted).lower()}",
                        f"compacted={str(report.compacted).lower()}",
                    ]
                )
            )
        lines.extend(f"warning: {warning}" for warning in report.warnings)
        return "\n".join(lines)

    @staticmethod
    def _parse_last_count(arguments: str) -> int:
        if not arguments:
            return 1
        try:
            return max(1, min(int(arguments.strip()), 5))
        except ValueError:
            return 1

    @staticmethod
    def _format_tool_message(message, index: int) -> str:  # noqa: ANN001
        result = message.tool_result
        header = f"[{index}] {message.tool_name or 'Tool'}: {result.summary}"
        if message.tool_name == "Bash" and result.data:
            return "\n".join(
                [
                    header,
                    f"command: {result.data.get('command', '')}",
                    f"returncode: {result.data.get('returncode', '')}",
                    "stdout:",
                    str(result.data.get("stdout", "")),
                    "stderr:",
                    str(result.data.get("stderr", "")),
                ]
            )
        if message.tool_name == "Read" and result.data:
            return "\n".join(
                [header, f"path: {result.data.get('path', '')}", "content:", str(result.data.get("content", ""))]
            )
        detail = result.data if result.ok else (result.error.to_dict() if result.error else {})
        return f"{header}\n{json.dumps(detail, ensure_ascii=False, indent=2)}"
