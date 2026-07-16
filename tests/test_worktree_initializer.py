from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from huicode.config import WorktreeConfig
from huicode.worktrees.initializer import WorktreeInitializer
from huicode.worktrees.manifest import manifest_path
from huicode.worktrees.types import WorktreeIdentity


class FakeGit:
    def __init__(self) -> None:
        self.hooks = None
        self.excludes = None

    def configure_hooks(self, path: Path, hooks: Path) -> None:
        self.hooks = (path, hooks)

    def configure_excludes(self, path: Path, excludes: Path) -> None:
        self.excludes = (path, excludes)


class WorktreeInitializerTests(unittest.TestCase):
    def test_copies_restores_links_and_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "huicode.yaml").write_text("model: test", encoding="utf-8")
            (source / "runtime").mkdir()
            (source / "runtime" / "data.bin").write_bytes(b"data")
            (source / "node_modules").mkdir()
            (source / "hooks").mkdir()
            config = WorktreeConfig(
                copy_files=("huicode.yaml",),
                restore_ignored=("runtime/*.bin",),
                symlink_directories=("node_modules",),
                hooks_path="hooks",
            )
            fake = FakeGit()
            identity = WorktreeIdentity("repo", "task-1234abcd", "role", "a" * 40, "branch", target, 1)
            WorktreeInitializer(source, config, fake).initialize(identity)  # type: ignore[arg-type]
            self.assertEqual((target / "huicode.yaml").read_text(encoding="utf-8"), "model: test")
            self.assertEqual((target / "runtime" / "data.bin").read_bytes(), b"data")
            self.assertTrue((target / "node_modules").is_symlink())
            self.assertEqual(fake.hooks, (target, (source / "hooks").resolve()))
            self.assertEqual(fake.excludes, (target, target / ".huicode" / "worktree.exclude"))
            self.assertTrue(manifest_path(target).exists())


if __name__ == "__main__":
    unittest.main()
