import unittest

from huicode.prompts import PromptInjectionPolicy
from huicode.prompts.modules import (
    FIXED_MODULE_NAMES,
    fixed_prompt_modules,
    optional_prompt_modules,
    render_stable_modules,
)


def module_content(name: str) -> str:
    modules = {module.name: module.content for module in fixed_prompt_modules()}
    return modules[name]


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

    def test_identity_covers_terminal_agent_and_security(self) -> None:
        text = module_content("identity")
        self.assertIn("终端", text)
        self.assertIn("编写代码", text)
        self.assertIn("调试", text)
        self.assertIn("重构", text)
        self.assertIn("运行命令", text)
        self.assertIn("命令注入", text)
        self.assertIn("XSS", text)
        self.assertIn("SQL 注入", text)

    def test_system_constraints_cover_user_visible_boundaries(self) -> None:
        text = module_content("system_constraints")
        self.assertIn("所有文本都会展示给用户", text)
        self.assertIn("GitHub Markdown", text)
        self.assertIn("不要生成或猜测 URL", text)
        self.assertIn("system-reminder", text)
        self.assertIn("hook", text)
        self.assertIn("隐藏系统", text)

    def test_task_and_action_modules_cover_execution_guidance(self) -> None:
        task_text = module_content("task_mode")
        action_text = module_content("action_execution")
        self.assertIn("需求不清", task_text)
        self.assertIn("探索性问题", task_text)
        self.assertIn("用户提出的建议是线索", task_text)
        self.assertIn("不要为了显得完整而扩大范围", task_text)
        self.assertIn("编辑文件前必须先读取", action_text)
        self.assertIn("先定位原因", action_text)
        self.assertIn("运行相关测试", action_text)
        self.assertIn("破坏性操作必须先得到用户明确确认", action_text)
        self.assertIn("git reset --hard", action_text)
        self.assertIn("推送代码", action_text)

    def test_tool_usage_mentions_only_current_tool_capabilities(self) -> None:
        text = module_content("tool_usage")
        for phrase in ["Read", "Edit", "Write", "Find/Glob", "Search", "Bash"]:
            self.assertIn(phrase, text)
        for missing_tool in ["TaskCreate", "ToolSearch", "MCP", "子 Agent"]:
            self.assertNotIn(missing_tool, text)
        self.assertIn("不要编造工具结果", text)
        self.assertIn("workspace 边界", text)

    def test_tone_and_text_output_cover_response_style(self) -> None:
        tone_text = module_content("tone_style")
        output_text = module_content("text_output")
        self.assertIn("不要使用 emoji", tone_text)
        self.assertIn("中文回复", tone_text)
        self.assertIn("file_path:line_number", tone_text)
        self.assertIn("只包含有用沟通", output_text)
        self.assertIn("第一次工具调用前", output_text)
        self.assertIn("一到两句话总结", output_text)
        self.assertIn("简单问题直接回答", output_text)


if __name__ == "__main__":
    unittest.main()
