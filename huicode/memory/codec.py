from __future__ import annotations

from typing import Any

from huicode.providers.base import ConversationMessage, ToolCall
from huicode.tools.base import ToolError, ToolResult


def tool_call_to_json(call: ToolCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "name": call.name,
        "arguments": call.arguments,
        "raw_arguments": call.raw_arguments,
    }


def tool_call_from_json(data: dict[str, Any]) -> ToolCall:
    return ToolCall(
        id=str(data.get("id") or ""),
        name=str(data.get("name") or ""),
        arguments=dict(data.get("arguments") or {}),
        raw_arguments=str(data.get("raw_arguments") or ""),
    )


def tool_result_to_json(result: ToolResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return result.to_model_dict()


def tool_result_from_json(data: dict[str, Any] | None) -> ToolResult | None:
    if data is None:
        return None
    error_data = data.get("error")
    error = None
    if isinstance(error_data, dict):
        error = ToolError(
            code=str(error_data.get("code") or ""),
            message=str(error_data.get("message") or ""),
            details=dict(error_data.get("details") or {}),
        )
    return ToolResult(
        ok=bool(data.get("ok")),
        data=data.get("data") if isinstance(data.get("data"), dict) else None,
        error=error,
        summary=str(data.get("summary") or ""),
    )


def message_to_json(message: ConversationMessage) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": message.content,
        "thinking": message.thinking,
        "thinking_signature": message.thinking_signature,
        "tool_calls": [tool_call_to_json(call) for call in message.tool_calls],
        "tool_call_id": message.tool_call_id,
        "tool_name": message.tool_name,
        "tool_result": tool_result_to_json(message.tool_result),
    }


def message_from_json(data: dict[str, Any]) -> ConversationMessage:
    role = data.get("role")
    if role not in {"user", "assistant", "tool"}:
        raise ValueError(f"非法消息角色: {role}")
    calls_raw = data.get("tool_calls") or []
    if not isinstance(calls_raw, list):
        raise ValueError("tool_calls 必须是列表")
    result_raw = data.get("tool_result")
    if result_raw is not None and not isinstance(result_raw, dict):
        raise ValueError("tool_result 必须是对象")
    return ConversationMessage(
        role=role,
        content=str(data.get("content") or ""),
        thinking=str(data.get("thinking") or ""),
        thinking_signature=str(data.get("thinking_signature") or ""),
        tool_calls=[tool_call_from_json(dict(call)) for call in calls_raw],
        tool_call_id=data.get("tool_call_id"),
        tool_name=data.get("tool_name"),
        tool_result=tool_result_from_json(result_raw),
    )
