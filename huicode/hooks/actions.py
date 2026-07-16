from __future__ import annotations

import codecs
import json
import locale
import os
import shlex
import socket
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping

from huicode.permissions.blacklist import check_dangerous_command
from huicode.permissions.sandbox import resolve_workspace_path

from .matching import read_field
from .types import (
    CommandAction,
    HookActionResult,
    HookPromptBlock,
    HookRule,
    HttpAction,
    PromptAction,
    SubagentAction,
)


PromptInjector = Callable[[HookPromptBlock], None]
SubagentSubmitter = Callable[[str, str], str]


class HookActionExecutor:
    def __init__(
        self,
        workspace: Path,
        subagent_submitter: SubagentSubmitter | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.subagent_submitter = subagent_submitter

    def set_subagent_submitter(self, submitter: SubagentSubmitter | None) -> None:
        self.subagent_submitter = submitter

    def execute(
        self,
        rule: HookRule,
        payload: dict[str, Any],
        inject_prompt: PromptInjector | None = None,
    ) -> HookActionResult:
        action = rule.action
        if isinstance(action, CommandAction):
            return self._run_command(action, rule, payload)
        if isinstance(action, HttpAction):
            return self._run_http(action, rule, payload)
        if isinstance(action, PromptAction):
            if inject_prompt is None:
                return HookActionResult("failed", "Prompt 注入器不可用")
            content = render_template(action.content, payload)
            inject_prompt(HookPromptBlock(rule.id, action.scope, content, rule.event))
            return HookActionResult("success", "提示词已注入", data={"scope": action.scope})
        if isinstance(action, SubagentAction):
            agent_scope = str(payload.get("agent_scope", "main"))
            if agent_scope.startswith("subagent:"):
                return HookActionResult("skipped", "recursion_guard")
            if self.subagent_submitter is None:
                return HookActionResult("skipped", "SubAgent 提交器不可用")
            task = render_template(action.task, payload)
            role = render_template(action.role, payload).strip() or "general"
            try:
                task_id = self.subagent_submitter(role, task)
            except Exception as exc:  # noqa: BLE001 - Hook 必须失败开放
                return HookActionResult("failed", f"SubAgent 提交失败: {exc}")
            return HookActionResult(
                "success",
                f"SubAgent 已提交: {task_id}",
                data={"task_id": task_id, "role": role},
            )
        return HookActionResult("failed", "未知 Hook 动作")

    def _run_command(self, action: CommandAction, rule: HookRule, payload: dict[str, Any]) -> HookActionResult:
        command_text = _join_command(action.command, action.args)
        dangerous = check_dangerous_command(command_text)
        if dangerous is not None:
            return HookActionResult("failed", dangerous.reason)
        try:
            event_workspace = Path(str(payload.get("workspace") or self.workspace)).resolve()
            cwd = resolve_workspace_path(event_workspace, action.cwd or ".")
        except (OSError, ValueError) as exc:
            return HookActionResult("failed", str(exc))
        environment = os.environ.copy()
        environment.update(action.env)
        input_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            completed = subprocess.run(
                command_text,
                cwd=cwd,
                shell=True,
                input=input_bytes,
                capture_output=True,
                timeout=rule.timeout_seconds,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            return HookActionResult(
                "timeout",
                f"命令执行超过 {rule.timeout_seconds} 秒",
                data={"stdout": _preview(exc.stdout), "stderr": _preview(exc.stderr)},
            )
        except OSError as exc:
            return HookActionResult("failed", f"命令启动失败: {exc}")
        stdout = _preview(completed.stdout)
        stderr = _preview(completed.stderr)
        data = {"returncode": completed.returncode, "stdout": stdout, "stderr": stderr}
        if completed.returncode == 0:
            return HookActionResult("success", "命令执行成功", data=data)
        if completed.returncode == 2 and rule.event == "tool_before":
            reason = (stderr or stdout or f"Hook {rule.id} 拒绝工具调用").strip()
            return HookActionResult("denied", "命令明确拒绝", deny_reason=reason, data=data)
        return HookActionResult("failed", f"命令退出码为 {completed.returncode}", data=data)

    def _run_http(self, action: HttpAction, rule: HookRule, payload: dict[str, Any]) -> HookActionResult:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8", **action.headers}
        request = urllib.request.Request(action.url, data=body, headers=headers, method=action.method)
        try:
            with urllib.request.urlopen(request, timeout=rule.timeout_seconds) as response:
                status = int(response.status)
                response_body = response.read(64 * 1024)
        except (TimeoutError, socket.timeout) as exc:
            return HookActionResult("timeout", f"HTTP 请求超过 {rule.timeout_seconds} 秒: {exc}")
        except urllib.error.HTTPError as exc:
            return HookActionResult("failed", f"HTTP 状态码 {exc.code}")
        except (urllib.error.URLError, OSError) as exc:
            return HookActionResult("failed", f"HTTP 请求失败: {exc}")
        if not action.expected_status[0] <= status <= action.expected_status[1]:
            return HookActionResult("failed", f"HTTP 状态码 {status} 不在期望范围")
        parsed: Any = None
        if response_body.strip():
            try:
                parsed = json.loads(response_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                return HookActionResult("failed", f"HTTP 响应不是有效 JSON: {exc}")
        preview = _preview(response_body)
        if rule.event == "tool_before" and isinstance(parsed, dict) and parsed.get("decision") == "deny":
            reason = str(parsed.get("reason", "")).strip()
            if not reason:
                return HookActionResult("failed", "HTTP deny 响应缺少 reason", data={"status": status})
            return HookActionResult("denied", "HTTP 明确拒绝", deny_reason=reason, data={"status": status})
        return HookActionResult("success", "HTTP 请求成功", data={"status": status, "response": preview})


def render_template(template: str, payload: Mapping[str, Any]) -> str:
    import re

    pattern = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")

    def replace(match: re.Match[str]) -> str:
        value = read_field(payload, match.group(1))
        if type(value) is object:
            return ""
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, ensure_ascii=False)
        return "" if value is None else str(value)

    return pattern.sub(replace, template)


def _join_command(command: str, args: tuple[str, ...]) -> str:
    if not args:
        return command
    if os.name == "nt":
        return subprocess.list2cmdline([command, *args])
    return shlex.join([command, *args])


def _preview(value: str | bytes | None, limit: int = 4096) -> str:
    text = _decode(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if value.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return value.decode("utf-16", errors="replace")
    for encoding in ("utf-8-sig", locale.getpreferredencoding(False), "gb18030"):
        try:
            return value.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return value.decode("utf-8", errors="replace")
