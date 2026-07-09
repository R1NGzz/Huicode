from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path

from huicode.agent_events import AgentMode
from huicode.config import LLMConfig, MemoryConfig
from huicode.memory.index import MemoryIndex
from huicode.memory.notes import NoteStore
from huicode.memory.scrub import scrub_secrets
from huicode.memory.types import MemoryNote, MemoryUpdateReport
from huicode.providers.base import ConversationMessage, Provider


class MemoryUpdater:
    def __init__(
        self,
        workspace: Path,
        settings: MemoryConfig,
        config: LLMConfig,
        note_store: NoteStore | None = None,
        memory_index: MemoryIndex | None = None,
    ) -> None:
        self.workspace = workspace
        self.settings = settings
        self.config = config
        self.note_store = note_store or NoteStore(workspace)
        self.memory_index = memory_index or MemoryIndex(workspace, settings, self.note_store)

    def update_from_turn(
        self,
        provider: Provider,
        session_id: str,
        mode: AgentMode,
        turn_messages: list[ConversationMessage],
        current_index: str,
    ) -> MemoryUpdateReport:
        if not self.settings.enabled:
            return MemoryUpdateReport(ok=True, message="记忆系统未启用", noop=True)
        if mode == "plan":
            return MemoryUpdateReport(ok=True, message="Plan Mode 不写入长期记忆", noop=True)
        if not turn_messages:
            return MemoryUpdateReport(ok=True, message="没有可整理内容", noop=True)
        prompt = self._build_prompt(session_id, turn_messages, current_index)
        text_parts: list[str] = []
        try:
            for event in provider.stream_chat(
                [ConversationMessage(role="user", content=prompt)],
                tools=[],
                allow_tool_calls=False,
                prompt=None,
            ):
                if event.tool_call is not None:
                    return MemoryUpdateReport(ok=False, message="记忆更新阶段不允许工具调用")
                if event.kind == "text":
                    text_parts.append(event.text)
        except Exception as exc:
            return MemoryUpdateReport(ok=False, message=f"记忆更新失败: {exc}")
        raw_text = "".join(text_parts).strip()
        try:
            payload = _extract_json(raw_text)
        except ValueError as exc:
            return MemoryUpdateReport(ok=False, message=f"记忆更新 JSON 解析失败: {exc}")
        return self._apply_operations(payload, session_id)

    def _build_prompt(self, session_id: str, turn_messages: list[ConversationMessage], current_index: str) -> str:
        messages_text = "\n".join(_summarize_message(message) for message in turn_messages)
        return (
            "你正在为 HuiCode 更新长期记忆。禁止调用任何工具，只返回 JSON。\n"
            "可用分类: preference, correction, project_knowledge, reference。\n"
            "scope 只能是 user 或 project。项目知识默认 project，跨项目偏好默认 user。\n"
            "不要保存临时状态、一次性任务步骤、API key、token、password 或认证 header。\n"
            "如果没有稳定新信息，返回 {\"operations\":[{\"action\":\"noop\",\"reason\":\"...\"}]}。\n\n"
            f"session_id: {session_id}\n"
            f"当前记忆索引:\n{current_index}\n\n"
            f"本轮对话:\n{messages_text}\n\n"
            "返回 JSON 格式: {\"operations\":[{\"action\":\"create|update|delete|noop\", ...}]}"
        )

    def _apply_operations(self, payload: dict[str, object], session_id: str) -> MemoryUpdateReport:
        operations = payload.get("operations")
        if not isinstance(operations, list):
            return MemoryUpdateReport(ok=False, message="记忆更新缺少 operations 列表")
        created = updated = deleted = 0
        noop = False
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        for raw in operations:
            if not isinstance(raw, dict):
                return MemoryUpdateReport(ok=False, message="记忆操作必须是对象")
            action = str(raw.get("action") or "")
            if action == "noop":
                noop = True
                continue
            if action == "create":
                note = MemoryNote(
                    note_id=str(raw.get("id") or f"mem-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"),
                    scope=str(raw.get("scope") or "project"),  # type: ignore[arg-type]
                    category=str(raw.get("category") or "project_knowledge"),  # type: ignore[arg-type]
                    title=scrub_secrets(str(raw.get("title") or "未命名记忆")),
                    summary=scrub_secrets(str(raw.get("summary") or "")),
                    body=scrub_secrets(str(raw.get("body") or raw.get("summary") or "")),
                    source_session=session_id,
                    created_at=now,
                    updated_at=now,
                )
                self.note_store.create_note(note)
                created += 1
                continue
            if action == "update":
                note_id = str(raw.get("id") or "")
                if not note_id:
                    return MemoryUpdateReport(ok=False, message="update 操作缺少 id")
                path = self.note_store.update_note(
                    note_id,
                    {
                        "title": scrub_secrets(str(raw.get("title") or "")),
                        "summary": scrub_secrets(str(raw.get("summary") or "")),
                        "body": scrub_secrets(str(raw.get("body") or "")),
                        "updated_at": now,
                    },
                )
                if path is not None:
                    updated += 1
                continue
            if action == "delete":
                if self.note_store.delete_note(str(raw.get("id") or "")):
                    deleted += 1
                continue
            return MemoryUpdateReport(ok=False, message=f"未知记忆操作: {action}")
        self.memory_index.rebuild()
        return MemoryUpdateReport(
            ok=True,
            message="记忆已更新" if not noop or created or updated or deleted else "没有需要更新的记忆",
            created=created,
            updated=updated,
            deleted=deleted,
            noop=noop and not (created or updated or deleted),
        )


def _summarize_message(message: ConversationMessage) -> str:
    if message.role == "tool" and message.tool_result is not None:
        return f"tool:{message.tool_name or ''}: {message.tool_result.summary}"
    if message.tool_calls:
        calls = ", ".join(call.name for call in message.tool_calls)
        return f"{message.role}: {message.content} [tool_calls: {calls}]"
    return f"{message.role}: {message.content}"


def _extract_json(text: str) -> dict[str, object]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("未找到 JSON 对象") from None
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("顶层 JSON 必须是对象")
    return parsed
