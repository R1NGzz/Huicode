from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .backends import BackendHandle, MemberLaunchSpec
from .approval import ApprovalGate
from .mailbox import MailboxStore
from .tasks import SharedTaskStore
from .types import TeamError


AssignmentExecutor = Callable[[str, str, str, Path], tuple[bool, str, dict[str, object]]]


class TeamMemberRunner:
    """长期成员邮箱循环；具体 Agent Loop 由可注入 executor 负责。"""

    def __init__(self, mailbox: MailboxStore, tasks: SharedTaskStore, executor: AssignmentExecutor, *, approval_gate: ApprovalGate | None = None, approval_required: Callable[[str], bool] | None = None, status_callback: Callable[[str, str], None] | None = None, poll_ms: int = 250) -> None:
        self.mailbox = mailbox
        self.tasks = tasks
        self.executor = executor
        self.approval_gate = approval_gate
        self.approval_required = approval_required or (lambda member: False)
        self.status_callback = status_callback or (lambda member, status: None)
        self.poll_seconds = max(0.05, poll_ms / 1000)

    def run(self, spec: MemberLaunchSpec, handle: BackendHandle) -> None:
        while not handle.stop_event.is_set():
            messages, _ = self.mailbox.inbox(spec.member_name, unread_only=True)
            stops = [item for item in messages if item.type == "stop"]
            if stops:
                for message in stops:
                    self.mailbox.mark_read(spec.member_name, message.id)
                handle.stop_event.set()
                break
            assignments = [item for item in messages if item.type == "assignment" and item.task_id]
            if not assignments:
                handle.wake_event.wait(self.poll_seconds)
                handle.wake_event.clear()
                continue
            for message in assignments:
                if handle.stop_event.is_set():
                    break
                if self.approval_required(spec.member_name) and self.approval_gate is not None:
                    approval = self.approval_gate.current(spec.member_name, message.task_id or "")
                    if approval is None:
                        self.approval_gate.submit_plan(spec.member_name, message.task_id or "", f"计划执行任务：{message.body}")
                        self.status_callback(spec.member_name, "waiting_approval")
                        handle.wake_event.wait(self.poll_seconds)
                        handle.wake_event.clear()
                        continue
                    if approval.status == "pending":
                        handle.wake_event.wait(self.poll_seconds)
                        handle.wake_event.clear()
                        continue
                    if approval.status == "denied":
                        self.approval_gate.submit_plan(spec.member_name, message.task_id or "", f"根据反馈重新规划：{approval.feedback}\n任务：{message.body}")
                        self.status_callback(spec.member_name, "waiting_approval")
                        handle.wake_event.wait(self.poll_seconds)
                        handle.wake_event.clear()
                        continue
                    if approval.status != "allowed":
                        continue
                self.mailbox.mark_read(spec.member_name, message.id)
                self._execute(spec, message.task_id or "", message.body)

    def _execute(self, spec: MemberLaunchSpec, task_id: str, prompt: str) -> None:
        task = self.tasks.get(task_id)
        if task.status not in {"pending", "blocked"}:
            return
        task = self.tasks.claim(task.id, spec.member_name, task.version)
        self.status_callback(spec.member_name, "working")
        try:
            ok, summary, usage = self.executor(spec.member_name, task.id, prompt, Path(spec.workspace))
        except Exception as exc:  # noqa: BLE001
            ok, summary, usage = False, str(exc), {}
        current = self.tasks.get(task.id)
        self.tasks.update(current.id, expected_version=current.version, status="completed" if ok else "failed", result_summary=summary)
        self.mailbox.send(spec.member_name, ("lead",), summary, message_type="completion", correlation_id=task.id, task_id=task.id, payload={"ok": ok, "usage": usage})
        self.mailbox.send(spec.member_name, ("lead",), "成员已空闲", message_type="idle", correlation_id=task.id, task_id=task.id)
        self.status_callback(spec.member_name, "idle")


def unavailable_executor(member: str, task_id: str, prompt: str, workspace: Path) -> tuple[bool, str, dict[str, object]]:
    del member, task_id, prompt, workspace
    raise TeamError("member_executor_unavailable", "团队成员 Agent Runner 尚未连接")
