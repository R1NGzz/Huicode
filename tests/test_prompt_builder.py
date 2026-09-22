import unittest
from dataclasses import replace
from pathlib import Path

from huicode.prompts import PromptContext, PromptInjectionPolicy, build_prompt_bundle
from huicode.prompts.builder import execution_phase


def make_context(iteration: int = 1, mode: str = "chat") -> PromptContext:
    return PromptContext(
        workspace=Path("C:/work/project"),
        platform="Windows",
        shell="powershell",
        now="2026-07-04T12:00:00+08:00",
        mode=mode,  # type: ignore[arg-type]
        iteration=iteration,
        max_iterations=8,
        available_tools=("Read", "Find", "Search"),
        read_only_tool_names=("Read", "Find", "Search", "Glob"),
        last_plan="先读 README。",
    )


class PromptBuilderTests(unittest.TestCase):
    def test_execution_phase_boundaries_for_long_turns(self) -> None:
        self.assertEqual(execution_phase(9, 50), "investigate")
        self.assertEqual(execution_phase(10, 50), "implement")
        self.assertEqual(execution_phase(30, 50), "implement")
        self.assertEqual(execution_phase(31, 50), "verify")
        self.assertEqual(execution_phase(42, 50), "verify")
        self.assertEqual(execution_phase(43, 50), "finalize")

    def test_interface_closure_keeps_more_budget_for_implementation(self) -> None:
        self.assertEqual(execution_phase(8, 50, interface_closure=True), "implement")
        self.assertEqual(execution_phase(40, 50, interface_closure=True), "implement")
        self.assertEqual(execution_phase(45, 50, interface_closure=True), "verify")
        self.assertEqual(execution_phase(48, 50, interface_closure=True), "finalize")

    def test_short_turns_have_no_execution_progress_module(self) -> None:
        bundle = build_prompt_bundle(make_context(iteration=2))
        self.assertNotIn("execution_progress", bundle.module_names())

    def test_long_turn_has_phase_specific_progress_module(self) -> None:
        bundle = build_prompt_bundle(
            PromptContext(
                **{**make_context(iteration=36).__dict__, "max_iterations": 50}
            )
        )
        module = next(module for module in bundle.dynamic_modules if module.name == "execution_progress")
        self.assertIn("phase: verify", module.content)
        self.assertIn("回归", module.content)

    def test_implementation_phase_has_early_edit_and_test_gate(self) -> None:
        bundle = build_prompt_bundle(
            PromptContext(
                **{**make_context(iteration=10).__dict__, "max_iterations": 50}
            )
        )
        module = next(module for module in bundle.dynamic_modules if module.name == "execution_progress")
        self.assertIn("生产源代码", module.content)
        self.assertIn("Edit 或 Write", module.content)
        self.assertIn("两轮内完成", module.content)
        self.assertIn("声明/锁定版本", module.content)
        self.assertIn("新增可选参数", module.content)
        self.assertIn("不要修改测试文件", module.content)

    def test_execution_discipline_reports_exploration_and_verification_debt(self) -> None:
        context = replace(
            make_context(iteration=12),
            max_iterations=50,
            read_only_tool_calls=6,
            exploration_soft_limit=6,
        )
        bundle = build_prompt_bundle(context)
        module = next(module for module in bundle.dynamic_modules if module.name == "execution_progress")
        self.assertIn("只读探索已达到软上限", module.content)

        context = replace(
            context,
            read_only_tool_calls=0,
            production_edit_count=1,
            last_production_edit_iteration=12,
            last_verification_iteration=0,
        )
        bundle = build_prompt_bundle(context)
        module = next(module for module in bundle.dynamic_modules if module.name == "execution_progress")
        self.assertIn("尚未有成功验证", module.content)

    def test_investigation_phase_has_deadline(self) -> None:
        bundle = build_prompt_bundle(
            PromptContext(
                **{**make_context(iteration=9).__dict__, "max_iterations": 50}
            )
        )
        module = next(module for module in bundle.dynamic_modules if module.name == "execution_progress")
        self.assertIn("第 10 轮", module.content)
        self.assertIn("第一次修改", module.content)

    def test_plan_mode_never_adds_execution_progress_module(self) -> None:
        context = PromptContext(
            **{**make_context(iteration=36, mode="plan").__dict__, "max_iterations": 50}
        )
        bundle = build_prompt_bundle(context)
        self.assertNotIn("execution_progress", bundle.module_names())

    def test_verification_gate_module_lists_paths_and_blocks_finalization(self) -> None:
        context = replace(
            make_context(iteration=12),
            max_iterations=50,
            verification_required=True,
            verification_paths=("src/module.py",),
            verification_status="验证命令失败：目标测试失败",
        )
        bundle = build_prompt_bundle(context)

        self.assertIn("verification_gate", bundle.module_names())
        module = next(module for module in bundle.dynamic_modules if module.name == "verification_gate")
        self.assertIn("src/module.py", module.content)
        self.assertIn("验证命令失败", module.content)
        self.assertIn("只有成功验证后才能结束任务", module.content)

    def test_interface_closure_module_is_explicit_and_compact(self) -> None:
        context = replace(
            make_context(iteration=12),
            max_iterations=50,
            changed_production_paths=("src/tasks/store.py",),
            verification_failures=1,
            last_verification_failure="目标测试退出码为 1",
        )
        bundle = build_prompt_bundle(context, PromptInjectionPolicy(interface_closure=True))

        self.assertIn("interface_closure", bundle.module_names())
        module = next(module for module in bundle.dynamic_modules if module.name == "interface_closure")
        self.assertIn("定义/协议", module.content)
        self.assertIn("factory/handler/直接调用方", module.content)
        self.assertIn("目标测试退出码为 1", module.content)
        self.assertIn("不要为每一个方法单独停下来", module.content)

    def test_scope_audit_adds_contract_and_minimal_diff_guidance(self) -> None:
        context = replace(
            make_context(iteration=42),
            max_iterations=50,
            changed_production_paths=("src/tasks/store.py", "src/tasks/builder.py"),
        )
        bundle = build_prompt_bundle(
            context,
            PromptInjectionPolicy(interface_closure=True, scope_audit=True),
        )

        module = next(module for module in bundle.dynamic_modules if module.name == "interface_closure")
        self.assertIn("参数顺序和仓库既有风格", module.content)
        self.assertIn("变更范围审计", module.content)
        self.assertIn("旁支的辅助 builder", module.content)

    def test_plan_mode_does_not_receive_verification_gate(self) -> None:
        context = replace(
            make_context(iteration=12, mode="plan"),
            max_iterations=50,
            verification_required=True,
            verification_paths=("src/module.py",),
        )
        bundle = build_prompt_bundle(context)
        self.assertNotIn("verification_gate", bundle.module_names())

    def test_hook_instructions_are_dynamic_after_active_skills(self) -> None:
        context = replace(
            make_context(),
            active_skill_blocks=("<skill>review</skill>",),
            hook_instruction_blocks=("<huicode_instruction type=\"hook\">check</huicode_instruction>",),
        )
        bundle = build_prompt_bundle(context)
        names = bundle.module_names()
        self.assertLess(names.index("active_skill_1"), names.index("hook_instruction_1"))
        self.assertLess(names.index("hook_instruction_1"), names.index("environment"))
        hook = next(module for module in bundle.dynamic_modules if module.name == "hook_instruction_1")
        self.assertFalse(hook.stable)
        self.assertFalse(hook.cacheable)

    def test_skill_catalog_is_lightweight_and_active_sop_is_dynamic_first(self) -> None:
        context = replace(
            make_context(),
            active_skill_blocks=(
                '<huicode_instruction type="active_skill">SECRET SOP</huicode_instruction>',
            ),
            skill_catalog=(("review", "Review code", "isolated"),),
        )

        bundle = build_prompt_bundle(context)

        self.assertIn("SECRET SOP", bundle.dynamic_modules[0].content)
        self.assertEqual(bundle.dynamic_modules[1].name, "environment")
        self.assertNotIn("SECRET SOP", bundle.stable_text())
        self.assertIn("review [isolated]: Review code", bundle.supplemental_text())

    def test_environment_uses_special_tag_and_is_dynamic(self) -> None:
        bundle = build_prompt_bundle(make_context())
        self.assertIn('<huicode_context type="environment" scope="turn">', bundle.dynamic_text())
        self.assertIn("workspace: C:/work/project", bundle.dynamic_text())
        self.assertNotIn("now:", bundle.dynamic_text())
        self.assertNotIn("2026-07-04", bundle.stable_text())

    def test_stable_text_does_not_mix_dynamic_tags(self) -> None:
        bundle = build_prompt_bundle(make_context())
        stable_text = bundle.stable_text()
        dynamic_text = bundle.dynamic_text()
        self.assertIn("## 身份", stable_text)
        self.assertIn("## 工具使用", stable_text)
        self.assertNotIn("<huicode_context", stable_text)
        self.assertNotIn("<huicode_instruction", stable_text)
        self.assertNotIn("## 身份", dynamic_text)

    def test_plan_mode_first_iteration_has_full_instruction(self) -> None:
        bundle = build_prompt_bundle(make_context(mode="plan", iteration=1))
        text = bundle.supplemental_text()
        self.assertIn('<huicode_instruction type="plan_mode" scope="turn">', text)
        self.assertIn("只能使用读类工具", text)

    def test_execution_mode_compact_between_repeats(self) -> None:
        bundle = build_prompt_bundle(make_context(mode="do", iteration=2))
        text = bundle.supplemental_text()
        self.assertIn('<huicode_instruction type="execution_mode" scope="turn">', text)
        self.assertIn("最小必要操作", text)
        self.assertNotIn("最近计划摘要", text)

    def test_every_fourth_iteration_repeats_key_constraints(self) -> None:
        bundle = build_prompt_bundle(
            make_context(mode="do", iteration=4),
            PromptInjectionPolicy(repeat_every=4),
        )
        text = bundle.supplemental_text()
        self.assertIn("编辑前必须先读", text)
        self.assertIn("最近计划摘要", text)

    def test_long_plan_is_bounded_and_catalogs_are_periodic(self) -> None:
        policy = PromptInjectionPolicy(
            repeat_every=8,
            catalog_repeat_every=8,
            plan_preview_chars=20,
        )
        context = replace(
            make_context(iteration=1),
            max_iterations=50,
            last_plan="这是一个很长的计划摘要，后面还有许多暂时不需要重复发送的内容。",
            skill_catalog=(("review", "Review code", "isolated"),),
            agent_catalog=(("worker", "Inspect code",),),
        )
        first = build_prompt_bundle(context, policy)
        self.assertIn("review [isolated]: Review code", first.supplemental_text())
        self.assertIn("worker: Inspect code", first.supplemental_text())
        self.assertIn("计划摘要已截断", first.supplemental_text())

        second = build_prompt_bundle(replace(context, iteration=2), policy)
        self.assertNotIn("review [isolated]: Review code", second.supplemental_text())
        self.assertNotIn("worker: Inspect code", second.supplemental_text())
        self.assertIn("目录已在首轮提供", second.supplemental_text())

        eighth = build_prompt_bundle(replace(context, iteration=8), policy)
        self.assertIn("review [isolated]: Review code", eighth.supplemental_text())
        self.assertIn("worker: Inspect code", eighth.supplemental_text())


    def test_memory_index_is_supplemental_not_stable(self) -> None:
        context = make_context()
        context = PromptContext(
            **{
                **context.__dict__,
                "custom_instructions": "项目指令",
                "memory_enabled": True,
                "memory_index": "- [mem-1] 记忆摘要 (source: .huicode/memory/notes/mem-1.md)",
                "memory_warnings": ("include missing",),
            }
        )
        bundle = build_prompt_bundle(context)

        self.assertIn("项目指令", bundle.stable_text())
        self.assertIn("memory_management", bundle.module_names())
        self.assertIn("后台自动维护", bundle.supplemental_text())
        self.assertIn("不需要用户权限确认", bundle.supplemental_text())
        self.assertIn("memory_index", bundle.module_names())
        self.assertIn("记忆摘要", bundle.supplemental_text())
        self.assertIn("include missing", bundle.supplemental_text())
        self.assertNotIn("记忆摘要", bundle.stable_text())


if __name__ == "__main__":
    unittest.main()
