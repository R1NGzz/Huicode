"""核心业务模型；Alembic 通过本模块读取 metadata。

字段来源为 specs/017-web-studio/plan.md 的 Core Data Structures 一节。
两处与 plan.md 的差异，已在 docs/web-studio-learning/T04-*.md 中说明：

- `UsageRecord` 只出现在 task.md 的 T4 步骤里，plan.md 没有定义它，这里按
  F10/C20 的"用量视图"需要补齐。
- `Project.workspace_path` 存相对路径而非绝对路径，配合 C48"API 无法创建
  指向未授权宿主机路径的项目"。

工具调用的幂等记录（C32）本阶段不建表：它的形状取决于 T12/T14 的执行设计，
现在定下来会先入为主。ToolApproval 已带 tool_call_id 且按 Run 唯一，够 T14 用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from huicode.server.db.base import Base, CreatedAtMixin, IdentityMixin, TimestampMixin

WORKSPACE_ROLES = ("owner", "admin", "member", "viewer")
PROJECT_STATUSES = ("active", "archived")
SESSION_STATUSES = ("idle", "running", "waiting_approval", "failed", "completed", "cancelled")
RUN_STATUSES = ("queued", "running", "waiting_approval", "completed", "failed", "cancelled")
RISK_LEVELS = ("low", "medium", "high")
APPROVAL_STATUSES = ("pending", "allowed", "denied", "expired", "cancelled")
EVENT_VISIBILITIES = ("user", "admin", "internal")
ARTIFACT_KINDS = ("diff", "file_snapshot", "tool_output")


def _enum_check(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    joined = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({joined})", name=name)


# --------------------------------------------------------------------------- 身份与授权


class User(IdentityMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Workspace(IdentityMixin, CreatedAtMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True,
    )


class WorkspaceMember(Base):
    """复合主键 (workspace_id, user_id)；一个用户在一个工作区只有一行。"""

    __tablename__ = "workspace_members"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (_enum_check("role", WORKSPACE_ROLES, "workspace_role"),)


# --------------------------------------------------------------------------- 项目与会话


class Project(IdentityMixin, CreatedAtMixin, Base):
    __tablename__ = "projects"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # 相对 HUICODE_PROJECT_ROOT 的路径，由 ProjectRootResolver 解析后再校验。
    # 不存绝对路径：绝对路径会把宿主机目录结构写进数据库，也让 C48 更难守。
    workspace_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )

    __table_args__ = (
        _enum_check("status", PROJECT_STATUSES, "project_status"),
        UniqueConstraint("workspace_id", "name", name="uq_projects_workspace_id_name"),
    )


class Session(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "sessions"

    project_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # 冗余 workspace_id：让工作区范围查询不必每次 join projects。
    # 代价是它与 project.workspace_id 可能不一致，由 service 层保证写入一致。
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="idle")
    created_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )

    __table_args__ = (
        _enum_check("status", SESSION_STATUSES, "session_status"),
        # 会话列表按更新时间倒序（C7）。
        Index("ix_sessions_workspace_id_updated_at", "workspace_id", "updated_at"),
    )


class Run(IdentityMixin, CreatedAtMixin, Base):
    __tablename__ = "runs"

    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 幂等键按会话唯一（C31）。可为空，SQL 允许多个 NULL，不互相冲突。
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        _enum_check("status", RUN_STATUSES, "run_status"),
        UniqueConstraint("session_id", "idempotency_key", name="uq_runs_session_id_idempotency_key"),
        # T15 的恢复扫描要按"过期租约 + 仍在跑"找失联任务。
        Index("ix_runs_status_lease_expires_at", "status", "lease_expires_at"),
    )


# --------------------------------------------------------------------------- 事件、审批、审计与产物


class SessionEvent(IdentityMixin, CreatedAtMixin, Base):
    """只追加。sequence 在单个会话内单调递增，用作 SSE 的 id 与断线补偿游标。"""

    __tablename__ = "session_events"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False,
    )
    run_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="user")

    __table_args__ = (
        _enum_check("visibility", EVENT_VISIBILITIES, "session_event_visibility"),
        # 唯一约束同时充当回放索引：按 session 取 sequence 区间。
        UniqueConstraint("session_id", "sequence", name="uq_session_events_session_id_sequence"),
    )


class ToolApproval(IdentityMixin, CreatedAtMixin, Base):
    __tablename__ = "tool_approvals"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False,
    )
    tool_call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    decided_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        _enum_check("risk_level", RISK_LEVELS, "tool_approval_risk_level"),
        _enum_check("status", APPROVAL_STATUSES, "tool_approval_status"),
        # 同一个 Run 里的同一次工具调用只应有一条审批（C30 的幂等前提）。
        UniqueConstraint("run_id", "tool_call_id", name="uq_tool_approvals_run_id_tool_call_id"),
    )


class AuditLog(IdentityMixin, CreatedAtMixin, Base):
    """只追加。actor 可为空，表示系统或 Worker 自身发起的动作。"""

    __tablename__ = "audit_logs"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # "metadata" 在 SQLAlchemy 声明式里是保留属性名，列名仍叫 metadata。
    audit_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict,
    )

    __table_args__ = (
        Index("ix_audit_logs_workspace_id_created_at", "workspace_id", "created_at"),
        Index("ix_audit_logs_request_id", "request_id"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )


class Artifact(IdentityMixin, CreatedAtMixin, Base):
    """大输出与 Diff 不放进事件 payload；事件存摘要，正文放这里。"""

    __tablename__ = "artifacts"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    relative_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (_enum_check("kind", ARTIFACT_KINDS, "artifact_kind"),)


class UsageRecord(IdentityMixin, CreatedAtMixin, Base):
    """一次 Run 一行（run_id 唯一）。

    C20 要求 Run、时间线和管理员用量视图三处数字一致；按 Run 汇总成一行，
    三处读同一个来源，比按模型调用逐条记录更容易保持相等。
    """

    __tablename__ = "usage_records"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True,
    )
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
