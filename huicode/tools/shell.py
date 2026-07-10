from __future__ import annotations

import codecs
import locale
import os
import re
import subprocess
from typing import Any

from .base import ToolContext, ToolResult


class RunCommandTool:
    name = "Bash"
    description = (
        "在当前工作目录内执行一条命令，返回退出码、标准输出和标准错误。"
        "当前环境是 Windows 时，优先使用 dir、tree、where、findstr 等命令。"
    )
    side_effect = True
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令文本"},
            "timeout_seconds": {"type": "integer", "description": "可选超时时间，不能超过上下文限制"},
        },
        "required": ["command"],
    }

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        command = args.get("command")
        if not isinstance(command, str) or not command:
            return ToolResult.failure("invalid_request", "参数 command 必须是非空字符串")
        command = _normalize_command(command)
        timeout = args.get("timeout_seconds", context.timeout_seconds)
        try:
            timeout = min(max(1, int(timeout)), context.timeout_seconds)
        except (TypeError, ValueError):
            return ToolResult.failure("invalid_request", "参数 timeout_seconds 必须是整数")

        command, line_limit = _prepare_command(command)
        try:
            completed = subprocess.run(
                command,
                cwd=context.workspace,
                shell=True,
                capture_output=True,
                timeout=timeout,
            )
            stdout = _limit_lines(_decode_output(completed.stdout), line_limit)
            stdout = _truncate(stdout, context.max_output_chars)
            stderr = _truncate(_decode_output(completed.stderr), context.max_output_chars)
            ok = completed.returncode == 0
            data = {
                "command": command,
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": False,
            }
            summary = f"exit {completed.returncode}, stdout {len(stdout)} chars, stderr {len(stderr)} chars"
            if ok:
                return ToolResult.success(data, summary)
            return ToolResult.failure("nonzero_exit", f"命令退出码为 {completed.returncode}", data, summary)
        except subprocess.TimeoutExpired as exc:
            stdout = _truncate(_decode_output(exc.stdout), context.max_output_chars)
            stderr = _truncate(_decode_output(exc.stderr), context.max_output_chars)
            return ToolResult.failure(
                "timeout",
                f"命令执行超过 {timeout} 秒",
                {
                    "command": command,
                    "returncode": None,
                    "stdout": stdout,
                    "stderr": stderr,
                    "timed_out": True,
                },
                f"timeout after {timeout}s",
            )
        except OSError as exc:
            return ToolResult.failure("exec_error", f"执行命令失败: {exc}", {"command": command})


def _decode_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if value.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return value.decode("utf-16", errors="replace")
    encodings = ("utf-8-sig", locale.getpreferredencoding(False), "gb18030")
    tried: set[str] = set()
    for encoding in encodings:
        normalized = encoding.lower()
        if normalized in tried:
            continue
        tried.add(normalized)
        try:
            return value.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return value.decode("utf-8", errors="replace")


def _truncate(value: str | bytes | None, limit: int) -> str:
    value = _decode_output(value)
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def _limit_lines(value: str | bytes | None, limit: int | None) -> str:
    text = _decode_output(value)
    if limit is None:
        return text
    return "\n".join(text.splitlines()[:limit])


def _prepare_command(command: str) -> tuple[str, int | None]:
    command, line_limit = _strip_trailing_head(command)
    return _normalize_command(command), line_limit


def _strip_trailing_head(command: str) -> tuple[str, int | None]:
    match = re.search(r"(?is)\|\s*head(?:\.exe)?\s+(?:-n\s*)?-?(\d+)\s*$", command.strip())
    if not match:
        return command, None
    return command[: match.start()].strip(), int(match.group(1))


def _normalize_command(command: str) -> str:
    if os.name != "nt":
        return command
    stripped = command.strip()
    aliases = {
        "ls": "dir",
        "ls -l": "dir",
        "ls -la": "dir /a",
        "ls -al": "dir /a",
    }
    normalized = aliases.get(stripped, command)
    if _looks_like_powershell_command(normalized):
        escaped = normalized.replace('"', '`"')
        return f'powershell -NoProfile -Command "{escaped}"'
    return normalized


def _looks_like_powershell_command(command: str) -> bool:
    lowered = command.strip().lower()
    if lowered.startswith(("powershell ", "powershell.exe ", "pwsh ", "pwsh.exe ")):
        return False
    return lowered.startswith(
        (
            "get-childitem",
            "gci ",
            "get-content",
            "select-string",
            "test-path",
            "get-location",
        )
    )
