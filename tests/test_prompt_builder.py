import unittest
from dataclasses import replace
from pathlib import Path

from huicode.prompts import PromptContext, PromptInjectionPolicy, build_prompt_bundle


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
