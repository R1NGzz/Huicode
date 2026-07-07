from __future__ import annotations

from fnmatch import fnmatchcase

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
    if _canonical_tool(rule.tool) != _canonical_tool(call.name):
        return False
    target = target_value_for_call(call)
    return target == rule.pattern or fnmatchcase(target, rule.pattern)


def target_value_for_call(call: ToolCall) -> str:
    args = call.arguments
    name = _canonical_tool(call.name)
    if name == "Bash":
        return _string_arg(args, "command")
    if name in {"Read", "Write", "Edit"}:
        return _string_arg(args, "path")
    if name == "Find":
        return _string_arg(args, "pattern")
    if name == "Search":
        return _string_arg(args, "glob") or _string_arg(args, "pattern")
    return ""


def _canonical_tool(name: str) -> str:
    return "Find" if name == "Glob" else name


def _string_arg(args: dict[str, object], key: str) -> str:
    value = args.get(key)
    return value if isinstance(value, str) else ""

