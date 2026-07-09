from __future__ import annotations

import json
from dataclasses import replace

from huicode.config import ContextConfig
from huicode.context.estimator import TokenEstimator
from huicode.context.store import ToolResultStore
from huicode.context.types import ContextCompressionReport, SpillRecord
from huicode.providers.base import ConversationMessage, ToolCall
from huicode.tools.base import ToolResult


def compact_single_tool_result(
    call: ToolCall,
    result: ToolResult,
    store: ToolResultStore,
    config: ContextConfig,
    estimator: TokenEstimator,
    iteration: int,
    reason: str = "single_tool_result",
) -> tuple[ToolResult, SpillRecord | None]:
    if _already_spilled(result):
        return result, None
    serialized = json.dumps(result.to_model_dict(), ensure_ascii=False)
    if estimator.estimate_text(serialized) <= config.single_tool_result_tokens:
        return result, None
    spill = store.spill(call, result, iteration, reason)
    return _compact_result(result, spill, config.preview_chars), spill


def compact_tool_groups(
    messages: list[ConversationMessage],
    store: ToolResultStore,
    config: ContextConfig,
    estimator: TokenEstimator,
    iteration: int = 0,
) -> tuple[list[ConversationMessage], ContextCompressionReport | None]:
    updated = list(messages)
    spilled: list[SpillRecord] = []
    index = 0
    while index < len(updated):
        message = updated[index]
        if not (message.role == "assistant" and message.tool_calls):
            index += 1
            continue
        group_indexes: list[int] = []
        cursor = index + 1
        group_total = 0
        candidates: list[tuple[int, int, ToolCall, ConversationMessage]] = []
        while cursor < len(updated) and updated[cursor].role == "tool":
            tool_message = updated[cursor]
            group_indexes.append(cursor)
            estimate = estimator.estimate_message(tool_message).tokens
            group_total += estimate
            if tool_message.tool_result is not None and not _already_spilled(tool_message.tool_result):
                call = _call_for_tool_message(message.tool_calls, tool_message.tool_call_id, tool_message.tool_name)
                if call is not None:
                    candidates.append((estimate, cursor, call, tool_message))
            cursor += 1
        if group_total > config.tool_result_group_tokens and candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            remaining = group_total
            for estimate, tool_index, call, tool_message in candidates:
                if remaining <= config.tool_result_group_tokens:
                    break
                compacted, spill = compact_single_tool_result(
                    call,
                    tool_message.tool_result,
                    store,
                    config,
                    estimator,
                    iteration,
                    reason="tool_result_group",
                )
                if spill is None:
                    continue
                updated[tool_index] = replace(tool_message, content=compacted.summary, tool_result=compacted)
                spilled.append(spill)
                remaining -= estimate
        index = cursor
    if not spilled:
        return updated, None
    total_freed = sum(record.tokens_freed for record in spilled)
    return updated, ContextCompressionReport(
        kind="lightweight",
        spilled_count=len(spilled),
        tokens_freed=total_freed,
        message=f"spilled {len(spilled)} tool result(s) to disk",
        paths=tuple(record.path for record in spilled),
    )


def _compact_result(result: ToolResult, spill: SpillRecord, preview_chars: int) -> ToolResult:
    compact_data = _compact_tool_data(result.data)
    preview = spill.preview[:preview_chars]
    compact_data["preview"] = preview
    compact_data["__spilled__"] = {
        "path": spill.path,
        "chars_freed": max(0, spill.original_chars - spill.compact_chars),
        "tokens_freed": spill.tokens_freed,
        "reason": spill.reason,
    }
    compact_data["summary"] = result.summary
    return ToolResult(ok=result.ok, data=compact_data, error=result.error, summary=result.summary)


def _compact_tool_data(data: dict[str, object] | None) -> dict[str, object]:
    if not data:
        return {}
    keep = {
        "path",
        "command",
        "returncode",
        "timed_out",
        "lines",
        "chars",
        "bytes",
        "count",
        "matches",
        "pattern",
        "server",
        "tool",
    }
    compact = {key: value for key, value in data.items() if key in keep}
    if isinstance(compact.get("matches"), list):
        matches = compact["matches"]
        compact["matches"] = matches[:80]
        if len(matches) > 80:
            compact["matches_omitted_count"] = len(matches) - 80
    omitted = sorted(key for key in data if key not in keep)
    if omitted:
        compact["omitted_fields"] = omitted
    return compact


def _already_spilled(result: ToolResult) -> bool:
    if not result.data:
        return False
    spill = result.data.get("__spilled__")
    return isinstance(spill, dict) and bool(spill.get("path"))


def _call_for_tool_message(
    tool_calls: list[ToolCall],
    tool_call_id: str | None,
    tool_name: str | None,
) -> ToolCall | None:
    for call in tool_calls:
        if tool_call_id and call.id == tool_call_id:
            return call
    for call in tool_calls:
        if tool_name and call.name == tool_name:
            return call
    return tool_calls[0] if tool_calls else None
