from __future__ import annotations

from huicode.permissions.base import (
    PermissionConfirmation,
    PermissionContext,
    PermissionDecision,
    PermissionRequest,
    PermissionRule,
)
from huicode.permissions.blacklist import check_dangerous_command
from huicode.permissions.config import append_persistent_rule
from huicode.permissions.rules import match_rule, target_value_for_call
from huicode.permissions.sandbox import extract_tool_paths, is_within_workspace, resolve_workspace_path
from huicode.providers.base import ToolCall
from huicode.tools.base import ToolContext, ToolResult


def evaluate_permission(call: ToolCall, tool, context: ToolContext) -> PermissionDecision:
    permissions = context.permissions
    if permissions is None:
        return PermissionDecision(True, "权限系统未启用", "disabled")

    if call.name == "Bash":
        command = _string_arg(call.arguments, "command")
        dangerous = check_dangerous_command(command)
        if dangerous is not None:
            return dangerous

    sandbox_decision = _check_sandbox(call, context, permissions)
    if sandbox_decision is not None:
        return sandbox_decision

    internal_state_decision = _check_internal_state_write(call, context)
    if internal_state_decision is not None:
        return internal_state_decision

    for rule in permissions.session_rules:
        if match_rule(rule, call):
            return _decision_from_rule(rule)
    for rule in permissions.rules:
        if match_rule(rule, call):
            return _decision_from_rule(rule)

    target = target_value_for_call(call)
    risk = _risk_for_call(call, tool, context)
    if permissions.mode == "strict":
        return PermissionDecision(False, "严格模式拒绝未匹配规则的工具调用", "mode", risk=risk)
    if permissions.mode == "permissive":
        return PermissionDecision(True, "放行模式允许未匹配规则的工具调用", "mode", risk=risk)
    if risk == "low":
        return PermissionDecision(True, "默认模式允许低风险只读工具调用", "mode", risk=risk)

    if permissions.confirmer is None:
        return PermissionDecision(False, "需要用户确认，但当前没有可用确认器", "confirmation", True, risk=risk)
    request = PermissionRequest(call=call, target=target, risk=risk, reason="默认模式需要确认副作用或风险操作")
    confirmation = permissions.confirmer.confirm(request)
    return _decision_from_confirmation(confirmation, call, permissions, risk)


def permission_denied_result(call: ToolCall, decision: PermissionDecision) -> ToolResult:
    return ToolResult.failure(
        "permission_denied",
        decision.reason,
        {
            "tool": call.name,
            "source": decision.source,
            "matched_rule": decision.matched_rule,
            "risk": decision.risk,
            "requires_confirmation": decision.requires_confirmation,
        },
        f"permission denied by {decision.source}: {decision.reason}",
    )


def _check_sandbox(call: ToolCall, context: ToolContext, permissions: PermissionContext) -> PermissionDecision | None:
    for path in extract_tool_paths(call.name, call.arguments):
        try:
            resolve_workspace_path(permissions.workspace or context.workspace, path)
        except ValueError as exc:
            return PermissionDecision(False, str(exc), "sandbox", risk="high")
    return None


def _check_internal_state_write(call: ToolCall, context: ToolContext) -> PermissionDecision | None:
    protected = (".huicode/memory", ".huicode/sessions")
    workspace = (
        context.permissions.workspace
        if context.permissions and context.permissions.workspace
        else context.workspace
    )
    if call.name in {"Write", "Edit"}:
        for raw_path in extract_tool_paths(call.name, call.arguments):
            try:
                relative = (
                    resolve_workspace_path(workspace, raw_path)
                    .relative_to(workspace.resolve())
                    .as_posix()
                    .lower()
                )
            except (ValueError, OSError):
                continue
            if any(relative == root or relative.startswith(f"{root}/") for root in protected):
                return PermissionDecision(
                    False,
                    "HuiCode 会话和长期记忆由后台自动维护，请勿通过文件工具修改",
                    "internal_state",
                    risk="medium",
                )
    if call.name == "Bash":
        command = _string_arg(call.arguments, "command")
        normalized = command.replace("\\", "/").lower()
        if any(root in normalized for root in protected) and not _is_read_only_shell_command(command, context):
            return PermissionDecision(
                False,
                "HuiCode 会话和长期记忆由后台自动维护，请勿通过 Bash 修改",
                "internal_state",
                risk="medium",
            )
    return None


