from __future__ import annotations

from typing import Any

from huicode.tools.base import ToolContext, ToolResult

from .manager import SubagentManager
from .types import SubagentLaunchRequest


class AgentTool:
    name = "Agent"
    description = (
        "把独立子任务委派给定义式或 Fork 式子 Agent。定义式需要 role；Fork 继承父历史并强制后台。"
    )
    side_effect = True
    parameters = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["defined", "fork"]},
            "task": {"type": "string", "description": "明确的子任务与期望产出"},
            "role": {"type": "string", "description": "定义式角色名"},
            "background": {"type": "boolean", "description": "定义式是否立即后台运行"},
        },
        "required": ["type", "task"],
        "additionalProperties": False,
    }

    def __init__(self, manager: SubagentManager) -> None:
        self.manager = manager

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        del context
        kind = args.get("type")
        task_text = args.get("task")
        role = args.get("role")
        background = args.get("background", False)
        if kind not in {"defined", "fork"}:
            return ToolResult.failure("invalid_request", "type 只允许 defined 或 fork")
        if not isinstance(task_text, str) or not task_text.strip():
            return ToolResult.failure("invalid_request", "task 必须是非空字符串")
        if not isinstance(background, bool):
            return ToolResult.failure("invalid_request", "background 必须是布尔值")
        if kind == "defined":
            if not isinstance(role, str) or not role.strip():
                return ToolResult.failure("invalid_request", "defined 类型必须提供 role")
            if self.manager.catalog.get(role) is None:
                return ToolResult.failure("unknown_role", f"未知子 Agent 角色: {role}")
            normalized_role: str | None = role.strip().lower()
        else:
            if role is not None:
                return ToolResult.failure("invalid_request", "fork 类型不得提供 role")
            normalized_role = None
            background = True
        parent = self.manager.parent_snapshot()
        if parent is None:
            return ToolResult.failure("runtime_unavailable", "当前没有可用的主 Agent 快照")
        submitted = None
        try:
            submitted = self.manager.submit(
                SubagentLaunchRequest(
                    type=kind,
                    task=task_text.strip(),
                    role=normalized_role,
                    background=background,
                    parent=parent,
                )
            )
            if background:
                return ToolResult.success(
                    {"task_id": submitted.id, "status": submitted.status, "background": True},
                    f"submitted {submitted.id} in background",
                )
            waited = self.manager.wait_foreground(submitted.id)
        except KeyboardInterrupt:
            if submitted is not None:
                self.manager.cancel(submitted.id)
            raise
        except (RuntimeError, ValueError) as exc:
            return ToolResult.failure("subagent_error", str(exc))
        if waited.reason != "completed":
            return ToolResult.success(
                {
                    "task_id": waited.task.id,
                    "status": waited.task.status,
                    "background": True,
                    "reason": waited.reason,
                },
                f"{waited.task.id} moved to background ({waited.reason})",
            )
        if waited.task.status == "completed":
            return ToolResult.success(
                {
                    "task_id": waited.task.id,
                    "summary": waited.task.summary,
                    "stop_reason": waited.task.stop_reason,
                    "iterations": waited.task.iterations,
                    "usage": waited.task.usage,
                },
                f"completed {waited.task.id}: {waited.task.summary[:120]}",
            )
        return ToolResult.failure(
            "subagent_failed",
            waited.task.error or waited.task.summary,
            {
                "task_id": waited.task.id,
                "status": waited.task.status,
                "stop_reason": waited.task.stop_reason,
            },
        )
