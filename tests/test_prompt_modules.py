import unittest

from huicode.prompts import PromptInjectionPolicy
from huicode.prompts.modules import FIXED_MODULE_NAMES, fixed_prompt_modules, optional_prompt_modules, render_stable_modules


class PromptModuleTests(unittest.TestCase):
    def test_default_policy_repeats_every_four_iterations(self) -> None:
        self.assertEqual(PromptInjectionPolicy().repeat_every, 4)

    def test_fixed_modules_keep_priority_order(self) -> None:
        modules = fixed_prompt_modules()
        self.assertEqual(tuple(module.name for module in modules), FIXED_MODULE_NAMES)

    def test_modules_render_with_blank_line_separator(self) -> None:
        text = render_stable_modules(fixed_prompt_modules()[:2])
        self.assertIn("\n\n", text)
        self.assertLess(text.index("## 身份"), text.index("## 系统约束"))

    def test_optional_modules_are_empty_by_default(self) -> None:
        self.assertEqual(optional_prompt_modules(), ())

    def test_optional_modules_render_after_fixed_slots(self) -> None:
        modules = optional_prompt_modules(
            custom_instructions="遵循项目约定",
            active_skills=("mew-spec",),
            long_term_memory="用户偏好中文。",
        )
        self.assertEqual(
            [module.name for module in modules],
            ["custom_instructions", "active_skills", "long_term_memory"],
        )


if __name__ == "__main__":
    unittest.main()
