"""统一 Runtime Event。

事件类型取自 specs/017-web-studio/plan.md 的 Append-only session events 一节。
那份清单写的是"至少包括"，这里在它之上补了三个**映射 AgentEvent 时确实需要**的类型，
以及一个未知类型的哨兵：

- ``memory_updated``  —— Agent 的 ``kind="memory"`` 没有对应的计划类型
- ``error``           —— 运行中途的错误（区别于结束整个 Run 的 ``run_failed``）
- ``unknown``         —— 反序列化时遇到不认识类型的哨兵，见 ``from_dict``

**未知类型一律降级为 internal 可见性。** 一个我们看不懂的载荷可能包含任何东西，
默认不让普通成员看到是唯一安全的默认值（C59）。反过来做——"不认识就当作
用户可见"——会把将来某个版本的内部事件泄露给所有人。

两个归一化在 ``__post_init__`` 里做，不依赖调用方自觉：

1. ``occurred_at`` 统一成 aware UTC。数据库读出来的时间可能是 naive 的
   （SQLite 不存 tzinfo，见 db/base.py 的 as_utc），不归一化就会在比较时抛
   TypeError——T5 踩过这个坑。
2. ``visibility`` 缺省时按事件类型取默认值；值不认识时按 internal 处理（fail closed）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

RuntimeEventType = Literal[
    "run_queued",
    "run_started",
    "assistant_text_delta",
    "thinking_delta",
    "tool_call_started",
    "tool_call_progress",
    "tool_call_finished",
    "tool_approval_requested",
    "tool_approval_resolved",
    "context_compacted",
    "usage_updated",
    "memory_updated",
    "error",
    "run_completed",
    "run_failed",
    "run_cancelled",
    "unknown",
]

Visibility = Literal["user", "admin", "internal"]

UNKNOWN_EVENT_TYPE: RuntimeEventType = "unknown"

# 不含 unknown：它是反序列化时的哨兵，不是生产者会主动选择的类型。
KNOWN_EVENT_TYPES: frozenset[str] = frozenset({
    "run_queued",
    "run_started",
    "assistant_text_delta",
    "thinking_delta",
    "tool_call_started",
    "tool_call_progress",
    "tool_call_finished",
    "tool_approval_requested",
    "tool_approval_resolved",
    "context_compacted",
    "usage_updated",
    "memory_updated",
    "error",
    "run_completed",
    "run_failed",
    "run_cancelled",
})

VISIBILITIES: frozenset[str] = frozenset({"user", "admin", "internal"})

TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({
    "run_completed", "run_failed", "run_cancelled",
})

# 每个类型的默认可见性。目前全部面向用户，因为 SSE 推送的就是这些；
# 将来若新增只给管理员看的事件，在这里改一处即可。
DEFAULT_VISIBILITY: dict[str, Visibility] = {name: "user" for name in KNOWN_EVENT_TYPES}
DEFAULT_VISIBILITY[UNKNOWN_EVENT_TYPE] = "internal"


class EventDecodeError(ValueError):
    """事件载荷缺失或类型不对。

    异常只带字段名，**不回显原始载荷**——载荷里可能有密钥或用户内容，
    错误信息会进日志。
    """


def _parse_uuid(value: Any, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str) or not value:
        raise EventDecodeError(field_name)
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise EventDecodeError(field_name) from None


def _parse_moment(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value:
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            raise EventDecodeError(field_name) from None
    else:
        raise EventDecodeError(field_name)
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class RuntimeEvent:
    """一条运行时事件。不可变：事件是只追加的，改它没有语义。"""

    type: RuntimeEventType
    session_id: UUID
    sequence: int
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: UUID = field(default_factory=uuid4)
    run_id: UUID | None = None
    visibility: Visibility | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool):
            raise EventDecodeError("sequence")
        if self.sequence < 0:
            raise EventDecodeError("sequence")

        visibility = self.visibility
        if visibility is None:
            visibility = DEFAULT_VISIBILITY.get(self.type, "internal")
        elif visibility not in VISIBILITIES:
            # fail closed：不认识的可见性按最严格处理
            visibility = "internal"
        object.__setattr__(self, "visibility", visibility)

        # 统一成 aware UTC，避免与 datetime.now(timezone.utc) 比较时抛 TypeError
        object.__setattr__(self, "occurred_at", _parse_moment(self.occurred_at, "occurred_at"))

        if not isinstance(self.payload, dict):
            raise EventDecodeError("payload")

    @property
    def is_terminal(self) -> bool:
        return self.type in TERMINAL_EVENT_TYPES

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "session_id": str(self.session_id),
            "run_id": str(self.run_id) if self.run_id is not None else None,
            "sequence": self.sequence,
            "type": self.type,
            "payload": self.payload,
            "visibility": self.visibility,
            "occurred_at": self.occurred_at.astimezone(timezone.utc).isoformat(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuntimeEvent":
        """从字典还原；不认识的事件类型降级为 unknown 且强制 internal。"""
        if not isinstance(data, Mapping):
            raise EventDecodeError("event")

        raw_type = data.get("type")
        if not isinstance(raw_type, str) or not raw_type:
            raise EventDecodeError("type")

        payload = data.get("payload")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise EventDecodeError("payload")

        if raw_type in KNOWN_EVENT_TYPES:
            event_type: str = raw_type
            visibility = data.get("visibility") or DEFAULT_VISIBILITY[raw_type]
        else:
            # 保留原文，否则排查时不知道遇到了什么；但载荷对我们是不透明的，
            # 因此整体按 internal 处理，不推送给普通成员。
            event_type = UNKNOWN_EVENT_TYPE
            payload = {"original_type": raw_type, "raw": payload}
            visibility = "internal"

        if visibility not in VISIBILITIES:
            visibility = "internal"

        run_id = data.get("run_id")

        return cls(
            type=event_type,  # type: ignore[arg-type]
            session_id=_parse_uuid(data.get("session_id"), "session_id"),
            run_id=_parse_uuid(run_id, "run_id") if run_id is not None else None,
            sequence=data.get("sequence"),  # type: ignore[arg-type]
            payload=payload,
            event_id=_parse_uuid(data.get("event_id"), "event_id") if data.get("event_id") else uuid4(),
            visibility=visibility,  # type: ignore[arg-type]
            occurred_at=_parse_moment(data.get("occurred_at"), "occurred_at")
            if data.get("occurred_at") is not None
            else datetime.now(timezone.utc),
        )

    @classmethod
    def from_json(cls, raw: str) -> "RuntimeEvent":
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            raise EventDecodeError("event") from None
        return cls.from_dict(data)


def visible_to(event: RuntimeEvent, role: str) -> bool:
    """该角色能否看到这条事件。

    ``user`` 级对所有工作区成员可见；``admin`` 级只给 admin 与 owner；
    ``internal`` 级不通过 SSE 推送，只留在数据库供审计（C59）。
    """
    if event.visibility == "user":
        return True
    if event.visibility == "admin":
        return role in ("admin", "owner")
    return False
