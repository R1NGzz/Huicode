from __future__ import annotations

from typing import Any

from huicode.tools.base import ToolContext, ToolResult

from .integration import IntegrationManager
from .manager import TeamManager
from .types import TeamError, record_dict


class _TeamTool:
    side_effect = True
    def __init__(self, manager: TeamManager) -> None:
        self.manager = manager
    def _run(self, function):  # noqa: ANN001, ANN202
        try:
            value = function()
            data = record_dict(value) if hasattr(value, "__dataclass_fields__") else value
            return ToolResult.success(data if isinstance(data, dict) else {"result": data}, "ok")
        except TeamError as exc:
            return ToolResult.failure(exc.code, str(exc), exc.details)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure("team_error", str(exc))


class TeamTool(_TeamTool):
    name = "Team"
    description = "创建、恢复、查看团队并管理长期成员；spawn 成功时会强制创建并返回成员独立 Worktree。"
    parameters = {"type": "object", "properties": {"action": {"type": "string", "enum": ["create", "resume", "list", "status", "spawn", "stop", "close", "delete"]}, "name": {"type": "string", "description": "团队名或成员名，取决于 action"}, "role": {"type": "string", "description": "成员角色标签；可使用自由角色。若与已加载 Agent 角色同名，则继承其指令、工具、模型、轮次和权限设置"}, "backend": {"type": "string", "enum": ["auto", "terminal", "coroutine"]}, "approval_required": {"type": "boolean"}}, "required": ["action"], "additionalProperties": False}
    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        del context
        action = args.get("action")
        if action == "create": return self._run(lambda: self.manager.create(str(args.get("name", ""))))
        if action == "resume": return self._run(lambda: self.manager.resume(str(args.get("name", ""))))
        if action == "list": return self._run(lambda: {"teams": self.manager.list_teams()})
        if action == "status": return self._run(self.manager.status)
        if action == "spawn": return self._run(lambda: self.manager.spawn_member(str(args.get("name", "")), str(args.get("role", "general")), backend=args.get("backend"), approval_required=bool(args.get("approval_required", False))))
        if action == "stop": return self._run(lambda: self.manager.stop_member(str(args.get("name", ""))))
        if action == "close": return self._run(self.manager.close_team)
        if action == "delete": return self._run(self.manager.delete_team)
        return ToolResult.failure("invalid_request", "未知 Team action")


class TeamTaskTool(_TeamTool):
    name = "TeamTask"
    description = "管理团队共享任务及依赖。"
    parameters = {"type": "object", "properties": {"action": {"type": "string", "enum": ["create", "list", "get", "claim", "update", "delete", "assign"]}, "task_id": {"type": "string"}, "title": {"type": "string"}, "description": {"type": "string"}, "dependencies": {"type": "array", "items": {"type": "string"}}, "member": {"type": "string"}, "prompt": {"type": "string"}, "expected_version": {"type": "integer"}, "status": {"type": "string"}, "result_summary": {"type": "string"}}, "required": ["action"], "additionalProperties": False}
    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        del context
        tasks = self.manager._require_tasks(); action = args.get("action")
        if action == "create": return self._run(lambda: tasks.create(str(args.get("title", "")), str(args.get("description", "")), tuple(args.get("dependencies") or ())))
        if action == "list": return self._run(lambda: {"tasks": [record_dict(item) for item in tasks.list()]})
        if action == "get": return self._run(lambda: tasks.get(str(args.get("task_id", ""))))
        if action == "claim": return self._run(lambda: tasks.claim(str(args.get("task_id", "")), str(args.get("member", "")), int(args.get("expected_version", 0))))
        if action == "update": return self._run(lambda: tasks.update(str(args.get("task_id", "")), expected_version=int(args.get("expected_version", 0)), status=args.get("status"), result_summary=args.get("result_summary")))
        if action == "delete": return self._run(lambda: tasks.delete(str(args.get("task_id", "")), int(args.get("expected_version", 0))) or {"deleted": True})
        if action == "assign": return self._run(lambda: self.manager.assign(str(args.get("task_id", "")), str(args.get("member", "")), str(args.get("prompt", ""))) or {"assigned": True})
        return ToolResult.failure("invalid_request", "未知 TeamTask action")


