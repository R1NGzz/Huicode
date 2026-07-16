from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .mailbox import MailboxStore
from .naming import new_id
from .storage import TeamStore
from .types import PlanApproval, TeamError


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ApprovalGate:
    def __init__(self, store: TeamStore, mailbox: MailboxStore) -> None:
        self.store = store
        self.mailbox = mailbox

    def submit_plan(self, member: str, task_id: str, plan: str) -> PlanApproval:
        if not plan.strip():
            raise TeamError("invalid_plan", "审批计划不能为空")
        with self.store.lock("approvals"):
            approvals = list(self.store.load_approvals())
            approvals = [replace(item, status="superseded") if item.member == member and item.task_id == task_id and item.status == "pending" else item for item in approvals]
            request = PlanApproval(new_id("plan"), member, task_id, plan.strip(), "pending", "", _now())
            approvals.append(request)
            self.store.save_approvals(approvals)
        self.mailbox.send(member, ("lead",), plan, message_type="plan_request", correlation_id=request.request_id, task_id=task_id)
        return request

    def decide(self, request_id: str, decision: str, feedback: str = "") -> PlanApproval:
        if decision not in {"allow", "deny"}:
            raise TeamError("invalid_decision", "审批决定只允许 allow 或 deny")
        with self.store.lock("approvals"):
            approvals = list(self.store.load_approvals())
            index = next((i for i, item in enumerate(approvals) if item.request_id == request_id), -1)
            if index < 0:
                raise TeamError("unknown_approval", f"未知审批请求: {request_id}")
            current = approvals[index]
            if current.status != "pending":
                raise TeamError("approval_closed", "审批请求已处理或过期")
            updated = replace(current, status="allowed" if decision == "allow" else "denied", feedback=feedback.strip(), decided_at=_now())
            approvals[index] = updated
            self.store.save_approvals(approvals)
        self.mailbox.send("lead", (updated.member,), feedback or decision, message_type="plan_decision", correlation_id=request_id, task_id=updated.task_id, payload={"decision": decision, "feedback": feedback})
        return updated

    def current(self, member: str, task_id: str) -> PlanApproval | None:
        matches = [item for item in self.store.load_approvals() if item.member == member and item.task_id == task_id]
        return matches[-1] if matches else None

    def allows_side_effect(self, member: str, task_id: str) -> bool:
        current = self.current(member, task_id)
        return current is not None and current.status == "allowed"
