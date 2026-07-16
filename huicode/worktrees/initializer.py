from __future__ import annotations

import glob
import shutil
from pathlib import Path

from huicode.config import WorktreeConfig

from .git import GitWorktreeBackend
from .manifest import write_manifest
from .types import WorktreeError, WorktreeIdentity


class WorktreeInitializer:
    def __init__(
        self,
        workspace: Path,
        config: WorktreeConfig,
        git: GitWorktreeBackend,
    ) -> None:
        self.workspace = workspace.resolve()
        self.config = config
        self.git = git

    def initialize(self, identity: WorktreeIdentity) -> None:
        exclude_file = identity.path / ".huicode" / "worktree.exclude"
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        exclude_file.write_text(
            ".huicode/worktree.json\n.huicode/worktree.exclude\n",
            encoding="utf-8",
        )
        self.git.configure_excludes(identity.path, exclude_file)
        for configured in self.config.copy_files:
            source = self._source(configured)
            if source.exists():
                self._copy(source, self._target(identity.path, configured))
        for pattern in self.config.restore_ignored:
            self._restore_pattern(pattern, identity.path)
        for configured in self.config.symlink_directories:
            source = self._source(configured)
            if not source.is_dir():
                raise WorktreeError("link_source", f"依赖链接来源不是目录: {configured}")
            target = self._target(identity.path, configured)
            if target.exists() or target.is_symlink():
                raise WorktreeError("link_target", f"依赖链接目标已存在: {configured}")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.symlink_to(source, target_is_directory=True)
            except OSError as exc:
                raise WorktreeError("link_failed", f"无法创建依赖目录链接 {configured}: {exc}") from exc
        if self.config.hooks_path:
            hooks = self._source(self.config.hooks_path)
            if not hooks.is_dir():
                raise WorktreeError("hooks_missing", f"Git Hooks 目录不存在: {self.config.hooks_path}")
            self.git.configure_hooks(identity.path, hooks)
        write_manifest(identity)

    def _restore_pattern(self, pattern: str, target_root: Path) -> None:
        raw = self.workspace / pattern
        matches = [Path(item) for item in glob.glob(str(raw), recursive=True)]
        for source in matches:
            resolved = self._inside(source.resolve(), self.workspace, "恢复文件来源越过主工作区")
            relative = resolved.relative_to(self.workspace)
            self._copy(resolved, self._target(target_root, relative.as_posix()))

    def _copy(self, source: Path, target: Path) -> None:
        if target.exists() or target.is_symlink():
            raise WorktreeError("init_target_exists", f"初始化目标已存在: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)

    def _source(self, configured: str) -> Path:
        raw = Path(configured)
        if raw.is_absolute() or raw.drive:
            raise WorktreeError("init_path", f"初始化来源必须是相对路径: {configured}")
        return self._inside((self.workspace / raw).resolve(), self.workspace, "初始化来源越过主工作区")

    def _target(self, root: Path, configured: str) -> Path:
        raw = Path(configured)
        if raw.is_absolute() or raw.drive:
            raise WorktreeError("init_path", f"初始化目标必须是相对路径: {configured}")
        return self._inside((root / raw).resolve(), root.resolve(), "初始化目标越过 Worktree")

    @staticmethod
    def _inside(path: Path, boundary: Path, message: str) -> Path:
        try:
            path.relative_to(boundary.resolve())
        except ValueError as exc:
            raise WorktreeError("path_escape", message) from exc
        return path
