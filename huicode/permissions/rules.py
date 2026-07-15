from __future__ import annotations

from huicode.matching import match_exact_or_glob
from huicode.permissions.base import PermissionRule
from huicode.providers.base import ToolCall


def parse_rule_key(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if not stripped.endswith(")") or "(" not in stripped:
        raise ValueError(f"权限规则必须是 工具名(模式) 格式: {text}")
    tool, pattern = stripped[:-1].split("(", 1)
    tool = tool.strip()
    pattern = pattern.strip()
    if not tool or not pattern:
        raise ValueError(f"权限规则必须包含工具名和模式: {text}")
    return tool, pattern


def match_rule(rule: PermissionRule, call: ToolCall) -> bool:
    if canonical_tool_name(rule.tool) != canonical_tool_name(call.name):
        return False
    target = target_value_for_call(call)
    return match_exact_or_glob(target, rule.pattern)


def target_value_for_call(call: ToolCall) -> str:
    args = call.arguments
    name = canonical_tool_name(call.name)
    if name == "Bash":
        return _string_arg(args, "command")
    if name in {"Read", "Write", "Edit"}:
        return _string_arg(args, "path")
    if name == "Find":
        return _string_arg(args, "pattern")
    if name == "Search":
        return _string_arg(args, "glob") or _string_arg(args, "pattern")
    return ""


def canonical_tool_name(name: str) -> str:
    return "Find" if name == "Glob" else name


def _string_arg(args: dict[str, object], key: str) -> str:
    value = args.get(key)
    return value if isinstance(value, str) else ""
