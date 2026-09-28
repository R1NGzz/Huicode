"""T10 工具能力与权限桥接（checklist C49–C51、C54）。

**为什么这个文件在 tests/integration 里却不需要数据库。** 它集成的是**真实组件**：
真实的默认工具注册表、真实的工具对象、真实的权限引擎与危险命令黑名单、真实的临时
工作目录。这里没有打桩的"假工具"，因为这一层要回答的问题恰恰是"工具**自己声明的
能力**有没有被正确采纳"——换成假工具就把待验证的东西替换掉了。它不碰 PostgreSQL，
所以不设 skip，`pytest tests` 一定跑得到。
"""

import tempfile
import unittest
from pathlib import Path

from huicode.permissions.base import PermissionRule
from huicode.providers.base import ToolCall
from huicode.server.runtime.capabilities import (
    ALL_CAPABILITIES,
    EXTERNAL_SIDE_EFFECT,
    FILE_WRITE,
    NETWORK,
    READ,
    SHELL,
    capabilities_of,
    is_declared,
    is_read_only,
    risk_of,
    summarise,
)
from huicode.server.runtime.permission_bridge import (
    CATEGORY_CAPABILITY_UNDECLARED,
    CATEGORY_CONFIRMATION,
    CATEGORY_DANGEROUS_COMMAND,
    CATEGORY_INTERNAL_STATE,
    CATEGORY_MODE,
    CATEGORY_OUTSIDE_WORKSPACE,
    CATEGORY_PLAN_MODE,
    CATEGORY_TOOL_NOT_ALLOWED,
    CATEGORY_UNKNOWN_TOOL,
    PERMISSION_MODES,
    PermissionSnapshot,
    build_tool_context,
    evaluate_call,
    evaluate_calls,
)
from huicode.tools.registry import ToolRegistry, create_default_registry


class _UndeclaredTool:
    """没有 `capabilities` 的工具。**这是 C49 要挡的情形**，不是测试脚手架的偷懒。"""

    name = "Mystery"
    description = "一个没有声明能力的工具"
    side_effect = False
    parameters = {"type": "object", "properties": {}}

    def run(self, args, context):  # pragma: no cover —— 这个测试不执行工具
        raise AssertionError("不应被执行")


class _MysteryWithStringCapability:
    """把能力写成字符串而不是集合——最容易犯的那种错。"""

    name = "Sloppy"
    description = "把 capabilities 写成了单个字符串"
    side_effect = True
    parameters = {"type": "object", "properties": {}}
    capabilities = "read"

    def run(self, args, context):  # pragma: no cover
        raise AssertionError("不应被执行")


class _SystemTool:
    name = "PlanNote"
    description = "系统工具，Plan Mode 下也允许"
    side_effect = True
    parameters = {"type": "object", "properties": {}}
    capabilities = frozenset({FILE_WRITE})

    def run(self, args, context):  # pragma: no cover
        raise AssertionError("不应被执行")


def _registry(*extra) -> ToolRegistry:
    registry = create_default_registry(Path("."))
    for tool in extra:
        registry.register(tool)
    return registry


