from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

from .manager import TeamManager
from .naming import new_id
from .storage import atomic_write_json
from .types import IntegrationRecord, TeamError, record_dict


class IntegrationManager:
    def __init__(self, manager: TeamManager) -> None:
        self.manager = manager
        self.record: IntegrationRecord | None = None

    def start(self) -> IntegrationRecord:
        team = self.manager._require_team()
        members = self.manager.members()
        branches = tuple(item.branch for item in members if item.status in {"idle", "stopped"} and item.branch)
        if not branches:
            raise TeamError("no_integration_input", "没有可集成的成员分支")
        attempt = new_id("integration")
        worktree = self.manager.worktrees.prepare_integration(team.id, attempt)
        record = IntegrationRecord(attempt, team.id, team.target_branch, self._git("rev-parse", team.target_branch), worktree.branch, str(worktree.path), branches, (), "merging", self._git("rev-parse", "HEAD", cwd=worktree.path))
        self.record = record
        self._save(record)
        merged: list[str] = []
        for branch in branches:
            completed = self._execute("merge", "--no-edit", branch, cwd=worktree.path)
            if completed.returncode != 0:
                record = replace(record, merged_members=tuple(merged), status="conflicted", error=(completed.stderr or completed.stdout).strip()[:800])
                self.record = record
                self._save(record)
                return record
            merged.append(branch)
        for command in self.manager.config.integration_checks:
            completed = subprocess.run(command, cwd=worktree.path, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if completed.returncode != 0:
                record = replace(record, merged_members=tuple(merged), status="aborted", error=f"集成检查失败: {(completed.stderr or completed.stdout).strip()[:800]}")
                self.record = record
                self._save(record)
                return record
        record = replace(record, merged_members=tuple(merged), status="ready")
        self.record = record
        self._save(record)
        return record

    def publish(self) -> IntegrationRecord:
        if self.record is None or self.record.status != "ready":
            raise TeamError("integration_not_ready", "集成结果尚未通过验证")
        current = self._git("rev-parse", self.record.target_branch)
        if current != self.record.expected_target_commit:
            raise TeamError("target_changed", "目标分支已变化，需要重新集成")
        if self._git("status", "--porcelain"):
            raise TeamError("target_dirty", "用户当前工作区存在未提交修改，拒绝发布")
        if self._git("branch", "--show-current") != self.record.target_branch:
            raise TeamError("target_not_checked_out", "目标分支当前未在主工作区检出")
        completed = self._execute("merge", "--ff-only", self.record.integration_branch)
        if completed.returncode != 0:
            raise TeamError("publish_failed", (completed.stderr or completed.stdout).strip()[:800])
        self.record = replace(self.record, status="published")
        self._save(self.record)
        return self.record

    def continue_after_resolution(self) -> IntegrationRecord:
        if self.record is None or self.record.status != "conflicted":
            raise TeamError("integration_not_conflicted", "当前集成不在冲突状态")
        path = Path(self.record.worktree_path).resolve()
        if path == self.manager.workspace.resolve():
            raise TeamError("integration_boundary", "拒绝在用户主工作区恢复集成")
        if self._git("diff", "--name-only", "--diff-filter=U", cwd=path):
            raise TeamError("conflict_unresolved", "仍有未解决的冲突文件")
        if self._git("status", "--porcelain", cwd=path):
            raise TeamError("resolver_not_committed", "Resolver 必须先提交冲突解决结果")
        merged = list(self.record.merged_members)
        conflict_index = len(merged)
        if conflict_index < len(self.record.member_branches):
            merged.append(self.record.member_branches[conflict_index])
        record = replace(self.record, merged_members=tuple(merged), status="merging", error="")
        for branch in self.record.member_branches[len(merged):]:
            completed = self._execute("merge", "--no-edit", branch, cwd=path)
            if completed.returncode != 0:
                record = replace(record, merged_members=tuple(merged), status="conflicted", error=(completed.stderr or completed.stdout).strip()[:800])
                self.record = record; self._save(record); return record
            merged.append(branch)
        for command in self.manager.config.integration_checks:
            completed = subprocess.run(command, cwd=path, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if completed.returncode != 0:
                record = replace(record, merged_members=tuple(merged), status="aborted", error=f"集成检查失败: {(completed.stderr or completed.stdout).strip()[:800]}")
                self.record = record; self._save(record); return record
        self.record = replace(record, merged_members=tuple(merged), status="ready")
        self._save(self.record)
        return self.record

    def abort(self) -> IntegrationRecord:
        if self.record is None:
            raise TeamError("no_integration", "当前没有集成任务")
        path = Path(self.record.worktree_path)
        if path.resolve() == self.manager.workspace.resolve():
            raise TeamError("integration_boundary", "拒绝在用户主工作区中止集成")
        self._execute("merge", "--abort", cwd=path)
        reset = self._execute("reset", "--hard", self.record.pre_attempt_commit, cwd=path)
        if reset.returncode != 0:
            raise TeamError("integration_abort_failed", (reset.stderr or reset.stdout).strip()[:800])
        self.record = replace(self.record, status="aborted")
        self._save(self.record)
        return self.record

    def _save(self, record: IntegrationRecord) -> None:
        store = self.manager._require_store()
        atomic_write_json(store.paths.integration, {"version": 1, "integration": record_dict(record)})

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        completed = self._execute(*args, cwd=cwd)
        if completed.returncode != 0:
            raise TeamError("git_failed", (completed.stderr or completed.stdout).strip()[:800])
        return completed.stdout.strip()

    def _execute(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=cwd or self.manager.workspace, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
