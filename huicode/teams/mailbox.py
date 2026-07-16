from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .naming import new_id, validate_name
from .storage import TeamStore, append_jsonl, read_jsonl
from .types import TeamError, TeamMessage, record_dict


ALLOWED_MESSAGE_TYPES = {"text", "assignment", "plan_request", "plan_decision", "progress", "completion", "idle", "wake", "stop"}


class NameRegistry:
    def __init__(self, names: tuple[str, ...] = ("lead",)) -> None:
        self._names = {validate_name(item, "成员名") for item in names}

    def add(self, name: str) -> None:
        value = validate_name(name, "成员名")
        if value in self._names:
            raise TeamError("duplicate_member", f"成员名已存在: {value}")
        self._names.add(value)

    def resolve(self, name: str) -> str:
        value = validate_name(name, "成员名")
        if value not in self._names:
            raise TeamError("unknown_member", f"未知团队成员: {value}")
        return value

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._names))


class MailboxStore:
    def __init__(self, store: TeamStore, registry: NameRegistry) -> None:
        self.store = store
        self.registry = registry

    def send(self, sender: str, recipients: tuple[str, ...], body: str, *, message_type: str = "text", summary: str = "", correlation_id: str = "", task_id: str | None = None, payload: dict[str, object] | None = None) -> TeamMessage:
        sender_name = self.registry.resolve(sender)
        targets = tuple(self.registry.resolve(item) for item in recipients)
        if not targets:
            raise TeamError("invalid_message", "消息至少需要一个收件人")
        if message_type not in ALLOWED_MESSAGE_TYPES:
            raise TeamError("invalid_message_type", f"未知团队消息类型: {message_type}")
        if message_type != "text" and not correlation_id:
            raise TeamError("invalid_message", "结构化消息必须提供 correlation_id")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        message = TeamMessage(new_id("msg"), sender_name, targets, body, summary or body[:120], message_type, correlation_id or new_id("corr"), task_id, now, False, payload or {})
        for target in targets:
            with self.store.lock(f"mailbox-{target}"):
                append_jsonl(self.store.paths.mailbox(target), record_dict(message))
        return message

    def broadcast(self, sender: str, body: str, **kwargs) -> TeamMessage:  # noqa: ANN003
        targets = tuple(name for name in self.registry.names() if name != self.registry.resolve(sender))
        return self.send(sender, targets, body, **kwargs)

    def inbox(self, member: str, *, unread_only: bool = False) -> tuple[tuple[TeamMessage, ...], tuple[str, ...]]:
        name = self.registry.resolve(member)
        records, warnings = read_jsonl(self.store.paths.mailbox(name))
        messages = tuple(_message(item) for item in records)
        if unread_only:
            messages = tuple(item for item in messages if not item.read)
        return messages, warnings

    def mark_read(self, member: str, message_id: str) -> TeamMessage:
        name = self.registry.resolve(member)
        with self.store.lock(f"mailbox-{name}"):
            messages, _ = self.inbox(name)
            found = None
            path = self.store.paths.mailbox(name)
            path.unlink(missing_ok=True)
            for item in messages:
                if item.id == message_id:
                    item = replace(item, read=True)
                    found = item
                append_jsonl(path, record_dict(item))
            if found is None:
                raise TeamError("unknown_message", f"未知团队消息: {message_id}")
            return found


def _message(raw: dict[str, object]) -> TeamMessage:
    try:
        return TeamMessage(
            id=str(raw["id"]), sender=str(raw["sender"]), recipients=tuple(raw["recipients"]),
            body=str(raw["body"]), summary=str(raw["summary"]), type=str(raw["type"]),
            correlation_id=str(raw["correlation_id"]), task_id=raw.get("task_id") if raw.get("task_id") is None else str(raw["task_id"]),
            timestamp=str(raw["timestamp"]), read=bool(raw.get("read", False)), payload=dict(raw.get("payload") or {}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TeamError("invalid_message", f"团队消息字段无效: {exc}") from exc