class CapabilityDeclarationTests(unittest.TestCase):
    """C49：每个内置工具的能力元数据必须正确，缺声明按高风险。"""

    def setUp(self):
        self.registry = _registry()

    def test_every_builtin_tool_declares_capabilities(self):
        for tool in self.registry.list():
            with self.subTest(tool=tool.name):
                self.assertTrue(is_declared(tool), f"{tool.name} 没有声明能力")
                self.assertTrue(capabilities_of(tool) <= ALL_CAPABILITIES)

    def test_read_tools_are_low_risk_and_read_only(self):
        for name in ("Read", "Find", "Search"):
            with self.subTest(tool=name):
                tool = self.registry.get(name)
                self.assertEqual(risk_of(tool), "low")
                self.assertTrue(is_read_only(tool))
                self.assertFalse(tool.side_effect)

    def test_file_writers_are_medium_risk_and_not_read_only(self):
        for name in ("Write", "Edit"):
            with self.subTest(tool=name):
                tool = self.registry.get(name)
                self.assertEqual(risk_of(tool), "medium")
                self.assertFalse(is_read_only(tool))

    def test_shell_is_high_risk_because_it_can_do_everything(self):
        """一条任意命令既能写文件也能出网。少声明会让信任声明的策略低估它。"""
        tool = self.registry.get("Bash")
        self.assertEqual(risk_of(tool), "high")
        self.assertFalse(is_read_only(tool))
        self.assertEqual(
            capabilities_of(tool),
            frozenset({READ, FILE_WRITE, SHELL, NETWORK, EXTERNAL_SIDE_EFFECT}),
        )

    def test_side_effect_and_capabilities_do_not_contradict_each_other(self):
        """两个字段说的是同一件事，不一致就说明有一处写错了。"""
        for tool in self.registry.list():
            with self.subTest(tool=tool.name):
                declared_read_only = capabilities_of(tool) <= frozenset({READ})
                self.assertEqual(
                    declared_read_only, not tool.side_effect,
                    f"{tool.name}: side_effect={tool.side_effect} 与声明的能力对不上",
                )

    def test_undeclared_tool_is_high_risk(self):
        tool = _UndeclaredTool()
        self.assertFalse(is_declared(tool))
        self.assertEqual(risk_of(tool), "high")
        self.assertFalse(is_read_only(tool), "没写能力不能当成只读")

    def test_a_capability_string_is_read_as_one_name_not_as_characters(self):
        tool = _MysteryWithStringCapability()
        self.assertEqual(capabilities_of(tool), frozenset({"read"}))
        self.assertTrue(is_declared(tool))

    def test_an_unknown_capability_name_is_high_risk(self):
        class FutureTool:
            name = "Future"
            side_effect = True
            parameters = {}
            capabilities = frozenset({"filesystem_write"})  # 拼错的/未来的名字

        self.assertFalse(is_declared(FutureTool()))
        self.assertEqual(risk_of(FutureTool()), "high")

    def test_mcp_tools_declare_network_and_external_side_effects(self):
        """MCP 工具在另一个进程里执行、调用要出网，而且我们看不到它做了什么。"""
        from huicode.mcp.tools import MCPToolAdapter

        adapter = MCPToolAdapter(
            server_name="demo", remote_name="do_thing", name="mcp__demo__do_thing",
            description="远程工具", parameters={"type": "object"}, session=None,  # type: ignore[arg-type]
        )
        self.assertTrue(is_declared(adapter))
        self.assertEqual(capabilities_of(adapter), frozenset({NETWORK, EXTERNAL_SIDE_EFFECT}))
        self.assertEqual(risk_of(adapter), "high")

    def test_summary_lists_capabilities_in_a_stable_order(self):
        info = summarise(self.registry.get("Bash"))
        self.assertTrue(info["declared"])
        self.assertEqual(info["risk"], "high")
        self.assertEqual(info["capabilities"], sorted(info["capabilities"]))


class SnapshotTests(unittest.TestCase):
    def test_an_unknown_permission_mode_falls_back_to_strict(self):
        """fail closed：认不出的模式按最严格的来，而不是按默认的来。"""
        snapshot = PermissionSnapshot(
            workspace=Path("."), allowed_tool_names=frozenset(), mode="yolo"  # type: ignore[arg-type]
        )
        self.assertEqual(snapshot.mode, "strict")
        self.assertIn(snapshot.mode, PERMISSION_MODES)

    def test_collections_are_frozen_into_tuples_and_frozensets(self):
        snapshot = PermissionSnapshot(
            workspace=Path("."),
            allowed_tool_names={"Read"},  # type: ignore[arg-type]
            rules=[PermissionRule("Read", "*", "allow")],  # type: ignore[arg-type]
        )
        self.assertIsInstance(snapshot.allowed_tool_names, frozenset)
        self.assertIsInstance(snapshot.rules, tuple)


class _BridgeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name).resolve()
        (self.workspace / "demo.txt").write_text("hello", encoding="utf-8")
        self.registry = _registry(_UndeclaredTool(), _MysteryWithStringCapability())

    def tearDown(self):
        self._tmp.cleanup()

    def snapshot(self, *, tools=None, mode="default", plan_mode=False, rules=()):
        if tools is None:
            tools = {tool.name for tool in self.registry.list()}
        return PermissionSnapshot(
            workspace=self.workspace,
            allowed_tool_names=frozenset(tools),
            mode=mode,
            plan_mode=plan_mode,
            rules=tuple(rules),
        )

    def call(self, name, **arguments) -> ToolCall:
        return ToolCall(id=f"c-{name}", name=name, arguments=arguments)


