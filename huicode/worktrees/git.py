from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from .types import WorktreeError


class GitWorktreeBackend:
    def __init__(self, workspace: Path, timeout_seconds: int = 30) -> None:
        self.workspace = workspace.resolve()
        self.timeout_seconds = timeout_seconds
        self.repository_root = Path(self._run("rev-parse", "--show-toplevel")).resolve()
        common = Path(self._run("rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = (self.workspace / common).resolve()
        self.git_common_dir = common
        self.repository_id = repository_id_for_workspace(self.repository_root)

    def head(self, cwd: Path | None = None) -> str:
        return self._run("rev-parse", "HEAD", cwd=cwd)

    def create(self, path: Path, branch: str, base_commit: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._run("worktree", "add", "-b", branch, str(path), base_commit)

    def is_ignored(self, path: Path) -> bool:
        completed = self._execute("check-ignore", "-q", "--no-index", str(path))
        if completed.returncode not in {0, 1}:
            detail = (completed.stderr or completed.stdout).strip()
            raise WorktreeError("git_failed", f"Git 无法检查 Worktree 忽略规则: {detail[:800]}")
        return completed.returncode == 0

    def configure_hooks(self, path: Path, hooks_path: Path) -> None:
        self.enable_worktree_config()
        self._run("config", "--worktree", "core.hooksPath", str(hooks_path), cwd=path)

    def configure_excludes(self, path: Path, excludes_path: Path) -> None:
        self.enable_worktree_config()
        self._run("config", "--worktree", "core.excludesFile", str(excludes_path), cwd=path)

    def enable_worktree_config(self) -> None:
        self._run("config", "extensions.worktreeConfig", "true")

    def is_dirty(self, path: Path) -> bool:
        return bool(self._run("status", "--porcelain", "--untracked-files=all", cwd=path))

    def has_unpushed(self, path: Path, base_commit: str) -> bool:
        upstream = self._try_run("rev-parse", "--abbrev-ref", "@{upstream}", cwd=path)
        revision_range = f"{upstream}..HEAD" if upstream else f"{base_commit}..HEAD"
        output = self._run("rev-list", "--count", revision_range, cwd=path)
        try:
            return int(output) > 0
        except ValueError as exc:
            raise WorktreeError("git_output", "Git 返回了无法识别的提交计数") from exc

    def remove(self, path: Path, branch: str) -> None:
        self._run("worktree", "remove", str(path))
        self._run("branch", "-D", branch)

    def rollback_create(self, path: Path, branch: str) -> str:
        errors: list[str] = []
        try:
            self._run("worktree", "remove", "--force", str(path))
        except WorktreeError as exc:
            errors.append(str(exc))
        try:
            self._run("branch", "-D", branch)
        except WorktreeError as exc:
            errors.append(str(exc))
        return "; ".join(errors)

    def _try_run(self, *args: str, cwd: Path | None = None) -> str:
        try:
            return self._run(*args, cwd=cwd)
        except WorktreeError:
            return ""

    def _run(self, *args: str, cwd: Path | None = None) -> str:
        completed = self._execute(*args, cwd=cwd)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise WorktreeError(
                "git_failed",
                f"Git 操作失败 ({' '.join(args[:2])}): {detail[:800]}",
            )
        return completed.stdout.strip()

    def _execute(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        command = ["git", *args]
        try:
            completed = subprocess.run(
                command,
                cwd=str((cwd or self.workspace).resolve()),
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise WorktreeError("git_missing", "未找到 Git 可执行程序") from exc
        except subprocess.TimeoutExpired as exc:
            raise WorktreeError("git_timeout", f"Git 操作超时: {' '.join(args[:2])}") from exc
        except OSError as exc:
            raise WorktreeError("git_failed", f"无法执行 Git: {exc}") from exc
        return completed


def repository_id_for_workspace(workspace: Path) -> str:
    normalized = str(workspace.resolve()).replace("\\", "/")
    if os.name == "nt":
        normalized = normalized.casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
