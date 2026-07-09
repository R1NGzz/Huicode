from __future__ import annotations

import re
import time
from typing import Any, TextIO

from huicode.agent_events import AgentEvent
from huicode.permissions.base import PermissionRequest
from huicode.providers.base import ToolCall
from huicode.tools.base import ToolResult

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.text import Text
except ImportError:  # pragma: no cover - 运行环境没有 rich 时保留纯文本输出
    Console = None
    Markdown = None
    Text = None


def format_tool_call_line(call: ToolCall) -> str:
    return f"● {call.name}({_summarize_args(call.arguments)})"


def format_tool_result_line(
    result: ToolResult,
    elapsed_seconds: float | None = None,
    call: ToolCall | None = None,
) -> str:
    status = "✓" if result.ok else "✗"
    summary = _clip(result.summary or (result.error.message if result.error else ""), 120)
    if call is not None:
        summary = f"{call.name}({_summarize_args(call.arguments)})"
        if not result.ok:
            summary += f" - {result.error.message if result.error else result.summary}"
    if elapsed_seconds is not None:
        summary = f"{summary} ({_format_elapsed(elapsed_seconds)})"
    return f"  {status} {summary}"


def format_permission_request(request: PermissionRequest) -> str:
    return "\n".join(
        [
            "HuiCode> 权限确认",
            f"  tool: {request.call.name}({_summarize_args(request.call.arguments)})",
            f"  target: {_clip(request.target, 120) if request.target else '-'}",
            f"  risk: {request.risk}",
            f"  reason: {request.reason}",
            "  choose: [d]eny / [o]nce / [s]ession / [a]lways, enter=deny",
        ]
    )


