from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


class TeamError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


TeamStatus = Literal["active", "closing", "closed", "failed"]
MemberStatus = Literal["starting", "working", "waiting_approval", "idle", "failed", "stopped"]
BackendKind = Literal["tmux", "windows_terminal", "coroutine"]
TaskStatus = Literal["pending", "blocked", "in_progress", "completed", "failed"]


@dataclass(frozen=True)
class TeamRecord:
    id: str
    name: str
    lead_session_id: str
    repository_id: str
    workspace: str
    target_branch: str
    target_base_commit: str
    status: TeamStatus
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TeamMemberRecord:
    id: str
    name: str
    role: str
    requested_backend: str
    actual_backend: str
    approval_required: bool
    status: MemberStatus
    worktree_task_id: str
    worktree_path: str
    branch: str
    session_path: str
    backend_handle: dict[str, str] = field(default_factory=dict)
    usage: dict[str, object] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(frozen=True)
class TeamTaskRecord:
    id: str
    title: str
    description: str
    status: TaskStatus
    assignee: str | None
    dependencies: tuple[str, ...]
    result_summary: str
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TeamMessage:
    id: str
    sender: str
    recipients: tuple[str, ...]
    body: str
    summary: str
    type: str
    correlation_id: str
    task_id: str | None
    timestamp: str
    read: bool = False
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanApproval:
    request_id: str
    member: str
    task_id: str
    plan: str
    status: str
    feedback: str
    created_at: str
    decided_at: str | None = None


@dataclass(frozen=True)
class TeamEvent:
    kind: str
    team: str
    message: str
    timestamp: str
    member: str = ""
    task_id: str = ""
    correlation_id: str = ""
    data: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TeamRuntimeIdentity:
    scope: Literal["main", "team_lead", "team_member", "subagent"] = "main"
    team_id: str | None = None
    member_id: str | None = None
    coordinator: bool = False


@dataclass(frozen=True)
class IntegrationRecord:
    id: str
    team_id: str
    target_branch: str
    expected_target_commit: str
    integration_branch: str
    worktree_path: str
    member_branches: tuple[str, ...]
    merged_members: tuple[str, ...]
    status: str
    pre_attempt_commit: str
    error: str = ""


def record_dict(value: object) -> dict[str, Any]:
    return asdict(value)  # type: ignore[arg-type]