class ThreePathTests(_BridgeCase):
    """同一个任务在三种权限模式下的三条路径：允许 / 需要审批 / 拒绝。"""

    TASK = (
        ("Read", {"path": "demo.txt"}),
        ("Write", {"path": "out.txt", "content": "x"}),
        ("Bash", {"command": "rm -rf /"}),
    )

    def test_the_same_task_under_each_mode(self):
        strict = evaluate_calls([self.call(n, **a) for n, a in self.TASK], self.registry, self.snapshot(mode="strict"))
        self.assertEqual([o.action for o in strict], ["deny", "deny", "deny"])
        self.assertEqual(strict[0].security_category, CATEGORY_MODE)

        default = evaluate_calls([self.call(n, **a) for n, a in self.TASK], self.registry, self.snapshot(mode="default"))
        # 只读低风险直接放行；写文件需要审批；危险命令被黑名单直接拒。
        self.assertEqual([o.action for o in default], ["allow", "request_approval", "deny"])
        self.assertEqual(default[2].security_category, CATEGORY_DANGEROUS_COMMAND)

        permissive = evaluate_calls([self.call(n, **a) for n, a in self.TASK], self.registry, self.snapshot(mode="permissive"))
        # 放行模式也不放过黑名单——它是独立于模式的一道检查。
        self.assertEqual([o.action for o in permissive], ["allow", "allow", "deny"])

    def test_read_only_shell_command_is_low_risk_even_in_default_mode(self):
        outcome = evaluate_call(
            self.call("Bash", command="dir"), self.registry, self.snapshot(mode="default")
        )
        self.assertEqual(outcome.action, "allow")

    def test_a_write_command_is_not_low_risk(self):
        outcome = evaluate_call(
            self.call("Bash", command="echo hi > out.txt"), self.registry, self.snapshot(mode="default")
        )
        self.assertEqual(outcome.action, "request_approval")


class PlanModeTests(_BridgeCase):
    """C50：Plan Mode 下写入、Shell 和副作用工具都不能执行。"""

    def test_plan_mode_blocks_the_same_task_that_default_mode_allows(self):
        snapshot = self.snapshot(mode="permissive", plan_mode=True)
        outcomes = evaluate_calls(
            [self.call("Read", path="demo.txt"),
             self.call("Write", path="out.txt", content="x"),
             self.call("Bash", command="dir")],
            self.registry,
            snapshot,
        )
        self.assertEqual([o.action for o in outcomes], ["allow", "deny", "deny"])
        self.assertEqual(outcomes[1].security_category, CATEGORY_PLAN_MODE)
        # `dir` 是只读命令，default 模式下会被放行；Plan Mode 按**工具能力**判断，
        # 不看命令内容——因为一条命令的只读性只能靠启发式，而能力是声明出来的。
        self.assertEqual(outcomes[2].security_category, CATEGORY_PLAN_MODE)

    def test_plan_mode_does_not_rescue_an_undeclared_tool(self):
        """没声明能力的工具在 Plan Mode 下不能被当成只读。"""
        outcome = evaluate_call(
            self.call("Mystery"), self.registry, self.snapshot(plan_mode=True)
        )
        self.assertEqual(outcome.action, "deny")
        self.assertEqual(outcome.security_category, CATEGORY_PLAN_MODE)

    def test_plan_mode_does_not_block_system_tools(self):
        """与 CLI 的 `_plan_mode_denial` 保持一致：系统工具不受 Plan Mode 限制。

        注意断言的是"**不是**被 Plan Mode 挡下的"——它仍然要走常规权限判断，
        在这里因为能写文件而需要审批。这正是 CLI 的行为。
        """
        registry = _registry(_SystemTool())
        registry.register(_SystemTool(), system=True)
        outcome = evaluate_call(
            self.call("PlanNote"), registry, self.snapshot(tools={"PlanNote"}, plan_mode=True)
        )
        self.assertNotEqual(outcome.security_category, CATEGORY_PLAN_MODE)
        self.assertEqual(outcome.security_category, CATEGORY_CONFIRMATION)

    def test_a_system_tool_without_write_capability_is_allowed_in_plan_mode(self):
        class PlanReadTool:
            name = "PlanRead"
            description = "只读的系统工具"
            side_effect = False
            parameters = {}
            capabilities = frozenset({READ})

            def run(self, args, context):  # pragma: no cover
                raise AssertionError("不应被执行")

        registry = _registry()
        registry.register(PlanReadTool(), system=True)
        outcome = evaluate_call(
            self.call("PlanRead"), registry, self.snapshot(tools={"PlanRead"}, plan_mode=True)
        )
        self.assertEqual(outcome.action, "allow")


