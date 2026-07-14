from __future__ import annotations

from huicode.permissions import evaluate_permission, permission_denied_result
from huicode.providers.base import ToolCall

from .base import ToolContext, ToolResult
from .registry import ToolRegistry


def execute_tool_call(registry: ToolRegistry, call: ToolCall, context: ToolContext) -> ToolResult:
    tool = registry.get(call.name)
    if tool is None:
        return ToolResult.failure("unknown_tool", f"未知工具: {call.name}", {"tool": call.name})
    if not isinstance(call.arguments, dict):
        return ToolResult.failure("invalid_arguments", "工具参数必须是 JSON 对象", {"tool": call.name})

    resolved_name = registry.resolve_name(call.name)
    if resolved_name not in registry.system_tool_names():
        decision = evaluate_permission(call, tool, context)
        if not decision.allowed:
            return permission_denied_result(call, decision)

    try:
        return tool.run(call.arguments, context)
    except Exception as exc:  # noqa: BLE001 - 工具边界必须兜底，避免会话崩溃
        return ToolResult.failure("tool_exception", f"工具执行异常: {exc}", {"tool": call.name})
