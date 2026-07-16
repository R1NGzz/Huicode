from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from huicode.worktrees.naming import branch_name, resolve_root, task_path, validate_logical_name
from huicode.worktrees.types import WorktreeError


class WorktreeNamingTests(unittest.TestCase):
    def test_accepts_safe_nested_name(self) -> None:
        self.assertEqual(validate_logical_name("review/api_v2"), ("review", "api_v2"))
        self.assertEqual(
            branch_name("review/api_v2", "task-1234abcd"),
            "huicode/worktree/review-api_v2-1234abcd",
        )

    def test_rejects_unsafe_names(self) -> None:
        invalid = ["", ".", "..", "a/../b", "/abs", "C:/temp", "a\\b", "a//b", "a b"]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(WorktreeError):
                validate_logical_name(value)

    def test_resolved_paths_stay_inside_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = resolve_root(workspace, ".huicode/worktrees")
            path = task_path(root, "review/api", "task-1234abcd")
            path.relative_to(root)
            with self.assertRaises(WorktreeError):
                resolve_root(workspace, "../outside")


if __name__ == "__main__":
    unittest.main()