def _summarize_args(args: dict[str, object]) -> str:
    for key in ("path", "command", "pattern", "glob"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return _clip(value, 80)
    if not args:
        return ""
    parts = [f"{key}={value}" for key, value in list(args.items())[:2]]
    return _clip(", ".join(parts), 80)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


_RENDER_STATES: dict[int, dict[str, Any]] = {}


def render_agent_event(event: AgentEvent, output: TextIO) -> None:
    state = _RENDER_STATES.setdefault(
        id(output),
        {
            "line_open": False,
            "thinking_open": False,
            "thinking_active": False,
            "answer_started": False,
            "code_stream_open": False,
            "tools_header_printed": False,
            "tool_start_times": {},
            "turn_started_at": None,
            "markdown_buffer": "",
            "console": None,
        },
    )

    if event.kind == "progress" and event.data.get("stage") == "assistant_turn_start":
        _flush_markdown_buffer(output, state)
        _close_inline_state(output, state)
        mode = event.data.get("mode", "chat")
        permission_mode = event.data.get("permission_mode", "disabled")
        print(f"HuiCode> 思考中... mode={mode} permission={permission_mode}", flush=True, file=output)
        state["turn_started_at"] = time.perf_counter()
        state["thinking_active"] = True
        state["answer_started"] = False
        state["code_stream_open"] = False
        state["tools_header_printed"] = False
        state["tool_start_times"] = {}
        state["thinking_open"] = False
        return

    if event.kind == "text":
        _finish_thinking_status(output, state)
        if state["thinking_open"]:
            print("\nHuiCode> ", end="", flush=True, file=output)
            state["thinking_open"] = False
            state["line_open"] = True
        _start_answer(output, state)
        _print_streaming_text(output, state, event.text)
        return

    if event.kind == "thinking":
        if not event.text:
            return
        _flush_markdown_buffer(output, state)
        if state["line_open"]:
            print("\n[thinking] ", end="", flush=True, file=output)
            state["line_open"] = False
            state["thinking_open"] = True
        elif not state["thinking_open"]:
            print("[thinking] ", end="", flush=True, file=output)
            state["thinking_open"] = True
        print(event.text, end="", flush=True, file=output)
        return

    if event.kind == "tool_call" and event.tool_call is not None:
        _flush_markdown_buffer(output, state)
        _close_inline_state(output, state)
        _finish_thinking_status(output, state)
        _start_tool_group(output, state)
        state["tool_start_times"][event.tool_call.id] = time.perf_counter()
        return

    if event.kind == "tool_result" and event.tool_result is not None:
        _flush_markdown_buffer(output, state)
        elapsed = _tool_elapsed(state, event.tool_call.id if event.tool_call else "")
        print(format_tool_result_line(event.tool_result, elapsed, event.tool_call), file=output)
        return

    if event.kind == "usage":
        usage = event.data.get("usage", {})
        if usage:
            _flush_markdown_buffer(output, state)
            _close_inline_state(output, state)
            print(f"  tokens: {_summarize_usage(usage)}", file=output)
        return

    if event.kind == "context":
        _flush_markdown_buffer(output, state)
        _close_inline_state(output, state)
        _render_context_event(output, event.data)
        return

    if event.kind == "memory":
        _flush_markdown_buffer(output, state)
        _close_inline_state(output, state)
        message = event.data.get("message", event.text)
        if message:
            print(f"HuiCode> {message}", file=output)
        return

    if event.kind == "error":
        _flush_markdown_buffer(output, state)
        _close_inline_state(output, state)
        print(event.data.get("message", event.text), file=output)
        return

    if event.kind == "done":
        _flush_markdown_buffer(output, state)
        state["code_stream_open"] = False
        state["thinking_active"] = False
        _close_inline_state(output, state)
        message = event.data.get("message", "")
        if message and event.stop_reason not in {"final", "error"}:
            print(message, file=output)


def _close_inline_state(output: TextIO, state: dict[str, Any]) -> None:
    if state["line_open"] or state["thinking_open"]:
        print(file=output)
    state["line_open"] = False
    state["thinking_open"] = False


def _finish_thinking_status(output: TextIO, state: dict[str, Any]) -> None:
    if not state.get("thinking_active"):
        return
    if state["line_open"] or state["thinking_open"]:
        print(file=output)
    started_at = state.get("turn_started_at")
    elapsed = time.perf_counter() - started_at if isinstance(started_at, float) else 0.0
    print(f"HuiCode> 思考完成 ({_format_elapsed(elapsed)})", flush=True, file=output)
    state["line_open"] = False
    state["thinking_open"] = False
    state["thinking_active"] = False


def _start_tool_group(output: TextIO, state: dict[str, Any]) -> None:
    if state.get("tools_header_printed"):
        return
    print("HuiCode> 调用工具...", file=output)
    state["tools_header_printed"] = True


def _tool_elapsed(state: dict[str, Any], tool_call_id: str) -> float | None:
    started_at = state.get("tool_start_times", {}).pop(tool_call_id, None)
    if not isinstance(started_at, float):
        return None
    return time.perf_counter() - started_at


def _format_elapsed(seconds: float) -> str:
    return f"{max(0.0, seconds):.2f}s"


def _summarize_usage(usage: dict[object, object]) -> str:
    preferred = [
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ]
    parts: list[str] = []
    seen: set[object] = set()
    for key in preferred:
        if key in usage and _is_scalar_usage_value(usage[key]):
            parts.append(f"{key}={usage[key]}")
            seen.add(key)

    cache = usage.get("cache")
    if isinstance(cache, dict):
        cache_keys = [
            ("creation_input_tokens", "cache_creation_input_tokens"),
            ("read_input_tokens", "cache_read_input_tokens"),
            ("cached_tokens", "cached_tokens"),
        ]
        for source_key, output_key in cache_keys:
            if output_key in seen:
                continue
            value = cache.get(source_key)
            if _is_scalar_usage_value(value):
                parts.append(f"{output_key}={value}")
                seen.add(output_key)

    for key, value in usage.items():
        if key in seen or key == "cache" or not _is_scalar_usage_value(value):
            continue
        parts.append(f"{key}={value}")
    return _clip(", ".join(parts), 120)


def _is_scalar_usage_value(value: object) -> bool:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def _rich_enabled() -> bool:
    return Console is not None and Markdown is not None


def _flush_complete_markdown_blocks(output: TextIO, state: dict[str, Any]) -> None:
    buffer = state["markdown_buffer"]
    split_at = _find_complete_markdown_split(buffer)
    if split_at <= 0:
        return
    text = buffer[:split_at]
    state["markdown_buffer"] = buffer[split_at:]
    _render_markdown_text(output, state, text)


def _flush_markdown_buffer(output: TextIO, state: dict[str, Any]) -> None:
    text = state.get("markdown_buffer", "")
    if not text:
        return
    state["markdown_buffer"] = ""
    _render_markdown_text(output, state, text)


def _render_markdown_text(output: TextIO, state: dict[str, Any], text: str) -> None:
    if not text:
        return
    if not _rich_enabled() or not _looks_like_markdown(text):
        print(text, end="", flush=True, file=output)
        return
    if state["line_open"] or state["thinking_open"]:
        print(file=output)
        state["line_open"] = False
        state["thinking_open"] = False
    console = _get_console(output, state)
    console.print(Markdown(text.rstrip()))


def _get_console(output: TextIO, state: dict[str, Any]):
    if state["console"] is None:
        state["console"] = Console(file=output, force_terminal=False, color_system=None, width=100)
    return state["console"]


def _find_complete_markdown_split(text: str) -> int:
    index = text.rfind("\n\n")
    if index < 0:
        return -1
    split_at = index + 2
    candidate = text[:split_at]
    if _has_unclosed_code_fence(candidate):
        return -1
    return split_at


def _has_unclosed_code_fence(text: str) -> bool:
    fence_count = len(re.findall(r"(?m)^```", text))
    return fence_count % 2 == 1


def _looks_like_markdown(text: str) -> bool:
    return bool(
        re.search(r"(?m)^(#{1,6}\s|[-*+]\s|\d+\.\s|>\s|```| {0,3}\|.+\|)", text)
        or re.search(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))", text)
    )


