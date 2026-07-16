from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from huicode.worktrees.git import GitWorktreeBackend


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


class WorktreeGitTests(unittest.TestCase):
    def make_repo(self, root: Path) -> None:
        git(root, "init")
        git(root, "config", "user.name", "HuiCode Tests")
        git(root, "config", "user.email", "huicode@example.invalid")
        (root / ".gitignore").write_text(".huicode/\n", encoding="utf-8")
        (root / "tracked.txt").write_text("base", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-m", "base")

    def test_create_dirty_unpushed_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repo(root)
            backend = GitWorktreeBackend(root)
            target = root / ".huicode" / "worktrees" / "tasks" / "role" / "task-1234abcd"
            base = backend.head()
            self.assertTrue(backend.is_ignored(target.parent))
            backend.create(target, "huicode/worktree/role-1234abcd", base)
            self.assertFalse(backend.is_dirty(target))
            (target / "tracked.txt").write_text("changed", encoding="utf-8")
            self.assertTrue(backend.is_dirty(target))
            git(target, "add", "tracked.txt")
            git(target, "commit", "-m", "change")
            self.assertFalse(backend.is_dirty(target))
            self.assertTrue(backend.has_unpushed(target, base))
            backend.remove(target, "huicode/worktree/role-1234abcd")
            self.assertFalse(target.exists())

    def test_upstream_ahead_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            container = Path(directory)
            remote = container / "remote.git"
            root = container / "repo"
            remote.mkdir()
            root.mkdir()
            git(remote, "init", "--bare")
            self.make_repo(root)
            git(root, "remote", "add", "origin", str(remote))
            backend = GitWorktreeBackend(root)
            target = root / ".huicode" / "worktrees" / "tasks" / "role" / "task-deadbeef"
            base = backend.head()
            branch = "huicode/worktree/role-deadbeef"
            backend.create(target, branch, base)
            git(target, "push", "-u", "origin", branch)
            self.assertFalse(backend.has_unpushed(target, base))
            (target / "tracked.txt").write_text("ahead", encoding="utf-8")
            git(target, "add", "tracked.txt")
            git(target, "commit", "-m", "ahead")
            self.assertTrue(backend.has_unpushed(target, base))
            git(target, "push")
            self.assertFalse(backend.has_unpushed(target, base))
            backend.remove(target, branch)


if __name__ == "__main__":
    unittest.main()
