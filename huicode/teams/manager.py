from __future__ import annotations

import queue
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from huicode.config import TeamConfig
from huicode.worktrees import WorktreeManager
from huicode.worktrees.git import repository_id_for_workspace

from .approval import ApprovalGate
from .backends import BackendHandle, CoroutineBackend, MemberBackendSelector, MemberLaunchSpec
from .mailbox import MailboxStore, NameRegistry
from .member_runner import AssignmentExecutor, TeamMemberRunner, unavailable_executor
from .naming import new_id, team_path, validate_name
from .storage import TeamStore, atomic_write_json, read_json
from .tasks import SharedTaskStore
from .terminal_backends import TmuxBackend, WindowsTerminalBackend
from .types import TeamError, TeamEvent, TeamMemberRecord, TeamRecord, record_dict
from .worktrees import TeamWorktree, TeamWorktreeService


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _extract_task_paths(text: str, workspace: Path) -> tuple[str, ...]:
    candidates = re.findall(r"(?<![\w.])([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_+-]+)", text)
    result: list[str] = []
    for candidate in candidates:
        relative = candidate.replace("\\", "/").lstrip("./")
        if not relative or relative in result:
            continue
        target = (workspace / relative).resolve()
        try:
            target.relative_to(workspace.resolve())
        except ValueError:
            continue
        if target.is_file():
            result.append(relative)
    return tuple(result)


def _normalize_task_paths(paths: tuple[str, ...], workspace: Path) -> tuple[str, ...]:
    result: list[str] = []
    root = workspace.resolve()
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            raise TeamError("invalid_task_path", "任务 paths 必须是非空项目相对路径")
        candidate = Path(raw.replace("\\", "/"))
        if candidate.is_absolute():
            raise TeamError("invalid_task_path", f"任务路径必须相对于项目目录: {raw}")
        target = (root / candidate).resolve()
        try:
            relative = target.relative_to(root).as_posix()
        except ValueError as exc:
            raise TeamError("task_path_escape", f"任务路径越出项目目录: {raw}") from exc
        if relative not in result:
            result.append(relative)
    return tuple(result)


