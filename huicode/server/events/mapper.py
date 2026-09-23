"""把 Agent 的 `AgentEvent` 映射成 `RuntimeEvent`。

**AgentEvent 的载荷位置并不统一**，这里按 `huicode/agent.py` 的实际产出逐个处理，
不假设统一形状：

- 文本类（text / thinking）内容在 `text` 字段；
- error / memory / usage / context 把内容放在 `data` 字典里；
- tool_call / tool_result 把对象放在 `tool_call` / `tool_result` 字段。

**工具参数值进载荷，但先过一道大小闸门。** T7 落地时这里只带参数名、不带值——
因为当时持久化会先于脱敏落地，写进去就会有一段时间数据库里躺着未脱敏内容。
T11 的 SecretScrubber 上线后这笔欠账还掉了：值可以进，脱敏由写入路径负责。

超过 `MAX_ARGUMENT_CHARS` 的参数（例如整份文件内容）只留键名并标记
`arguments_truncated`。正文应当走 Artifact 存储，不该塞进事件表——
事件表会被每个订阅者按 sequence 全量扫描。

映射不认识的事件类型不会被静默丢掉：它会变成 `unknown` 类型且可见性为 internal，
原文保留在载荷里，既不丢失也不外泄。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from huicode.agent_events import AgentEvent
from huicode.server.events.types import RuntimeEvent, RuntimeEventType

# ``done`` 事件的 stop_reason 由 huicode/agent.py 产出：final / cancelled / error /
# max_iterations / unknown_tool_limit。未列出的取值一律按失败处理——
# 把不认识的停止原因报成"成功完成"是最糟的默认值。
_TERMINAL_BY_STOP_REASON: dict[str, RuntimeEventType] = {
    "final": "run_completed",
    "cancelled": "run_cancelled",
    "error": "run_failed",
    "max_iterations": "run_failed",
    "unknown_tool_limit": "run_failed",
}

_ERROR_CODE_BY_STOP_REASON: dict[str, str] = {
    "error": "agent_error",
    "max_iterations": "max_iterations_exceeded",
    "unknown_tool_limit": "unknown_tool_limit",
    "cancelled": "cancelled",
}

MAX_TEXT_DELTA_CHARS = 8192
MAX_SUMMARY_CHARS = 2048
MAX_ERROR_CHARS = 1024
MAX_ARGUMENT_CHARS = 4096


def _bounded(value: Any, limit: int) -> str:
    """截断到上限。事件载荷不能因为一次工具输出就无限增长。"""
    if not isinstance(value, str):
        return ""
    return value if len(value) <= limit else value[:limit]


def _tool_call_payload(event: AgentEvent) -> dict[str, Any]:
    call = event.tool_call
    if call is None:
        return {}
    arguments = getattr(call, "arguments", None)
    if not isinstance(arguments, dict):
        arguments = {}

    payload: dict[str, Any] = {"tool_call_id": call.id, "tool_name": call.name}
    try:
        serialized = json.dumps(arguments, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        serialized = ""
    if len(serialized) <= MAX_ARGUMENT_CHARS:
        payload["arguments"] = arguments
    else:
        # 太大：只留键名，正文走 Artifact。见模块顶部说明。
        payload["argument_keys"] = sorted(arguments)
        payload["arguments_truncated"] = True
    return payload


def map_agent_event(
    event: AgentEvent,
    *,
    session_id: UUID,
    sequence: int,
    run_id: UUID | None = None,
    occurred_at: datetime | None = None,
) -> RuntimeEvent | None:
    """映射单条事件；返回 None 表示这条不值得成为运行时事件（例如空文本增量）。

    `sequence` 由调用方（T8 的事件存储）分配，映射本身不生成序号——
    序号必须在单个会话内单调且唯一，那是持久化层的职责。
    """
    kind = event.kind
    payload: dict[str, Any]
    event_type: RuntimeEventType
    visibility: str | None = None

    if kind == "text":
        delta = _bounded(event.text, MAX_TEXT_DELTA_CHARS)
        if not delta:
            return None
        event_type, payload = "assistant_text_delta", {"delta": delta}

    elif kind == "thinking":
        delta = _bounded(event.text, MAX_TEXT_DELTA_CHARS)
        if not delta:
            return None
        event_type, payload = "thinking_delta", {"delta": delta}

    elif kind == "tool_call":
        event_type, payload = "tool_call_started", _tool_call_payload(event)

    elif kind == "tool_result":
        result = event.tool_result
        payload = _tool_call_payload(event)
        payload["ok"] = bool(result.ok) if result is not None else False
        payload["summary"] = _bounded(getattr(result, "summary", ""), MAX_SUMMARY_CHARS)
        if result is not None and result.error is not None:
            payload["error_code"] = result.error.code
        event_type = "tool_call_finished"

    elif kind == "progress":
        event_type, payload = "tool_call_progress", {"message": _bounded(event.text, MAX_SUMMARY_CHARS)}

    elif kind == "usage":
        event_type, payload = "usage_updated", {"usage": dict(event.data.get("usage", {}))}

    elif kind == "context":
        event_type, payload = "context_compacted", dict(event.data)

    elif kind == "memory":
        event_type, payload = "memory_updated", {"message": _bounded(event.data.get("message", ""), MAX_SUMMARY_CHARS)}

    elif kind == "error":
        event_type = "error"
        payload = {
            "message": _bounded(event.data.get("message", event.text), MAX_ERROR_CHARS),
        }

    elif kind == "done":
        stop_reason = event.stop_reason or "error"
        event_type = _TERMINAL_BY_STOP_REASON.get(stop_reason, "run_failed")
        payload = {"stop_reason": stop_reason}
        if event_type == "run_failed":
            payload["error_code"] = _ERROR_CODE_BY_STOP_REASON.get(stop_reason, "unknown_stop_reason")

    else:
        # 不认识的 kind：保留原文但不外泄，也不静默丢弃。
        event_type = "unknown"
        visibility = "internal"
        payload = {
            "original_kind": kind,
            "data": dict(event.data) if isinstance(event.data, dict) else {},
        }

    if event.iteration is not None:
        payload.setdefault("iteration", event.iteration)

    return RuntimeEvent(
        type=event_type,
        session_id=session_id,
        run_id=run_id,
        sequence=sequence,
        payload=payload,
        **({"visibility": visibility} if visibility is not None else {}),
        **({"occurred_at": occurred_at} if occurred_at is not None else {}),
    )