class BypassTests(_BridgeCase):
    """C54：服务端不接受来自请求的权限输入。"""

    def test_a_tool_outside_the_allowed_set_is_denied(self):
        snapshot = self.snapshot(tools={"Read"})
        outcome = evaluate_call(
            self.call("Write", path="out.txt", content="x"), self.registry, snapshot
        )
        self.assertEqual(outcome.action, "deny")
        self.assertEqual(outcome.security_category, CATEGORY_TOOL_NOT_ALLOWED)

    def test_an_empty_allowed_set_denies_everything(self):
        snapshot = self.snapshot(tools=set())
        for name, args in (("Read", {"path": "demo.txt"}), ("Bash", {"command": "dir"})):
            with self.subTest(tool=name):
                self.assertEqual(
                    evaluate_call(self.call(name, **args), self.registry, snapshot).action, "deny"
                )

    def test_an_unknown_tool_is_denied_not_ignored(self):
        outcome = evaluate_call(self.call("Nonexistent"), self.registry, self.snapshot())
        self.assertEqual(outcome.action, "deny")
        self.assertEqual(outcome.security_category, CATEGORY_UNKNOWN_TOOL)

    def test_arguments_cannot_smuggle_a_permission_override(self):
        """模型（或直接构造请求的人）在参数里塞权限开关，不该有任何效果。"""
        smuggled = self.call(
            "Write", path="out.txt", content="x",
            permission_mode="permissive", skip_permissions=True,
            allowed_tools=["*"], plan_mode=False, approved=True,
        )
        baseline = evaluate_call(
            self.call("Write", path="out.txt", content="x"), self.registry, self.snapshot()
        )
        outcome = evaluate_call(smuggled, self.registry, self.snapshot())
        self.assertEqual(outcome.action, baseline.action)
        self.assertEqual(outcome.security_category, baseline.security_category)

    def test_a_caller_supplied_context_cannot_change_the_decision(self):
        """传进来的 ToolContext 只带运行状态；权限部分一律被快照覆盖。"""
        from dataclasses import replace

        from huicode.permissions.base import PermissionContext

        permissive_context = build_tool_context(self.snapshot())
        permissive_context = replace(
            permissive_context,
            permissions=PermissionContext(workspace=self.workspace, mode="permissive"),
        )
        outcome = evaluate_call(
            self.call("Bash", command="rm -rf /"),
            self.registry,
            self.snapshot(mode="strict"),
            context=permissive_context,
        )
        self.assertEqual(outcome.action, "deny")
        self.assertEqual(outcome.security_category, CATEGORY_DANGEROUS_COMMAND)

    def test_allowlist_mode_denies_what_strict_would_deny(self):
        snapshot = self.snapshot(mode="permissive", plan_mode=True)
        outcome = evaluate_call(self.call("Write", path="out.txt", content="x"), self.registry, snapshot)
        self.assertFalse(outcome.allowed)


