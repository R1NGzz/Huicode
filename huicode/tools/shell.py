from __future__ import annotations

import os
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

        try:
            completed = subprocess.run(
                command,
                cwd=context.workspace,
                shell=True,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            stdout = _truncate(completed.stdout, context.max_output_chars)
            stderr = _truncate(completed.stderr, context.max_output_chars)
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
            stdout = _truncate(exc.stdout or "", context.max_output_chars)
            stderr = _truncate(exc.stderr or "", context.max_output_chars)
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


def _truncate(value: str | bytes, limit: int) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


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
    return aliases.get(stripped, command)