def _decision_from_rule(rule: PermissionRule) -> PermissionDecision:
    allowed = rule.action == "allow"
    return PermissionDecision(
        allowed=allowed,
        reason=f"命中权限规则 {rule.raw or f'{rule.tool}({rule.pattern})'}: {rule.action}",
        source=f"{rule.source}_rule",
        matched_rule=rule.raw or f"{rule.tool}({rule.pattern})",
        risk="low" if allowed else "medium",
    )


def _decision_from_confirmation(
    confirmation: PermissionConfirmation,
    call: ToolCall,
    permissions: PermissionContext,
    risk: str,
) -> PermissionDecision:
    if confirmation.action == "deny":
        return PermissionDecision(False, "用户拒绝本次工具调用", "confirmation", risk=risk)
    target = target_value_for_call(call)
    rule = PermissionRule(call.name, target or "*", "allow", source="session", raw=f"{call.name}({target or '*'})")
    if confirmation.action == "session":
        permissions.session_rules.insert(0, rule)
        return PermissionDecision(True, "用户允许本会话同类工具调用", "confirmation", risk=risk)
    if confirmation.action == "always":
        if permissions.persistent_path is not None:
            append_persistent_rule(permissions.persistent_path, rule)
        permissions.session_rules.insert(0, rule)
        return PermissionDecision(True, "用户永久允许同类工具调用", "confirmation", risk=risk)
    return PermissionDecision(True, "用户允许本次工具调用", "confirmation", risk=risk)


def _risk_for_call(call: ToolCall, tool, context: ToolContext) -> str:
    if call.name == "Bash" and _is_read_only_shell_command(_string_arg(call.arguments, "command"), context):
        return "low"
    return _risk_for_tool(tool)


def _risk_for_tool(tool) -> str:
    if tool is None:
        return "high"
    if getattr(tool, "side_effect", True):
        return "medium"
    return "low"


def _string_arg(args: dict[str, object], key: str) -> str:
    value = args.get(key)
    return value if isinstance(value, str) else ""


def _is_read_only_shell_command(command: str, context: ToolContext) -> bool:
    if not command.strip():
        return False
    lowered = command.lower()
    if any(operator in lowered for operator in (">", ">>", "&&", "||", ";")):
        return False
    if not _absolute_paths_stay_in_workspace(command, context):
        return False
    segments = [segment.strip() for segment in command.split("|")]
    return bool(segments) and all(_is_read_only_shell_segment(segment) for segment in segments)


def _is_read_only_shell_segment(segment: str) -> bool:
    if not segment:
        return False
    normalized = segment.strip().lower()
    if normalized.startswith(("cmd /c ", "powershell ", "powershell.exe ", "pwsh ", "pwsh.exe ")):
        return False

    first = normalized.split(maxsplit=1)[0]
    if first in {
        "dir",
        "tree",
        "where",
        "where.exe",
        "findstr",
        "findstr.exe",
        "type",
        "more",
        "ls",
        "cat",
        "pwd",
        "head",
        "sort",
    }:
        return True
    if first in {"get-childitem", "gci", "get-content", "select-string", "test-path", "get-location"}:
        return True
    if first == "select-object" and (" -first " in f" {normalized} " or normalized.startswith("select-object -first")):
        return True
    if normalized.startswith("git "):
        return _is_read_only_git_command(normalized)
    return False


def _is_read_only_git_command(command: str) -> bool:
    parts = command.split()
    if len(parts) < 2:
        return False
    if any(part == "-o" or part.startswith("--output") for part in parts[2:]):
        return False
    return parts[1] in {"status", "diff", "log", "show", "branch", "ls-files", "rev-parse", "remote"}


def _absolute_paths_stay_in_workspace(command: str, context: ToolContext) -> bool:
    import re

    workspace = (context.permissions.workspace if context.permissions and context.permissions.workspace else context.workspace)
    for match in re.finditer(r"(?i)([A-Z]:\\[^\s|\"']+)", command):
        try:
            resolved = resolve_workspace_path(workspace, match.group(1))
        except ValueError:
            return False
        if not is_within_workspace(workspace, resolved):
            return False
    return True