class ExistingSemanticsTests(_BridgeCase):
    """桥接必须保留 CLI 已有的语义，不能另起一套。"""

    def test_dangerous_commands_are_still_blocked(self):
        """C51：黑名单在服务端继续生效。"""
        for command in ("rm -rf /", "git reset --hard HEAD", "format C:"):
            with self.subTest(command=command):
                outcome = evaluate_call(
                    self.call("Bash", command=command), self.registry, self.snapshot(mode="permissive")
                )
                self.assertEqual(outcome.action, "deny")
                self.assertEqual(outcome.security_category, CATEGORY_DANGEROUS_COMMAND)

    def test_paths_outside_the_workspace_are_rejected(self):
        outcome = evaluate_call(
            self.call("Read", path="../../etc/passwd"), self.registry, self.snapshot(mode="permissive")
        )
        self.assertEqual(outcome.action, "deny")
        self.assertEqual(outcome.security_category, CATEGORY_OUTSIDE_WORKSPACE)

    def test_internal_state_writes_are_rejected(self):
        outcome = evaluate_call(
            self.call("Write", path=".huicode/memory/notes.md", content="x"),
            self.registry,
            self.snapshot(mode="permissive"),
        )
        self.assertEqual(outcome.action, "deny")
        self.assertEqual(outcome.security_category, CATEGORY_INTERNAL_STATE)

    def test_an_explicit_deny_rule_wins_over_permissive_mode(self):
        outcome = evaluate_call(
            self.call("Read", path="demo.txt"),
            self.registry,
            self.snapshot(mode="permissive", rules=[PermissionRule("Read", "*", "deny")]),
        )
        self.assertEqual(outcome.action, "deny")

    def test_an_explicit_allow_rule_lifts_the_undeclared_escalation(self):
        """显式规则是人的决定，优先于"未声明就升级为审批"的默认值。"""
        outcome = evaluate_call(
            self.call("Mystery"),
            self.registry,
            self.snapshot(rules=[PermissionRule("Mystery", "*", "allow")]),
        )
        self.assertEqual(outcome.action, "allow")


class CliParityTests(_BridgeCase):
    """桥接不能自己长出一套语义。同一批调用直接问引擎、和经过桥接问，结论必须一样。

    这是"适配而不是重写"能拿出来的证据：往桥接里偷偷加一条引擎没有的判断
    （或反过来），这里就会红。

    **它证明的边界要说清楚。** 两边用的是同一个引擎、同一份 `PermissionContext`
    （都由 `build_tool_context` 从快照构造），所以它证明的是"桥接在引擎之上没有
    多余判断"。它**不能**证明"CLI 从配置文件加载权限的那条路径与 Web 等价"——
    那需要 T16 接进真实循环之后才有端到端对照。
    """

    SAMPLES = (
        ("Read", {"path": "demo.txt"}),
        ("Write", {"path": "out.txt", "content": "x"}),
        ("Bash", {"command": "dir"}),
        ("Bash", {"command": "echo hi > out.txt"}),
        ("Bash", {"command": "rm -rf /"}),
        ("Read", {"path": "../../etc/passwd"}),
    )

    @staticmethod
    def _cli_action(decision) -> str:
        if decision.allowed and not decision.requires_confirmation:
            return "allow"
        if decision.requires_confirmation and not decision.allowed:
            return "request_approval"
        return "deny"

    def test_the_same_calls_get_the_same_verdict_on_both_paths(self):
        from huicode.permissions.engine import evaluate_permission

        for mode in ("strict", "default", "permissive"):
            snapshot = self.snapshot(mode=mode, plan_mode=False)
            context = build_tool_context(snapshot)
            for name, args in self.SAMPLES:
                with self.subTest(mode=mode, tool=name, args=args):
                    call = self.call(name, **args)
                    cli = evaluate_permission(call, self.registry.get(name), context)
                    web = evaluate_call(call, self.registry, snapshot)
                    self.assertEqual(
                        web.action, self._cli_action(cli),
                        f"{mode} / {name}({args}): CLI={cli.source} Web={web.security_category}",
                    )


class UndeclaredEscalationTests(_BridgeCase):
    def test_an_undeclared_tool_never_takes_the_automatic_allow_path(self):
        outcome = evaluate_call(self.call("Mystery"), self.registry, self.snapshot())
        self.assertEqual(outcome.action, "request_approval")
        self.assertEqual(outcome.security_category, CATEGORY_CAPABILITY_UNDECLARED)
        self.assertEqual(outcome.risk, "high")

    def test_permissive_mode_is_not_overridden_by_the_escalation(self):
        """permissive 是运维明确选择的"放行未匹配规则的调用"，不该被这条架空。"""
        outcome = evaluate_call(self.call("Mystery"), self.registry, self.snapshot(mode="permissive"))
        self.assertEqual(outcome.action, "allow")

    def test_strict_mode_still_denies_rather_than_escalating(self):
        outcome = evaluate_call(self.call("Mystery"), self.registry, self.snapshot(mode="strict"))
        self.assertEqual(outcome.action, "deny")


