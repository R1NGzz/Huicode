from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from huicode.config import WorktreeConfig
from huicode.worktrees.cleanup import WorktreeCleanupService
from huicode.worktrees.manifest import write_manifest
from huicode.worktrees.types import WorktreeDisposition, WorktreeIdentity


class FakeGit:
    repository_id = "repo"


class FakeManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = WorktreeConfig(stale_after_days=1, copy_files=())
        self.git = FakeGit()
        self.removed = []

    def _backend(self):
        return self.git

    def remove(self, handle):  # noqa: ANN001
        self.removed.append(handle.path)
        return WorktreeDisposition("removed", "clean")


class WorktreeCleanupTests(unittest.TestCase):
    def test_only_expired_matching_manifest_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = FakeManager(root)
            old = root / "tasks" / "role" / "task-1234abcd"
            fresh = root / "tasks" / "role" / "task-deadbeef"
            old.mkdir(parents=True)
            fresh.mkdir(parents=True)
            write_manifest(WorktreeIdentity("repo", "task-1234abcd", "role", "a" * 40, "old", old, time.time() - 172800))
            write_manifest(WorktreeIdentity("repo", "task-deadbeef", "role", "a" * 40, "new", fresh, time.time()))
            records = WorktreeCleanupService(manager).scan_once()
        self.assertEqual(manager.removed, [old.resolve()])
        self.assertEqual({record.state for record in records}, {"removed", "skipped"})

    def test_failed_terminal_status_is_never_auto_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = FakeManager(root)
            failed = root / "tasks" / "role" / "task-1234abcd"
            failed.mkdir(parents=True)
            write_manifest(
                WorktreeIdentity(
                    "repo",
                    "task-1234abcd",
                    "role",
                    "a" * 40,
                    "failed",
                    failed,
                    time.time() - 172800,
                    terminal_status="failed",
                    retained_reason="任务失败",
                )
            )
            records = WorktreeCleanupService(manager).scan_once()
        self.assertEqual(manager.removed, [])
        self.assertEqual(records[0].state, "retained")

    def test_symlink_escape_is_not_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(directory)
            outside = Path(outside_dir)
            manager = FakeManager(root)
            target = outside / "escaped"
            target.mkdir()
            write_manifest(WorktreeIdentity("repo", "task-1234abcd", "role", "a" * 40, "branch", target, 1))
            link = root / "tasks" / "escaped"
            link.parent.mkdir(parents=True)
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"当前平台无法创建目录链接: {exc}")
            WorktreeCleanupService(manager).scan_once()
        self.assertEqual(manager.removed, [])

    def test_background_service_closes_promptly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = FakeManager(Path(directory))
            manager.config = WorktreeConfig(
                stale_after_days=1,
                cleanup_interval_seconds=60,
                copy_files=(),
            )
            service = WorktreeCleanupService(manager)
            started = time.monotonic()
            service.start()
            service.close()
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.5)


if __name__ == "__main__":
    unittest.main()
