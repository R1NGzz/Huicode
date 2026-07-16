from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from huicode.config import MemoryConfig
from huicode.workspaces import WorkspaceContextLoader


class WorkspaceContextLoaderTests(unittest.TestCase):
    def test_absolute_workspace_keys_do_not_cross_contaminate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "one"
            second = root / "two"
            first.mkdir()
            second.mkdir()
            (first / "HUICODE.md").write_text("FIRST", encoding="utf-8")
            (second / "HUICODE.md").write_text("SECOND", encoding="utf-8")
            loader = WorkspaceContextLoader(MemoryConfig())
            self.assertIn("FIRST", loader.load(first).instructions)
            self.assertIn("SECOND", loader.load(second).instructions)
            (first / "HUICODE.md").write_text("FIRST-UPDATED", encoding="utf-8")
            self.assertIn("FIRST-UPDATED", loader.load(first).instructions)
            self.assertNotIn("FIRST", loader.load(second).instructions)


if __name__ == "__main__":
    unittest.main()
