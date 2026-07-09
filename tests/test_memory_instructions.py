import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huicode.config import MemoryConfig
from huicode.memory.instructions import InstructionLoader


class MemoryInstructionTests(unittest.TestCase):
    def test_loads_project_before_user_and_expands_include(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            workspace = root / "work"
            (home / "memory").mkdir(parents=True)
            (workspace / ".huicode").mkdir(parents=True)
            (home / "instructions.md").write_text("用户偏好", encoding="utf-8")
            (workspace / ".huicode" / "extra.md").write_text("项目补充", encoding="utf-8")
            (workspace / ".huicode" / "instructions.md").write_text(
                "项目规则\n@include extra.md",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"HUICODE_HOME": str(home)}):
                result = InstructionLoader(workspace, MemoryConfig(enabled=True)).load()

        self.assertIn("project_instructions", result.text)
        self.assertLess(result.text.index("项目规则"), result.text.index("用户偏好"))
        self.assertIn("项目补充", result.text)
        self.assertFalse(result.warnings)

    def test_include_safety_reports_loop_depth_and_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "work"
            home = Path(directory) / "home"
            (workspace / ".huicode").mkdir(parents=True)
            (home).mkdir(parents=True)
            (Path(directory) / "secret.md").write_text("outside", encoding="utf-8")
            (workspace / ".huicode" / "a.md").write_text("@include b.md", encoding="utf-8")
            (workspace / ".huicode" / "b.md").write_text("@include a.md", encoding="utf-8")
            (workspace / ".huicode" / "instructions.md").write_text(
                "\n".join(["@include a.md", "@include ../../secret.md", "@include missing.md"]),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"HUICODE_HOME": str(home)}):
                result = InstructionLoader(
                    workspace,
                    MemoryConfig(enabled=True, instruction_include_depth=2),
                ).load()

        self.assertNotIn("outside", result.text)
        warning_text = "\n".join(result.warnings)
        self.assertIn("循环", warning_text)
        self.assertIn("越过边界", warning_text)
        self.assertIn("不存在", warning_text)


if __name__ == "__main__":
    unittest.main()