def _should_buffer_for_markdown(text: str) -> bool:
    return _rich_enabled() and _looks_like_markdown(text)


def _start_answer(output: TextIO, state: dict[str, Any]) -> None:
    if state["answer_started"]:
        return
    print("HuiCode> 正在回答...", flush=True, file=output)
    print("HuiCode> ● ", end="", flush=True, file=output)
    state["line_open"] = True
    state["answer_started"] = True


def _print_streaming_text(output: TextIO, state: dict[str, Any], text: str) -> None:
    if not text:
        return
    if state["code_stream_open"]:
        _print_code_stream_text(output, state, text)
        return

    fence = _find_code_fence_open(text)
    if fence is not None:
        before = text[: fence.start()]
        if before:
            _render_preface_text(output, state, before)
        state["code_stream_open"] = True
        remainder = text[fence.end() :]
        if remainder:
            _print_code_stream_text(output, state, remainder)
        return

    if state["markdown_buffer"] or _should_buffer_for_markdown(text):
        state["markdown_buffer"] += text
        _flush_complete_markdown_blocks(output, state)
        return
    _print_inline_text(output, state, text)


def _print_code_stream_text(output: TextIO, state: dict[str, Any], text: str) -> None:
    fence = _find_code_fence_close(text)
    if fence is None:
        print(text, end="", flush=True, file=output)
        return

    before = text[: fence.start()]
    if before:
        print(before, end="", flush=True, file=output)
    state["code_stream_open"] = False
    remainder = text[fence.end() :]
    if remainder:
        _print_streaming_text(output, state, remainder)


def _render_preface_text(output: TextIO, state: dict[str, Any], text: str) -> None:
    if _rich_enabled() and _looks_like_markdown(text):
        _render_markdown_text(output, state, text)
        return
    _print_inline_text(output, state, text)


def _find_code_fence_open(text: str) -> re.Match[str] | None:
    return re.search(r"(?m)^```[^\r\n]*(?:\r?\n)?", text)


def _find_code_fence_close(text: str) -> re.Match[str] | None:
    return re.search(r"(?m)^```\s*(?:\r?\n)?", text)


def _print_inline_text(output: TextIO, state: dict[str, Any], text: str) -> None:
    if not text:
        return
    if not _rich_enabled() or Text is None or "`" not in text:
        print(text, end="", flush=True, file=output)
        return
    console = _get_console(output, state)
    console.print(_inline_code_text(text), end="")


def _inline_code_text(text: str):
    rendered = Text()
    last = 0
    for match in re.finditer(r"`([^`\n]+)`", text):
        rendered.append(text[last : match.start()])
        rendered.append(match.group(1), style="bold red on #2b2424")
        last = match.end()
    rendered.append(text[last:])
    return rendered


def _render_context_event(output: TextIO, data: dict[str, Any]) -> None:
    kind = str(data.get("kind", "skip"))
    if kind == "lightweight":
        print("HuiCode> 上下文整理...", file=output)
        detail = f"  ◦ spilled {data.get('spilled_count', 0)} tool result(s) to disk"
        if data.get("tokens_freed"):
            detail += f" (~{data.get('tokens_freed')} tokens freed)"
        paths = data.get("paths") or []
        if paths:
            detail += f": {', '.join(str(path) for path in paths[:2])}"
        print(detail, file=output)
        return
    if kind == "summary":
        print("HuiCode> 上下文整理...", file=output)
        print(
            f"  ◦ summary created (~{data.get('tokens_before', 0)} -> {data.get('tokens_after', 0)} tokens)",
            file=output,
        )
        return
    if kind == "failure":
        print(f"HuiCode> 上下文压缩失败: {data.get('message', '')}", file=output)
        return
    if kind == "fuse":
        print(f"HuiCode> {data.get('message', '上下文摘要已熔断')}", file=output)
        return
    if kind == "skip":
        print(f"HuiCode> 上下文压缩跳过: {data.get('message', '')}", file=output)
