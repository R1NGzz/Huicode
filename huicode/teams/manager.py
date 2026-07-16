from __future__ import annotations

import queue
import shutil
import subprocess
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
from .storage import TeamStore
from .tasks import SharedTaskStore
from .terminal_backends import TmuxBackend, WindowsTerminalBackend
from .types import TeamError, TeamEvent, TeamMemberRecord, TeamRecord
from .worktrees import TeamWorktree, TeamWorktreeService


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
            if member.status not in {"stopped", "failed"}:
                self._restore_member(member)
        self._event("team_resumed", f"团队 {team.name} 已恢复")
        return team

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
        if self.agent_catalog is not None and self.agent_catalog.get(role) is None:
            raise TeamError("unknown_role", f"未知子 Agent 角色: {role}")
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
        provisional = TeamMemberRecord(member_id, safe, role, requested, selected.kind, approval_required, "starting", worktree.handle.identity.task_id, str(worktree.path), worktree.branch, str(store.paths.member_session(safe)), {}, {}, now)
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
        mailbox.send("lead", (member,), prompt, message_type="assignment", correlation_id=task.id, task_id=task.id)
        self._wake_member(member)
        self._event("task_assigned", f"任务 {task.id} 已分配给 {member}", member=member, task_id=task.id)

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
        selected = self.selector.select(member.requested_backend)
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
