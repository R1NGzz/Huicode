from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from huicode.config import WorktreeConfig
from huicode.worktrees.git import GitWorktreeBackend, repository_id_for_workspace
from huicode.worktrees.manager import WorktreeManager
from huicode.worktrees.manifest import write_manifest
from huicode.worktrees.naming import branch_name, resolve_root, task_path
from huicode.worktrees.types import WorktreeIdentity
from huicode.worktrees.types import WorktreeError


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class ExplodingGit:
    def __getattr__(self, name: str):
        raise AssertionError(f"恢复期间不应调用 Git: {name}")


class WorktreeManagerTests(unittest.TestCase):
    def make_repo(self, root: Path) -> None:
        git(root, "init")
        git(root, "config", "user.name", "HuiCode Tests")
        git(root, "config", "user.email", "huicode@example.invalid")
        (root / ".gitignore").write_text(".huicode/\n", encoding="utf-8")
        (root / "tracked.txt").write_text("base", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-m", "base")

    def test_clean_finalize_removes_and_dirty_retains(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repo(root)
            manager = WorktreeManager(root, WorktreeConfig(copy_files=()))
            clean = manager.prepare("task-1234abcd", "review")
            disposition = manager.finalize(clean, "completed")
            self.assertEqual(disposition.state, "removed")
            dirty = manager.prepare("task-deadbeef", "review")
            (dirty.path / "tracked.txt").write_text("changed", encoding="utf-8")
            disposition = manager.finalize(dirty, "completed")
            self.assertEqual(disposition.state, "retained")
            self.assertTrue(disposition.dirty)

    def test_existing_directory_recovery_does_not_call_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config = WorktreeConfig(copy_files=())
            worktree_root = resolve_root(root, config.root)
            path = task_path(worktree_root, "review", "task-1234abcd")
            path.mkdir(parents=True)
            identity = WorktreeIdentity(
                repository_id_for_workspace(root),
                "task-1234abcd",
                "review",
                "a" * 40,
                branch_name("review", "task-1234abcd"),
                path,
                1,
            )
            write_manifest(identity)
            manager = WorktreeManager(root, config, git=ExplodingGit())  # type: ignore[arg-type]
            handle = manager.prepare("task-1234abcd", "review")
            self.assertTrue(handle.recovered)

    def test_initializer_failure_rolls_back_created_worktree(self) -> None:
        class FailingInitializer:
            def initialize(self, identity):  # noqa: ANN001
                raise RuntimeError("init failed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repo(root)
            backend = GitWorktreeBackend(root)
            manager = WorktreeManager(
                root,
                WorktreeConfig(copy_files=()),
                git=backend,
                initializer=FailingInitializer(),  # type: ignore[arg-type]
            )
            with self.assertRaises(WorktreeError):
                manager.prepare("task-1234abcd", "review")
            expected = root / ".huicode" / "worktrees" / "tasks" / "review" / "task-1234abcd"
            self.assertFalse(expected.exists())
            branches = subprocess.run(
                ["git", "branch", "--list", "huicode/worktree/review-1234abcd"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertEqual(branches.strip(), "")

    def test_private_exclude_keeps_manifest_clean_without_global_huicode_ignore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repo(root)
            (root / ".gitignore").write_text(".wt/\n", encoding="utf-8")
            git(root, "add", ".gitignore")
            git(root, "commit", "-m", "custom worktree root")
            manager = WorktreeManager(root, WorktreeConfig(root=".wt", copy_files=()))
            handle = manager.prepare("task-1234abcd", "review")
            self.assertFalse(manager._backend().is_dirty(handle.path))
            self.assertEqual(manager.finalize(handle, "completed").state, "removed")


if __name__ == "__main__":
    unittest.main()
