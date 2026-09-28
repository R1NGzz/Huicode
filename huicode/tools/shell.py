from __future__ import annotations

import codecs
import locale
import os
import re
import uuid
from typing import Any

from .base import (
    EXTERNAL_SIDE_EFFECT,
    FILE_WRITE,
    NETWORK,
    READ,
    SHELL,
    ToolContext,
    ToolResult,
)
from .execution import (
    SHELL_ENV_REJECTED,
    SHELL_OUTPUT_EXCEEDED,
    SHELL_SPAWN_FAILED,
    CommandRequest,
    CommandRunner,
)

#: 执行层的字节上限至少给这么多，否则一个把 max_output_chars 设得很小的上下文
#: 会因为输出护栏太紧而频繁杀进程。
_MIN_OUTPUT_BYTES = 64 * 1024

#: 后端错误码 → 工具错误码。工具错误码是**模型看到的词汇表**，与 CLI 既有行为
#: 保持一致；后端错误码是运行时与事件流用的。刻意不合并：合并之后，改一个给运维
#: 看的码就会改变模型看到的东西。
_ERROR_CODE_MAP = {
    SHELL_ENV_REJECTED: "invalid_request",
    SHELL_OUTPUT_EXCEEDED: "output_limit_exceeded",
    SHELL_SPAWN_FAILED: "exec_error",
}

#: 进程级执行器。**共用一个是刻意的**：它持有"正在跑的进程"表，共用意味着按
#: execution_id 取消能覆盖到工具发起的命令（服务端也用它）。用完即从表里移除，
#: 不会随会话增长。
_RUNNER = CommandRunner()


class RunCommandTool:
    name = "Bash"
    description = (
        "在当前工作目录内执行一条命令，返回退出码、标准输出和标准错误。"
        "当前环境是 Windows 时，优先使用 dir、tree、where、findstr 等命令。"
    )
    side_effect = True
    # 声明成"什么都能干"是**准确**的，不是保守：一条任意命令既可以读、可以写文件、
    # 可以出网、也可以调用外部副作用。少声明会让信任声明的策略低估它。
    # 只读命令的低风险处理在 permissions/engine.py 里按**命令内容**判断，不靠这里。
    capabilities = frozenset({READ, FILE_WRITE, SHELL, NETWORK, EXTERNAL_SIDE_EFFECT})
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

        # 真正执行的是受控的本地后端（T12）：工作目录经 WorkspacePathResolver、
        # 环境变量按白名单过滤、超时后终止**整棵进程树**。这里只负责把结果翻译回
        # 模型认识的形状——工具的错误码是给模型看的词汇表，后端的错误码是给运行时
        # 与事件流看的，两者刻意不混用（见 execution_backend.py 的模块文档）。
        result = _RUNNER.run(
            CommandRequest(
                execution_id=uuid.uuid4().hex,
                command=command,
                cwd=context.workspace,
                timeout_seconds=timeout,
                # 执行层的字节上限是**内存护栏**（输出到上限就杀进程）；呈现层的字符
                # 截断在下面，那才是可读性。两个都要有，作用不同。
                max_output_bytes=max(context.max_output_chars * 4, _MIN_OUTPUT_BYTES),
            )
        )
        stdout = _limit_lines(result.stdout, line_limit)
        stdout = _truncate(stdout, context.max_output_chars)
        stderr = _truncate(result.stderr, context.max_output_chars)

        if result.timed_out:
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
        if result.error_code is not None:
            return ToolResult.failure(
                _ERROR_CODE_MAP.get(result.error_code, "exec_error"),
                stderr or "命令未能执行",
                {"command": command, "error_code": result.error_code, "timed_out": False},
                f"{result.error_code}: {stderr}"[:240],
            )

        ok = result.returncode == 0
        data = {
            "command": command,
            "returncode": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": False,
        }
        summary = f"exit {result.returncode}, stdout {len(stdout)} chars, stderr {len(stderr)} chars"
        if ok:
            return ToolResult.success(data, summary)
        return ToolResult.failure("nonzero_exit", f"命令退出码为 {result.returncode}", data, summary)


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