class TeamManager:
    def __init__(self, workspace: Path, config: TeamConfig, worktree_manager: WorktreeManager, *, root: Path | None = None, assignment_executor: AssignmentExecutor | None = None, config_path: str = "", agent_catalog=None) -> None:  # noqa: ANN001
        self.workspace = workspace.resolve()
        self.config = config
        self.root = (root or Path.home() / ".huicode" / "teams").resolve()
        self.worktrees = TeamWorktreeService(worktree_manager)
        self.assignment_executor = assignment_executor or unavailable_executor
        self.config_path = config_path
        self.agent_catalog = agent_catalog
        self.store: TeamStore | None = None
        self.team: TeamRecord | None = None
        self.registry: NameRegistry | None = None
        self.tasks: SharedTaskStore | None = None
        self.mailbox: MailboxStore | None = None
        self.approvals: ApprovalGate | None = None
        self._member_worktrees: dict[str, TeamWorktree] = {}
        self._handles: dict[str, tuple[object, BackendHandle]] = {}
        self._events: queue.Queue[TeamEvent] = queue.Queue()
        self._coroutine = CoroutineBackend(self._run_coroutine_member, config.max_members)
        self.selector = MemberBackendSelector(TmuxBackend(), WindowsTerminalBackend(), self._coroutine)

    def create(self, name: str, lead_session_id: str = "main") -> TeamRecord:
        if not self.config.enabled:
            raise TeamError("teams_disabled", "Team 能力未在配置中启用")
        safe = validate_name(name, "团队名")
        branch = self._git("branch", "--show-current") or "HEAD"
        head = self._git("rev-parse", "HEAD")
        now = _now()
        team = TeamRecord(new_id("team"), safe, lead_session_id, repository_id_for_workspace(self.workspace), str(self.workspace), branch, head, "active", now, now)
        store = TeamStore(self.root, safe, self.config)
        store.initialize(team)
        self._attach(store, team, ())
        self._event("team_created", f"团队 {safe} 已创建")
        return team

    def resume(self, name: str) -> TeamRecord:
        store = TeamStore(self.root, validate_name(name, "团队名"), self.config)
        team = store.load_team()
        if team.repository_id != repository_id_for_workspace(self.workspace):
            raise TeamError("repository_mismatch", "团队不属于当前 Git 仓库")
        members = store.load_members()
        self._attach(store, team, members)
        for member in members:
            self._quiesce_previous_terminal_worker(member)
        self._recover_persisted_assignments(members)
        for task in self._require_tasks().list():
            if task.status in {"pending", "blocked"} and task.assignee:
                self._prepare_task_baseline(task, task.description or task.title)
        for member in members:
            if member.status not in {"stopped", "failed"}:
                self._restore_member(member)
        self._event("team_resumed", f"团队 {team.name} 已恢复")
        return team

    def _recover_persisted_assignments(self, members: tuple[TeamMemberRecord, ...]) -> None:
        mailbox = self._require_mailbox()
        tasks = self._require_tasks()
        for member in members:
            messages, _ = mailbox.inbox(member.name, unread_only=True)
            for message in messages:
                if message.type != "assignment" or not message.task_id:
                    continue
                task = tasks.get(message.task_id)
                if task.status in {"pending", "blocked"} and not task.assignee:
                    tasks.assign(task.id, member.name)

    def _quiesce_previous_terminal_worker(self, member: TeamMemberRecord) -> None:
        if member.actual_backend not in {"tmux", "windows_terminal"}:
            return
        mailbox = self._require_mailbox()
        message = mailbox.send("lead", (member.name,), "切换团队成员运行后端", message_type="stop", correlation_id=new_id("resume-stop"))
        time.sleep(min(1.0, max(0.15, self.config.member_idle_poll_ms / 1000 * 3)))
        mailbox.mark_read(member.name, message.id)

    def list_teams(self) -> tuple[str, ...]:
        if not self.root.exists():
            return ()
        return tuple(sorted(path.name for path in self.root.iterdir() if path.is_dir() and (path / "team.json").exists()))

    def members(self) -> tuple[TeamMemberRecord, ...]:
        return self._require_store().load_members()

    def spawn_member(self, name: str, role: str, *, backend: str | None = None, approval_required: bool = False) -> TeamMemberRecord:
        store = self._require_store()
        team = self._require_team()
        safe = validate_name(name, "成员名")
        normalized_role = role.strip().lower()
        if not normalized_role:
            raise TeamError("invalid_role", "成员角色不能为空")
        role_profile: dict[str, object] = {}
        if self.agent_catalog is not None:
            try:
                self.agent_catalog.initialize()
            except Exception as exc:  # noqa: BLE001
                self._event("role_catalog_warning", f"Agent 角色目录刷新失败，成员将使用通用角色: {exc}", member=safe)
            definition = self.agent_catalog.get(normalized_role)
            if definition is not None:
                role_profile = {
                    "name": definition.name,
                    "instructions": definition.instructions,
                    "allowed_tools": list(definition.allowed_tools),
                    "denied_tools": list(definition.denied_tools),
                    "model": definition.model,
                    "max_iterations": definition.max_iterations,
                    "permission_mode": definition.permission_mode,
                    "source_path": str(definition.source_path),
                }
        members = list(store.load_members())
        if any(item.name == safe for item in members):
            raise TeamError("duplicate_member", f"成员名已存在: {safe}")
        if len(members) >= self.config.max_members:
            raise TeamError("member_limit", f"团队成员数已达到上限 {self.config.max_members}")
        member_id = new_id("member")
        worktree = self.worktrees.prepare_member(team.id, member_id, safe)
        requested = backend or self.config.default_backend
        selected = self.selector.select(requested)
        now = _now()
        provisional = TeamMemberRecord(member_id, safe, normalized_role, requested, selected.kind, approval_required, "starting", worktree.handle.identity.task_id, str(worktree.path), worktree.branch, str(store.paths.member_session(safe)), {}, {}, now, role_profile)
        members.append(provisional)
        store.save_members(members)
        if self.registry is None:
            raise TeamError("runtime_unavailable", "团队名称注册表未初始化")
        self.registry.add(safe)
        spec = MemberLaunchSpec(str(store.paths.root), member_id, safe, str(worktree.path), self.config_path)
        try:
            handle = selected.launch(spec)
        except Exception:
            store.save_members([replace(item, status="failed", updated_at=_now()) if item.id == member_id else item for item in members])
            raise
        record = replace(provisional, status="idle", backend_handle={**handle.data, "id": handle.id}, updated_at=_now())
        store.save_members([record if item.id == member_id else item for item in members])
        self._member_worktrees[member_id] = worktree
        self._handles[member_id] = (selected, handle)
        self._event("member_started", f"成员 {safe} 已启动，后端 {selected.kind}", member=safe, data={"backend": selected.kind, "worktree": str(worktree.path), "branch": worktree.branch})
        return record

    def assign(self, task_id: str, member: str, prompt: str) -> None:
        mailbox = self._require_mailbox()
        task = self._require_tasks().get(task_id)
        if not any(item.name == member for item in self.members()):
            raise TeamError("unknown_member", f"未知团队成员: {member}")
        baseline_paths = self._prepare_task_baseline(task, prompt)
        task = self._require_tasks().assign(task.id, member)
        assignment = prompt.strip() or task.description or task.title
        mailbox.send("lead", (member,), assignment, message_type="assignment", correlation_id=task.id, task_id=task.id)
        self._wake_member(member)
        self._event("task_assigned", f"任务 {task.id} 已分配给 {member}", member=member, task_id=task.id, data={"baseline_paths": list(baseline_paths)})

    def wait_tasks(self, task_ids: tuple[str, ...], timeout_seconds: float = 60.0) -> dict[str, object]:
        selected = task_ids or tuple(item.id for item in self._require_tasks().list())
        if not selected:
            return {"completed": True, "tasks": []}
        deadline = time.monotonic() + max(0.1, min(timeout_seconds, 300.0))
        while True:
            tasks = [self._require_tasks().get(task_id) for task_id in selected]
            if all(item.status in {"completed", "failed"} for item in tasks):
                return {"completed": True, "tasks": [record_dict(item) for item in tasks]}
            if time.monotonic() >= deadline:
                return {"completed": False, "timed_out": True, "tasks": [record_dict(item) for item in tasks]}
            time.sleep(0.1)

    def send_message(self, sender: str, recipients: tuple[str, ...], body: str):  # noqa: ANN201
        message = self._require_mailbox().send(sender, recipients, body)
        for member in recipients:
            if member != "lead":
                self._wake_member(member, warn_only=True)
        self._event("message_sent", message.summary, correlation_id=message.correlation_id)
        return message

    def stop_member(self, name: str) -> TeamMemberRecord:
        store = self._require_store()
        member = next((item for item in store.load_members() if item.name == name), None)
        if member is None:
            raise TeamError("unknown_member", f"未知团队成员: {name}")
        pair = self._handles.get(member.id)
        status = "stopped"
        if pair is not None:
            backend, handle = pair
            try:
                self._require_mailbox().send("lead", (name,), "停止当前成员", message_type="stop", correlation_id=new_id("stop"))
                try:
                    backend.wake(handle)  # type: ignore[attr-defined]
                except Exception:
                    pass
                backend.stop(handle, self.config.shutdown_wait_seconds)  # type: ignore[attr-defined]
            except Exception:
                status = "failed"
        updated = replace(member, status=status, updated_at=_now())
        store.save_members([updated if item.id == member.id else item for item in store.load_members()])
        self._event("member_stopped", f"成员 {name} 已{status}", member=name)
        return updated

    def close_team(self) -> TeamRecord:
        team = self._require_team()
        for member in self.members():
            if member.status not in {"stopped", "failed"}:
                self.stop_member(member.name)
        updated = replace(team, status="closed", updated_at=_now())
        self._require_store().save_team(updated)
        self.team = updated
        self._event("team_closed", f"团队 {team.name} 已关闭")
        return updated

    def delete_team(self) -> dict[str, object]:
        store = self._require_store()
        team = self._require_team()
        reasons: list[str] = []
        active = [item.name for item in self.members() if item.status not in {"stopped", "failed"}]
        if active:
            reasons.append("活动成员: " + ", ".join(active))
        unfinished = [item.id for item in self._require_tasks().list() if item.status not in {"completed", "failed"}]
        if unfinished:
            reasons.append("未完成任务: " + ", ".join(unfinished))
        pending = [item.request_id for item in store.load_approvals() if item.status == "pending"]
        if pending:
            reasons.append("待审批请求: " + ", ".join(pending))
        if self.registry is not None:
            unread = sum(len(self._require_mailbox().inbox(name, unread_only=True)[0]) for name in self.registry.names())
            if unread:
                reasons.append(f"未读消息: {unread}")
        if store.paths.integration.exists():
            from .storage import read_json
            integration = read_json(store.paths.integration).get("integration", {})
            if integration.get("status") != "published":
                reasons.append(f"未发布集成: {integration.get('status', 'unknown')}")
        if reasons:
            raise TeamError("team_protected", "团队仍有受保护状态，拒绝删除", {"reasons": reasons})
        for worktree in tuple(self._member_worktrees.values()):
            disposition = self.worktrees.delete(worktree)
            if disposition.state != "removed":
                raise TeamError("worktree_protected", "成员 Worktree 受保护，拒绝删除团队", {"reason": disposition.reason})
        path = store.paths.root.resolve()
        expected = team_path(self.root, team.name)
        if path != expected:
            raise TeamError("path_mismatch", "团队目录身份不匹配，拒绝删除")
        shutil.rmtree(path)
        self.store = None; self.team = None; self.registry = None; self.tasks = None; self.mailbox = None; self.approvals = None
        return {"deleted": True, "team": team.name}

    def status(self) -> dict[str, object]:
        team = self._require_team()
        members = self.members()
        tasks = self._require_tasks().list()
        return {"team": team.name, "status": team.status, "members": [{"name": item.name, "status": item.status, "backend": item.actual_backend, "worktree": item.worktree_path, "branch": item.branch} for item in members], "tasks": {state: sum(1 for item in tasks if item.status == state) for state in {item.status for item in tasks}}, "pending_approvals": sum(1 for item in self._require_store().load_approvals() if item.status == "pending")}

    def drain_events(self) -> tuple[TeamEvent, ...]:
        result = []
        while True:
            try:
                result.append(self._events.get_nowait())
            except queue.Empty:
                return tuple(result)

    def close(self) -> None:
        for member in self.members() if self.store is not None else ():
            pair = self._handles.get(member.id)
            if pair is not None:
                try:
                    if member.actual_backend in {"tmux", "windows_terminal"} and self.mailbox is not None:
                        self.mailbox.send("lead", (member.name,), "HuiCode 主会话关闭", message_type="stop", correlation_id=new_id("close-stop"))
                    pair[0].stop(pair[1], self.config.shutdown_wait_seconds)  # type: ignore[attr-defined]
                except Exception:
                    pass
        self._coroutine.close()

    def _attach(self, store: TeamStore, team: TeamRecord, members: tuple[TeamMemberRecord, ...]) -> None:
        self.store = store
        self.team = team
        self.registry = NameRegistry(("lead", *(item.name for item in members)))
        self.tasks = SharedTaskStore(store)
        self.mailbox = MailboxStore(store, self.registry)
        self.approvals = ApprovalGate(store, self.mailbox)

    def _run_coroutine_member(self, spec: MemberLaunchSpec, handle: BackendHandle) -> None:
        runner = TeamMemberRunner(
            self._require_mailbox(),
            self._require_tasks(),
            self.assignment_executor,
            approval_gate=self.approvals,
            approval_required=lambda name: bool(next((item.approval_required for item in self.members() if item.name == name), False)),
            status_callback=self._set_member_status,
            poll_ms=self.config.member_idle_poll_ms,
        )
        runner.run(spec, handle)

    def _restore_member(self, member: TeamMemberRecord) -> None:
        team = self._require_team()
        worktree = self.worktrees.prepare_member(team.id, member.id, member.name)
        requested = self.config.default_backend if member.requested_backend == "auto" else member.requested_backend
        selected = self.selector.select(requested)
        spec = MemberLaunchSpec(str(self._require_store().paths.root), member.id, member.name, str(worktree.path), self.config_path)
        handle = selected.launch(spec)
        updated = replace(member, actual_backend=selected.kind, status="idle", worktree_path=str(worktree.path), branch=worktree.branch, backend_handle={**handle.data, "id": handle.id}, updated_at=_now())
        self._require_store().save_members([updated if item.id == member.id else item for item in self.members()])
        self._member_worktrees[member.id] = worktree
        self._handles[member.id] = (selected, handle)

    def _set_member_status(self, name: str, status: str) -> None:
        store = self._require_store()
        members = list(store.load_members())
        updated = []
        for item in members:
            if item.name == name:
                item = replace(item, status=status, updated_at=_now())  # type: ignore[arg-type]
            updated.append(item)
        store.save_members(updated)
        self._event(f"member_{status}", f"成员 {name} 状态: {status}", member=name)

    def _wake_member(self, name: str, warn_only: bool = False) -> None:
        member = next((item for item in self.members() if item.name == name), None)
        if member is None:
            raise TeamError("unknown_member", f"未知团队成员: {name}")
        pair = self._handles.get(member.id)
        if pair is None:
            if warn_only:
                self._event("member_wake_failed", f"成员 {name} 当前没有运行后端", member=name)
                return
            raise TeamError("backend_unavailable", f"成员 {name} 当前没有运行后端")
        try:
            pair[0].wake(pair[1])  # type: ignore[attr-defined]
        except Exception as exc:
            self._event("member_wake_failed", f"成员 {name} 唤醒失败: {exc}", member=name)
            if not warn_only:
                raise

    def _event(self, kind: str, message: str, *, member: str = "", task_id: str = "", correlation_id: str = "", data: dict[str, object] | None = None) -> None:
        event = TeamEvent(kind, self.team.name if self.team else "", message, _now(), member, task_id, correlation_id, data or {})
        self._events.put(event)
        if self.store is not None:
            self.store.append_event(event)

    def _git(self, *args: str) -> str:
        completed = subprocess.run(["git", *args], cwd=self.workspace, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            raise TeamError("git_failed", (completed.stderr or completed.stdout).strip()[:800])
        return completed.stdout.strip()

    def _prepare_task_baseline(self, task, prompt: str) -> tuple[str, ...]:  # noqa: ANN001
        paths = _normalize_task_paths(tuple(task.paths), self.workspace) if task.paths else _extract_task_paths(f"{task.title}\n{task.description}\n{prompt}", self.workspace)
        if not paths or not self.members():
            return ()
        worktrees = [Path(item.worktree_path).resolve() for item in self.members()]
        if all(self._paths_exist_in_commit(path, paths) for path in worktrees):
            return paths
        heads = {self._git_at(path, "rev-parse", "HEAD") for path in worktrees}
        if len(heads) != 1:
            raise TeamError("baseline_diverged", "成员分支已经分叉，不能再注入新的共享文件基线", {"paths": list(paths)})
        base = next(iter(heads))
        for path in worktrees:
            if self._git_at(path, "status", "--porcelain", "--untracked-files=all"):
                raise TeamError("worktree_dirty", f"成员 Worktree 存在未提交修改，不能更新共享基线: {path}")
        snapshot = self._snapshot_paths(base, paths)
        if snapshot == base:
            return paths
        for path in worktrees:
            self._git_at(path, "merge", "--ff-only", snapshot)
        return paths

    def _snapshot_paths(self, base: str, paths: tuple[str, ...]) -> str:
        with tempfile.TemporaryDirectory(prefix="huicode-team-index-") as directory:
            index = Path(directory) / "index"
            env = os.environ.copy()
            env.update({
                "GIT_INDEX_FILE": str(index),
                "GIT_AUTHOR_NAME": "HuiCode Team",
                "GIT_AUTHOR_EMAIL": "team@huicode.local",
                "GIT_COMMITTER_NAME": "HuiCode Team",
                "GIT_COMMITTER_EMAIL": "team@huicode.local",
            })
            self._git_env(env, "read-tree", base)
            self._git_env(env, "add", "-A", "--", *paths)
            tree = self._git_env(env, "write-tree")
            if tree == self._git("rev-parse", f"{base}^{{tree}}"):
                missing = [relative for relative in paths if not self._path_exists_at_revision(base, relative)]
                if missing:
                    raise TeamError("task_path_unavailable", "任务路径不存在或被 Git 忽略，无法建立成员共同基线", {"paths": missing})
                return base
            commit = self._git_env(env, "commit-tree", tree, "-p", base, "-m", "HuiCode Team shared task baseline")
            self._record_baseline_paths(paths, commit)
            return commit

    def _record_baseline_paths(self, paths: tuple[str, ...], commit: str) -> None:
        store = self._require_store()
        entries: dict[str, object] = {}
        if store.paths.baseline.exists():
            entries.update(read_json(store.paths.baseline).get("entries", {}))
        for relative in paths:
            target = (self.workspace / relative).resolve()
            if target.is_file():
                entries[relative] = {"sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "commit": commit}
        atomic_write_json(store.paths.baseline, {"version": 1, "entries": entries})

    def _paths_exist_in_commit(self, worktree: Path, paths: tuple[str, ...]) -> bool:
        for relative in paths:
            completed = subprocess.run(["git", "cat-file", "-e", f"HEAD:{relative}"], cwd=worktree, shell=False, capture_output=True)
            if completed.returncode != 0:
                return False
        return True

    def _path_exists_at_revision(self, revision: str, relative: str) -> bool:
        completed = subprocess.run(["git", "cat-file", "-e", f"{revision}:{relative}"], cwd=self.workspace, shell=False, capture_output=True)
        return completed.returncode == 0

    def _git_env(self, env: dict[str, str], *args: str) -> str:
        completed = subprocess.run(["git", *args], cwd=self.workspace, env=env, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            raise TeamError("git_failed", (completed.stderr or completed.stdout).strip()[:800])
        return completed.stdout.strip()

    @staticmethod
    def _git_at(path: Path, *args: str) -> str:
        completed = subprocess.run(["git", *args], cwd=path, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            raise TeamError("git_failed", (completed.stderr or completed.stdout).strip()[:800])
        return completed.stdout.strip()

    def _require_store(self) -> TeamStore:
        if self.store is None:
            raise TeamError("no_active_team", "当前没有活动团队")
        return self.store

    def _require_team(self) -> TeamRecord:
        if self.team is None:
            raise TeamError("no_active_team", "当前没有活动团队")
        return self.team

    def _require_tasks(self) -> SharedTaskStore:
        if self.tasks is None:
            raise TeamError("no_active_team", "当前没有活动团队")
        return self.tasks

    def _require_mailbox(self) -> MailboxStore:
        if self.mailbox is None:
            raise TeamError("no_active_team", "当前没有活动团队")
        return self.mailbox
