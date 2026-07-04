import tempfile
import unittest
from pathlib import Path

from huicode.tools.base import ToolContext
from huicode.tools.search import FindFilesTool, SearchCodeTool


class SearchToolTests(unittest.TestCase):
    def test_find_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "pkg").mkdir()
            (workspace / "pkg" / "a.py").write_text("print('a')", encoding="utf-8")
            (workspace / "pkg" / "b.txt").write_text("b", encoding="utf-8")

            result = FindFilesTool().run({"pattern": "*.py"}, ToolContext(workspace=workspace))

        self.assertTrue(result.ok)
        self.assertEqual(result.data["matches"], ["pkg/a.py"])

    def test_search_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "a.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
            (workspace / "b.txt").write_text("hello text\n", encoding="utf-8")

            result = SearchCodeTool().run({"pattern": "hello", "glob": "*.py"}, ToolContext(workspace=workspace))

        self.assertTrue(result.ok)
        self.assertEqual(result.data["count"], 1)
        self.assertEqual(result.data["matches"][0]["path"], "a.py")
        self.assertEqual(result.data["matches"][0]["line"], 1)

    def test_search_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "a.py").write_text("x = 1\n", encoding="utf-8")

            result = SearchCodeTool().run({"pattern": "missing"}, ToolContext(workspace=workspace))

        self.assertTrue(result.ok)
        self.assertEqual(result.data["matches"], [])


if __name__ == "__main__":
    unittest.main()
