import unittest

from huicode.prompts import enhance_tool_specs
from huicode.providers.base import ToolSpec


class PromptToolTests(unittest.TestCase):
    def test_enhance_tool_specs_keeps_name_and_parameters(self) -> None:
        spec = ToolSpec(name="Read", description="读取文件", parameters={"type": "object"})
        result = enhance_tool_specs([spec])
        self.assertEqual(result[0].name, "Read")
        self.assertEqual(result[0].parameters, {"type": "object"})
        self.assertEqual(spec.description, "读取文件")

    def test_edit_description_contains_read_and_unique_match_rules(self) -> None:
        spec = ToolSpec(name="Edit", description="修改文件", parameters={})
        text = enhance_tool_specs([spec])[0].description
        self.assertIn("编辑前必须先 Read", text)
        self.assertIn("唯一匹配", text)

    def test_bash_description_prefers_specialized_tools_and_workspace_boundary(self) -> None:
        spec = ToolSpec(name="Bash", description="执行命令", parameters={})
        text = enhance_tool_specs([spec])[0].description
        self.assertIn("优先用 Find", text)
        self.assertIn("workspace 边界", text)

    def test_common_rules_are_not_copied_to_every_tool(self) -> None:
        specs = [
            ToolSpec(name="Read", description="读取文件", parameters={}),
            ToolSpec(name="Glob", description="找文件", parameters={}),
        ]
        result = enhance_tool_specs(specs)
        self.assertNotIn("通用规则", result[0].description)
        self.assertNotIn("通用规则", result[1].description)
        self.assertEqual(result[1].description, "找文件")


if __name__ == "__main__":
    unittest.main()
