"""把工具调用接进服务端的权限判断（checklist C49–C51、C54）。

**桥接而不是重写。** 危险命令黑名单、路径沙箱、内部状态保护、规则匹配、三种权限
模式——这些语义 CLI 已经有了（`huicode/permissions/engine.py`）。这里不复制一份，
而是把服务端的情况**适配**成那套引擎能吃的输入（`PermissionContext`），再在它前面
补两道服务端特有的检查。复制一份的后果是 CLI 与 Web 的行为慢慢分叉，而 C9/AC9 明确
要求两边语义一致。

```text
     ┌─ 1. 工具必须存在且在本次运行的允许集合内 ──── C54
     ├─ 2. Plan Mode 只放行"只能读"的工具 ─────────── C50
     ├─ 3. 未声明能力的工具不得走自动放行 ─────────── C49
     └─ 4. 既有引擎：黑名单 / 沙箱 / 内部状态 / 规则 / 模式 / 确认
                              │
                              ▼
              allow ─ 无事件
              request_approval ─ tool_approval_requested（T14 补 approval_id）
              deny ── error 事件（只带安全分类，不带内部配置）── C51
```

**权限状态由服务端构造，不从请求里读。** `evaluate_call` 无论调用方传进来什么
`ToolContext`，都会用它自己从 `PermissionSnapshot` 重建的 `PermissionContext` 覆盖掉
里面的 `permissions`。这不是洁癖：只要"用哪个权限模式"存在一条从请求参数到判断的
路径，C54 就不成立。**前端不给权限判断提供任何输入**，它只展示结果。

**服务端没有同步确认器。** CLI 可以阻塞等用户敲 y/n；服务端不能占着一个线程等人。
所以这里**不传 confirmer**：引擎返回"需要确认"时，桥接把它翻译成一次审批请求事件，
Run 停在等待审批的状态（T14 的 ApprovalBroker 负责唤醒）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from huicode.permissions.base import PermissionContext, PermissionMode, PermissionRule
from huicode.permissions.engine import evaluate_permission
from huicode.permissions.rules import target_value_for_call
from huicode.providers.base import ToolCall
from huicode.server.runtime.capabilities import (
    is_declared,
    is_read_only,
    risk_of,
    summarise,
)
from huicode.tools.base import ToolContext
from huicode.tools.registry import ToolRegistry

PermissionAction = Literal["allow", "deny", "request_approval"]

PERMISSION_MODES: frozenset[str] = frozenset({"strict", "default", "permissive"})

# ── 安全分类 ────────────────────────────────────────────────────────────
# 拒绝与审批事件只带分类，**不带引擎给的人话原因**：原因里会出现规则原文
# （`命中权限规则 Bash(rm -rf *): deny`），那是用户的权限配置。事件对工作区所有
# 成员可见，把配置读给所有人看不合适（C51）。
CATEGORY_UNKNOWN_TOOL = "unknown_tool"
CATEGORY_TOOL_NOT_ALLOWED = "tool_not_allowed"
CATEGORY_PLAN_MODE = "plan_mode"
CATEGORY_CAPABILITY_UNDECLARED = "capability_undeclared"
CATEGORY_DANGEROUS_COMMAND = "dangerous_command"
CATEGORY_OUTSIDE_WORKSPACE = "path_outside_workspace"
CATEGORY_INTERNAL_STATE = "internal_state"
CATEGORY_RULE = "rule"
CATEGORY_MODE = "mode"
CATEGORY_CONFIRMATION = "confirmation"
CATEGORY_PERMISSIONS_DISABLED = "permissions_disabled"

#: 分类 → 面向用户的一句话。**事件载荷只能取自这张表**，不能取自引擎的 reason。
CATEGORY_MESSAGES: dict[str, str] = {
    CATEGORY_UNKNOWN_TOOL: "该工具不存在",
    CATEGORY_TOOL_NOT_ALLOWED: "该工具不在本次运行允许的工具范围内",
    CATEGORY_PLAN_MODE: "Plan Mode 只允许读类工具",
    CATEGORY_CAPABILITY_UNDECLARED: "该工具未声明能力，需要人工确认",
    CATEGORY_DANGEROUS_COMMAND: "命令被安全策略拦截",
    CATEGORY_OUTSIDE_WORKSPACE: "路径超出工作目录",
    CATEGORY_INTERNAL_STATE: "HuiCode 内部状态由后台维护，不允许通过工具修改",
    CATEGORY_RULE: "命中权限规则",
    CATEGORY_MODE: "当前权限模式不允许该调用",
    CATEGORY_CONFIRMATION: "需要用户确认",
    CATEGORY_PERMISSIONS_DISABLED: "权限系统不可用",
}

_SOURCE_TO_CATEGORY: dict[str, str] = {
    "blacklist": CATEGORY_DANGEROUS_COMMAND,
    "sandbox": CATEGORY_OUTSIDE_WORKSPACE,
    "internal_state": CATEGORY_INTERNAL_STATE,
    "rule": CATEGORY_RULE,
    "session_rule": CATEGORY_RULE,
    "mode": CATEGORY_MODE,
    "confirmation": CATEGORY_CONFIRMATION,
    "disabled": CATEGORY_PERMISSIONS_DISABLED,
}


@dataclass(frozen=True)
class PermissionSnapshot:
    """一次 Run 的权限状态。**由服务端构造**（工作区、角色、项目设置），
    请求体里没有任何字段能影响它。"""

    workspace: Path
    allowed_tool_names: frozenset[str]
    mode: PermissionMode = "default"
    plan_mode: bool = False
    rules: tuple[PermissionRule, ...] = ()

    def __post_init__(self):
        if self.mode not in PERMISSION_MODES:
            # fail closed：认不出的模式按最严格的来，而不是按默认的来。
            object.__setattr__(self, "mode", "strict")
        object.__setattr__(self, "allowed_tool_names", frozenset(self.allowed_tool_names))
        object.__setattr__(self, "rules", tuple(self.rules))


@dataclass(frozen=True)
class PermissionOutcome:
    """权限判断的结果，以及它该变成哪条事件。"""

    action: PermissionAction
    tool: str
    security_category: str
    risk: str
    resolved_tool: str | None = None
    target: str = ""
    capabilities: tuple[str, ...] = ()
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    @property
    def requires_approval(self) -> bool:
        return self.action == "request_approval"

    @property
    def event_type(self) -> str | None:
        """`None` 表示放行不需要产生事件——放行是常态，为每次放行写一条事件会把
        事件流淹掉（真正记录"调用了什么"的是 `tool_call_started`）。"""
        if self.action == "request_approval":
            return "tool_approval_requested"
        if self.action == "deny":
            return "error"
        return None

    def to_event_payload(self) -> dict:
        """事件载荷。**只由分类查表得到**，不转发引擎的原始原因（C51）。

        审批请求带上 `target`（要执行的命令 / 要写的路径）：审批人必须看到自己
        在批准什么。它可能包含密钥（例如 `export KEY=...`），但审批事件走
        `store.append` 落库，脱敏在那条路径上（T11）。
        """
        message = CATEGORY_MESSAGES.get(self.security_category, "工具调用被拒绝")
        payload: dict = {
            "tool": self.tool,
            "resolved_tool": self.resolved_tool,
            "risk": self.risk,
            "security_category": self.security_category,
            "message": message,
        }
        if self.action == "request_approval":
            payload["target"] = self.target
            payload["capabilities"] = list(self.capabilities)
        if self.action == "deny":
            payload["error_code"] = "permission_denied"
        return payload


def build_permission_context(snapshot: PermissionSnapshot) -> PermissionContext:
    """把快照适配成既有引擎认识的 `PermissionContext`。

    `confirmer` 刻意留空，`persistent_path` 也留空——服务端不阻塞等人，"永久允许"
    要落库并由 T14 的审批流程管理，不能写本地 YAML。
    """
    return PermissionContext(
        workspace=snapshot.workspace,
        mode=snapshot.mode,
        rules=list(snapshot.rules),
        session_rules=[],
        confirmer=None,
        persistent_path=None,
    )


def build_tool_context(
    snapshot: PermissionSnapshot,
    *,
    read_cache=None,
    protect_test_edits: bool = False,
    timeout_seconds: int = 10,
    max_output_chars: int = 6000,
) -> ToolContext:
    """构造 Runner 实际使用的 `ToolContext`。权限部分一定来自快照。"""
    return ToolContext(
        workspace=snapshot.workspace,
        permissions=build_permission_context(snapshot),
        read_cache=read_cache,
        protect_test_edits=protect_test_edits,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )


def evaluate_call(
    call: ToolCall,
    registry: ToolRegistry,
    snapshot: PermissionSnapshot,
    *,
    context: ToolContext | None = None,
) -> PermissionOutcome:
    """判断一次工具调用，返回结果与它对应的事件。

    调用方传进来的 `context` 只用来携带 read_cache 之类的运行状态；
    **它的 `permissions` 会被快照重建的那份覆盖**，所以传什么都改变不了判断。
    """
    resolved = registry.resolve_name(call.name)
    if resolved is None:
        return _outcome(
            "deny", call.name, CATEGORY_UNKNOWN_TOOL, risk="high", resolved=None
        )

    tool = registry.get(call.name)
    capability_info = summarise(tool)
    risk = risk_of(tool)

    if resolved not in snapshot.allowed_tool_names:
        return _outcome(
            "deny", call.name, CATEGORY_TOOL_NOT_ALLOWED, risk,
            resolved=resolved, capabilities=capability_info["capabilities"],
        )

    if snapshot.plan_mode and not is_read_only(tool) and resolved not in registry.system_tool_names():
        return _outcome(
            "deny", call.name, CATEGORY_PLAN_MODE, risk,
            resolved=resolved, capabilities=capability_info["capabilities"],
        )

    base = context if context is not None else ToolContext(workspace=snapshot.workspace)
    bounded = replace(base, workspace=snapshot.workspace, permissions=build_permission_context(snapshot))

    decision = evaluate_permission(call, tool, bounded)
    category = _SOURCE_TO_CATEGORY.get(decision.source, CATEGORY_MODE)

    if decision.requires_confirmation and not decision.allowed:
        # 没有同步确认器时的"需要确认"就是**一次审批请求**，不是拒绝。
        return _outcome(
            "request_approval", call.name, category, decision.risk,
            resolved=resolved, target=_target(call), capabilities=capability_info["capabilities"],
        )
    if not decision.allowed:
        return _outcome(
            "deny", call.name, category, decision.risk,
            resolved=resolved, capabilities=capability_info["capabilities"],
        )

    # 走到这里引擎说"放行"。但自动放行（source=="mode"）不能用在没声明能力的工具上：
    # 引擎只看到 side_effect 布尔量，看不到"这个工具会不会出网"。
    # permissive 模式除外——那是运维明确选择的"放行未匹配规则的调用"，不该被架空。
    if decision.source == "mode" and snapshot.mode != "permissive" and not is_declared(tool):
        return _outcome(
            "request_approval", call.name, CATEGORY_CAPABILITY_UNDECLARED, "high",
            resolved=resolved, target=_target(call), capabilities=capability_info["capabilities"],
        )

    return _outcome(
        "allow", call.name, category, decision.risk,
        resolved=resolved, capabilities=capability_info["capabilities"],
    )


def evaluate_calls(
    calls: list[ToolCall],
    registry: ToolRegistry,
    snapshot: PermissionSnapshot,
) -> list[PermissionOutcome]:
    """按顺序判断一组调用。用来表达"同一个任务在不同权限模式下跑一遍"。"""
    return [evaluate_call(call, registry, snapshot) for call in calls]


def _outcome(
    action: PermissionAction,
    tool: str,
    category: str,
    risk: str,
    *,
    resolved: str | None,
    target: str = "",
    capabilities: list[str] | tuple[str, ...] = (),
) -> PermissionOutcome:
    return PermissionOutcome(
        action=action,
        tool=tool,
        security_category=category,
        risk=risk,
        resolved_tool=resolved,
        target=target,
        capabilities=tuple(capabilities),
        reason=CATEGORY_MESSAGES.get(category, ""),
    )


def _target(call: ToolCall) -> str:
    """审批人要看到的那一行：要跑的命令、要写的路径。"""
    return target_value_for_call(call)
