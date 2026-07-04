import tempfile
import unittest
from pathlib import Path

from huicode.tools.base import ToolContext
from huicode.tools.files import EditFileTool, ReadFileTool, WriteFileTool


class FileToolTests(unittest.TestCase):
    def test_read_and_write_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            context = ToolContext(workspace=workspace)

            write_result = WriteFileTool().run({"path": "notes/a.txt", "content": "你好\n世界"}, context)
            read_result = ReadFileTool().run({"path": "notes/a.txt"}, context)

        self.assertTrue(write_result.ok)
        self.assertTrue(read_result.ok)
        self.assertEqual(read_result.data["content"], "你好\n世界")
        self.assertEqual(read_result.data["lines"], 2)

    def test_rejects_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = ToolContext(workspace=Path(directory))
            result = ReadFileTool().run({"path": "../outside.txt"}, context)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "invalid_request")

    def test_edit_unique_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = workspace / "a.txt"
            path.write_text("alpha beta gamma", encoding="utf-8")

            result = EditFileTool().run(
                {"path": "a.txt", "old_text": "beta", "new_text": "BETA"},
                ToolContext(workspace=workspace),
            )

            self.assertTrue(result.ok)
            self.assertEqual(path.read_text(encoding="utf-8"), "alpha BETA gamma")

    def test_edit_missing_and_multiple_matches_do_not_modify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = workspace / "a.txt"
            path.write_text("one two two", encoding="utf-8")
            context = ToolContext(workspace=workspace)

            missing = EditFileTool().run({"path": "a.txt", "old_text": "three", "new_text": "3"}, context)
            multiple = EditFileTool().run({"path": "a.txt", "old_text": "two", "new_text": "2"}, context)

            self.assertFalse(missing.ok)
            self.assertEqual(missing.error.code, "not_found")
            self.assertFalse(multiple.ok)
            self.assertEqual(multiple.error.code, "multiple_matches")
            self.assertEqual(path.read_text(encoding="utf-8"), "one two two")


if __name__ == "__main__":
    unittest.main()