class TeamMessageTool(_TeamTool):
    name = "TeamMessage"; description = "向团队成员发送消息或读取邮箱。"; side_effect = True
    parameters = {"type": "object", "properties": {"action": {"type": "string", "enum": ["send", "broadcast", "inbox", "read"]}, "sender": {"type": "string"}, "recipients": {"type": "array", "items": {"type": "string"}}, "body": {"type": "string"}, "message_id": {"type": "string"}}, "required": ["action"], "additionalProperties": False}
    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        del context; action=args.get("action"); box=self.manager._require_mailbox(); sender=str(args.get("sender", "lead"))
        if action == "send": return self._run(lambda: self.manager.send_message(sender, tuple(args.get("recipients") or ()), str(args.get("body", ""))))
        if action == "broadcast": return self._run(lambda: box.broadcast(sender, str(args.get("body", ""))))
        if action == "inbox": return self._run(lambda: {"messages": [record_dict(item) for item in box.inbox(sender)[0]]})
        if action == "read": return self._run(lambda: box.mark_read(sender, str(args.get("message_id", ""))))
        return ToolResult.failure("invalid_request", "未知 TeamMessage action")


class TeamPlanRequestTool(_TeamTool):
    name = "TeamPlanRequest"; description = "成员提交需要 Lead 审批的执行计划。"; side_effect = False
    parameters = {"type": "object", "properties": {"member": {"type": "string"}, "task_id": {"type": "string"}, "plan": {"type": "string"}}, "required": ["member", "task_id", "plan"], "additionalProperties": False}
    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        del context; return self._run(lambda: self.manager.approvals.submit_plan(str(args["member"]), str(args["task_id"]), str(args["plan"])))


class TeamPlanDecisionTool(_TeamTool):
    name = "TeamPlanDecision"; description = "Lead 按 request_id 批准或驳回成员计划。"
    parameters = {"type": "object", "properties": {"request_id": {"type": "string"}, "decision": {"type": "string", "enum": ["allow", "deny"]}, "feedback": {"type": "string"}}, "required": ["request_id", "decision"], "additionalProperties": False}
    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        del context
        def decide():
            approval = self.manager.approvals.decide(str(args["request_id"]), str(args["decision"]), str(args.get("feedback", "")))
            self.manager._wake_member(approval.member, warn_only=True)
            return approval
        return self._run(decide)


class TeamIntegrateTool(_TeamTool):
    name = "TeamIntegrate"; description = "在专用 Worktree 检查、合并、发布或中止团队成果。"
    parameters = {"type": "object", "properties": {"action": {"type": "string", "enum": ["start", "status", "continue", "publish", "abort"]}}, "required": ["action"], "additionalProperties": False}
    def __init__(self, manager: TeamManager) -> None:
        super().__init__(manager); self.integration = IntegrationManager(manager)
    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        del context; action=args.get("action")
        if action == "start": return self._run(self.integration.start)
        if action == "status": return self._run(lambda: self.integration.record or {"status": "none"})
        if action == "continue": return self._run(self.integration.continue_after_resolution)
        if action == "publish": return self._run(self.integration.publish)
        if action == "abort": return self._run(self.integration.abort)
        return ToolResult.failure("invalid_request", "未知 TeamIntegrate action")


def register_team_tools(registry, manager: TeamManager) -> None:  # noqa: ANN001
    for tool in (TeamTool(manager), TeamTaskTool(manager), TeamMessageTool(manager), TeamPlanRequestTool(manager), TeamPlanDecisionTool(manager), TeamIntegrateTool(manager)):
        registry.register(tool)
