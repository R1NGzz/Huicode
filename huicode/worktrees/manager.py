from __future__ import annotations

import time
import threading
from dataclasses import replace
from pathlib import Path

from huicode.config import WorktreeConfig

from .git import GitWorktreeBackend, repository_id_for_workspace
from .initializer import WorktreeInitializer
from .manifest import read_manifest, require_matching_manifest
from .naming import branch_name, resolve_root, task_path, validate_logical_name
from .types import WorktreeDisposition, WorktreeError, WorktreeHandle, WorktreeIdentity


class WorktreeManager:
    def __init__(
        self,
        workspace: Path,
        config: WorktreeConfig,
        *,
        git: GitWorktreeBackend | None = None,
        initializer: WorktreeInitializer | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.config = config
        self.git = git
        self.root = resolve_root(self.workspace, config.root)
        self.initializer = initializer
        self._entered: set[str] = set()
        self._lock = threading.RLock()

    def prepare(self, task_id: str, logical_name: str) -> WorktreeHandle:
        validate_logical_name(logical_name)
        path = task_path(self.root, logical_name, task_id)
        branch = branch_name(logical_name, task_id)
        if path.exists():
            actual = read_manifest(path)
            expected = WorktreeIdentity(
                repository_id=repository_id_for_workspace(self.workspace),
                task_id=task_id,
                logical_name=logical_name,
                base_commit=actual.base_commit,
                branch=branch,
                path=path,
                created_at=actual.created_at,
            )
            matched = require_matching_manifest(expected)
            return WorktreeHandle(matched, recovered=True)
        git = self._backend()
        if not git.is_ignored(self.root / ".huicode-ignore-probe"):
            raise WorktreeError(
                "root_not_ignored",
                f"Worktree 根目录未被 Git 忽略: {self.root}",
            )
        base = git.head()
        identity = WorktreeIdentity(
            repository_id=git.repository_id,
            task_id=task_id,
            logical_name=logical_name,
            base_commit=base,
            branch=branch,
            path=path,
            created_at=time.time(),
        )
        git.create(path, branch, base)
        try:
            initializer = self.initializer or WorktreeInitializer(self.workspace, self.config, git)
            initializer.initialize(identity)
        except Exception as exc:
            rollback_error = git.rollback_create(path, branch)
            suffix = f"；回滚失败: {rollback_error}" if rollback_error else ""
            raise WorktreeError("initialize_failed", f"Worktree 环境初始化失败: {exc}{suffix}") from exc
        return WorktreeHandle(identity)

    def enter(self, handle: WorktreeHandle) -> Path:
        self._validate_for_delete(handle)
        with self._lock:
            self._entered.add(handle.identity.task_id)
        return handle.path

    def exit(self, handle: WorktreeHandle) -> None:
        with self._lock:
            self._entered.discard(handle.identity.task_id)

    def finalize(self, handle: WorktreeHandle, task_status: str) -> WorktreeDisposition:
        if task_status != "completed":
            reason = f"任务状态为 {task_status}，保留隔离目录"
            self._mark_terminal(handle, task_status, reason)
            return WorktreeDisposition("retained", reason)
        self._mark_terminal(handle, "completed", "等待变更保护检查")
        return self.remove(handle)

    def remove(self, handle: WorktreeHandle) -> WorktreeDisposition:
        self._validate_for_delete(handle)
        git = self._backend()
        dirty = git.is_dirty(handle.path)
        if dirty:
            self._mark_terminal(handle, "completed", "存在未提交修改")
            return WorktreeDisposition("retained", "存在未提交修改", dirty=True)
        unpushed = git.has_unpushed(handle.path, handle.identity.base_commit)
        if unpushed:
            self._mark_terminal(handle, "completed", "存在未推送提交")
            return WorktreeDisposition("retained", "存在未推送提交", unpushed=True)
        git.remove(handle.path, handle.branch)
        self._remove_empty_parents(handle.path.parent)
        return WorktreeDisposition("removed", "任务成功且工作目录干净")

    def _validate_for_delete(self, handle: WorktreeHandle) -> None:
        try:
            handle.path.resolve().relative_to(self.root.resolve())
        except ValueError as exc:
            raise WorktreeError("delete_escape", "拒绝删除专用根目录外的 Worktree") from exc
        require_matching_manifest(handle.identity)

    def _remove_empty_parents(self, current: Path) -> None:
        tasks_root = self.root / "tasks"
        while current != tasks_root and current != self.root:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    def _mark_terminal(self, handle: WorktreeHandle, status: str, reason: str) -> None:
        current = require_matching_manifest(handle.identity)
        from .manifest import write_manifest

        write_manifest(replace(current, terminal_status=status, retained_reason=reason))

    def close(self) -> None:
        return None

    def _backend(self) -> GitWorktreeBackend:
        if self.git is None:
            self.git = GitWorktreeBackend(self.workspace)
        if self.git.repository_root != self.workspace:
            raise WorktreeError("repository_root", "HuiCode 必须从 Git 仓库根目录启动 Worktree 隔离")
        return self.git
