from __future__ import annotations

import dataclasses
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from huicode.permissions.rules import canonical_tool_name, target_value_for_call

from .types import HookEvent, HookEventName


_SENSITIVE_PARTS = ("api_key", "apikey", "authorization", "cookie", "password", "secret", "token")
_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(api[_-]?key|authorization|cookie|password|secret|token)\s*[:=]\s*[^\s,;]+"),
)


def make_event(
    name: HookEventName,
    *,
    session_id: str,
    workspace: Path,
    mode: str = "chat",
    turn_id: str | None = None,
    iteration: int = 0,
    agent_scope: str = "main",
    data: dict[str, Any] | None = None,
) -> HookEvent:
    return HookEvent(
        name=name,
        occurred_at=datetime.now().astimezone().isoformat(timespec="milliseconds"),
        session_id=session_id,
        workspace=workspace,
        mode=mode,
        turn_id=turn_id,
        iteration=iteration,
        agent_scope=agent_scope,
        data=sanitize_payload(data or {}),
    )


def message_data(message, *, is_final: bool) -> dict[str, Any]:  # noqa: ANN001
    calls = [
        {"id": call.id, "name": call.name}
        for call in getattr(message, "tool_calls", []) or []
    ]
    return {
        "message": {
            "role": getattr(message, "role", "unknown"),
            "content_preview": _limit_string(str(getattr(message, "content", ""))),
            "has_thinking": bool(getattr(message, "thinking", "")),
            "tool_calls": calls,
            "is_final": is_final,
        }
    }


def tool_data(call, result=None, *, source: str = "tool") -> dict[str, Any]:  # noqa: ANN001
    canonical_name = canonical_tool_name(call.name)
    data: dict[str, Any] = {
        "tool": {
            "call_id": call.id,
            "name": canonical_name,
            "original_name": call.name,
            "canonical_name": canonical_name,
            "arguments": sanitize_payload(call.arguments),
            "target": _limit_string(target_value_for_call(call)),
        }
    }
    if result is not None:
        error = getattr(result, "error", None)
        data["result"] = {
            "ok": bool(getattr(result, "ok", False)),
            "error_code": getattr(error, "code", "") if error is not None else "",
            "summary": _limit_string(str(getattr(result, "summary", ""))),
            "source": source,
        }
    return data


def context_data(report=None, **extra: Any) -> dict[str, Any]:  # noqa: ANN001
    values: dict[str, Any] = dict(extra)
    if report is not None:
        if dataclasses.is_dataclass(report):
            values.update(dataclasses.asdict(report))
        elif isinstance(report, Mapping):
            values.update(report)
        else:
            values["message"] = str(report)
    return {"context": sanitize_payload(values)}


def error_data(error: BaseException | str, *, category: str = "agent") -> dict[str, Any]:
    return {
        "error": {
            "category": category,
            "type": type(error).__name__ if isinstance(error, BaseException) else "error",
            "summary": _limit_string(str(error)),
        }
    }


def event_payload(event: HookEvent) -> dict[str, Any]:
    return sanitize_payload(event.to_payload())


def sanitize_payload(value: Any, *, max_string: int = 4096, max_items: int = 50, depth: int = 0) -> Any:
    if depth >= 8:
        return "[MAX_DEPTH]"
    if dataclasses.is_dataclass(value):
        return sanitize_payload(dataclasses.asdict(value), max_string=max_string, max_items=max_items, depth=depth + 1)
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= max_items:
                result["__truncated_items__"] = len(value) - max_items
                break
            key = str(raw_key)
            if _sensitive_key(key):
                result[key] = "[REDACTED]"
            else:
                result[key] = sanitize_payload(item, max_string=max_string, max_items=max_items, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        result = [
            sanitize_payload(item, max_string=max_string, max_items=max_items, depth=depth + 1)
            for item in items[:max_items]
        ]
        if len(items) > max_items:
            result.append(f"[TRUNCATED {len(items) - max_items} ITEMS]")
        return result
    if isinstance(value, bytes):
        return _limit_string(value.decode("utf-8", errors="replace"), max_string)
    if isinstance(value, str):
        return _limit_string(_redact_text(value), max_string)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _limit_string(str(value), max_string)


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_PARTS)


def _limit_string(value: str, limit: int = 4096) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)} [REDACTED]", redacted)
    return redacted