class EventMappingTests(_BridgeCase):
    """C51：事件只带安全分类，不转发引擎的原始原因（里面会有规则原文）。"""

    def test_allow_produces_no_event(self):
        outcome = evaluate_call(self.call("Read", path="demo.txt"), self.registry, self.snapshot())
        self.assertIsNone(outcome.event_type)

    def test_approval_maps_to_the_approval_event(self):
        outcome = evaluate_call(
            self.call("Write", path="out.txt", content="x"), self.registry, self.snapshot()
        )
        self.assertEqual(outcome.event_type, "tool_approval_requested")
        payload = outcome.to_event_payload()
        self.assertEqual(payload["target"], "out.txt", "审批人必须看到自己在批准什么")
        self.assertEqual(payload["security_category"], "confirmation")

    def test_denial_maps_to_an_error_event_with_a_category(self):
        outcome = evaluate_call(
            self.call("Bash", command="rm -rf /"), self.registry, self.snapshot()
        )
        self.assertEqual(outcome.event_type, "error")
        payload = outcome.to_event_payload()
        self.assertEqual(payload["error_code"], "permission_denied")
        self.assertEqual(payload["security_category"], CATEGORY_DANGEROUS_COMMAND)

    def test_the_payload_never_carries_the_rule_text(self):
        """规则原文是用户的权限配置，事件对工作区所有成员可见。"""
        outcome = evaluate_call(
            self.call("Bash", command="rm -rf /"),
            self.registry,
            self.snapshot(mode="default", rules=[PermissionRule("Bash", "rm*", "deny")]),
        )
        payload = outcome.to_event_payload()
        self.assertNotIn("rm*", str(payload))
        self.assertNotIn("命中权限规则", str(payload))
        self.assertEqual(payload["message"], "命令被安全策略拦截")

    def test_payload_messages_come_only_from_the_category_table(self):
        """载荷里的 message 必须能在分类表里查到——否则就是有人把原始原因漏了进去。"""
        from huicode.server.runtime.permission_bridge import CATEGORY_MESSAGES

        calls = [
            self.call("Nonexistent"),
            self.call("Write", path="../../x", content="x"),
            self.call("Bash", command="rm -rf /"),
            self.call("Mystery"),
            self.call("Write", path="out.txt", content="x"),
        ]
        for call in calls:
            with self.subTest(tool=call.name):
                payload = evaluate_call(call, self.registry, self.snapshot()).to_event_payload()
                self.assertIn(payload["message"], CATEGORY_MESSAGES.values())

    def test_event_types_are_known_to_the_event_layer(self):
        """桥接产出的事件名必须真的存在，否则落库时才炸。"""
        from huicode.server.events.types import KNOWN_EVENT_TYPES

        for call in (self.call("Write", path="out.txt", content="x"), self.call("Bash", command="rm -rf /")):
            with self.subTest(tool=call.name):
                event_type = evaluate_call(call, self.registry, self.snapshot()).event_type
                self.assertIsNotNone(event_type)
                self.assertIn(event_type, KNOWN_EVENT_TYPES)


class ScratchWorkspaceTests(unittest.TestCase):
    """默认工作区就是快照里的那个，不需要调用方再传一次。"""

    def test_tool_context_is_built_from_the_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            snapshot = PermissionSnapshot(workspace=workspace, allowed_tool_names=frozenset({"Read"}))
            context = build_tool_context(snapshot)
            self.assertEqual(context.workspace, workspace)
            self.assertIsNotNone(context.permissions)
            self.assertEqual(context.permissions.workspace, workspace)
            self.assertIsNone(context.permissions.confirmer, "服务端不阻塞等用户输入")
            self.assertIsNone(context.permissions.persistent_path, "服务端不写本地 YAML")


if __name__ == "__main__":
    unittest.main()
