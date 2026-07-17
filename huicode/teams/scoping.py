from __future__ import annotations

import re
from typing import Any

from huicode.tools.base import ToolContext, ToolResult
from huicode.tools.registry import ToolRegistry
from huicode.providers.base import ToolSpec

from .approval import ApprovalGate
from .types import TeamRuntimeIdentity


TEAM_TOOL_NAMES = frozenset({"Team", "TeamTask", "TeamMessage", "TeamPlanRequest", "TeamPlanDecision", "TeamIntegrate"})
LEAD_TOOLS = frozenset({"Team", "TeamTask", "TeamMessage", "TeamPlanDecision", "TeamIntegrate"})
MEMBER_TOOLS = frozenset({"TeamTask", "TeamMessage", "TeamPlanRequest"})


class CoordinatorGitTool:
    name = "Bash"
    description = "Coordinator 专用 Git 诊断命令；不允许普通 shell、重定向或管道。"
    side_effect = True
    parameters = {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"], "additionalProperties": False}
    _allowed = {"status", "log", "diff", "show", "branch", "rev-parse", "worktree", "merge"}

    def __init__(self, delegate) -> None:  # noqa: ANN001
        self.delegate = delegate

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        command = args.get("command")
        if not isinstance(command, str) or re.search(r"[|&;<>`\r\n]", command):
            return ToolResult.failure("coordinator_denied", "Coordinator 只允许不含 shell 控制符的 Git 命令")
        parts = command.strip().split()
        if len(parts) < 2 or parts[0].lower() != "git" or parts[1].lower() not in self._allowed:
            return ToolResult.failure("coordinator_denied", "Coordinator 只允许 Git 协调与集成命令")
        if parts[1].lower() in {"show", "diff", "log", "status", "rev-parse"} or "--abort" in parts:
            return self.delegate.run(args, context)
        return ToolResult.failure("coordinator_denied", "请通过 TeamIntegrate 执行会修改分支的 Git 操作")


class ScopedToolRegistry:
    def __init__(self, registry: ToolRegistry, identity: TeamRuntimeIdentity, *, approval_gate: ApprovalGate | None = None, task_id: str = "", allowed_tools: tuple[str, ...] | list[str] | None = None, denied_tools: tuple[str, ...] | list[str] = ()) -> None:
        self.registry = registry
        self.identity = identity
        self.approval_gate = approval_gate
        self.task_id = task_id
        self.allowed_tools = None if allowed_tools is None else tuple(allowed_tools)
        self.denied_tools = tuple(denied_tools)

    def _visible(self) -> set[str]:
        names = {tool.name for tool in self.registry.list()}
        names.difference_update(TEAM_TOOL_NAMES)
        if self.identity.scope == "main":
            names.add("Team")
        elif self.identity.scope == "team_lead":
            names.update(LEAD_TOOLS)
            names.discard("Agent")
        elif self.identity.scope == "team_member":
            names.update(MEMBER_TOOLS)
            names.discard("Agent")
            names.discard("Skill")
            if self.approval_gate is not None and self.identity.member_id and not self.approval_gate.allows_side_effect(self.identity.member_id, self.task_id):
                names = {name for name in names if not self.registry.is_side_effect(name) or name in MEMBER_TOOLS}
        else:
            names.difference_update(TEAM_TOOL_NAMES)
        if self.identity.scope == "team_member" and self.allowed_tools is not None:
            allowed, _ = self.registry.normalize_names(set(self.allowed_tools))
            names.intersection_update(allowed | MEMBER_TOOLS)
        if self.identity.scope == "team_member" and self.denied_tools:
            denied, _ = self.registry.normalize_names(set(self.denied_tools))
            names.difference_update(denied - MEMBER_TOOLS)
        if self.identity.coordinator:
            names.difference_update({"Write", "Edit"})
        return names

    def resolve_name(self, name: str) -> str | None:
        resolved = self.registry.resolve_name(name)
        return resolved if resolved in self._visible() else None

    def get(self, name: str):  # noqa: ANN201
        resolved = self.resolve_name(name)
        if resolved is None:
            return None
        tool = self.registry.get(resolved)
        if self.identity.coordinator and resolved == "Bash" and tool is not None:
            return CoordinatorGitTool(tool)
        if tool is not None and resolved in TEAM_TOOL_NAMES:
            return IdentityBoundTeamTool(tool, self.identity)
        return tool

    def list(self):  # noqa: ANN201
        return [self.get(name) for name in sorted(self._visible()) if self.get(name) is not None]

    def system_tool_names(self) -> frozenset[str]:
        return self.registry.system_tool_names() & self._visible()

    def ordinary_tool_names(self) -> frozenset[str]:
        return frozenset(self._visible()) - self.system_tool_names()

    def normalize_names(self, names):  # noqa: ANN001, ANN201
        resolved = {item for name in names if (item := self.resolve_name(name)) is not None}
        return resolved, set(names) - resolved

    def is_side_effect(self, name: str) -> bool:
        tool = self.get(name)
        return True if tool is None else bool(tool.side_effect)

    def to_specs(self, allowed_names=None, *, include_system=True):  # noqa: ANN001, ANN201
        names = self._visible()
        if allowed_names is not None:
            requested, _ = self.registry.normalize_names(set(allowed_names))
            names.intersection_update(requested | (self.system_tool_names() if include_system else set()))
        return [ToolSpec(tool.name, tool.description, tool.parameters) for tool in self.list() if tool.name in names]


class IdentityBoundTeamTool:
    def __init__(self, delegate, identity: TeamRuntimeIdentity) -> None:  # noqa: ANN001
        self.delegate = delegate
        self.identity = identity
        self.name = delegate.name
        self.description = delegate.description
        self.parameters = delegate.parameters
        self.side_effect = delegate.side_effect

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        values = dict(args)
        if self.name == "TeamMessage":
            values["sender"] = "lead" if self.identity.scope == "team_lead" else self.identity.member_id
        if self.name == "TeamPlanRequest":
            values["member"] = self.identity.member_id
        if self.identity.scope == "team_member" and self.name == "TeamTask":
            if values.get("action") not in {"list", "get", "claim", "update"}:
                return ToolResult.failure("team_scope_denied", "团队成员不能执行该任务管理操作")
            if values.get("action") == "claim":
                values["member"] = self.identity.member_id
        return self.delegate.run(values, context)
