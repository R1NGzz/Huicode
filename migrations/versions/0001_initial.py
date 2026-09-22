"""核心业务表初始迁移

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-22

字段对应 specs/017-web-studio/plan.md 的 Core Data Structures 一节。

与 plan.md 的两处差异，理由见 task.md 与 docs/web-studio-learning/T04-*.md：
- UsageRecord 只在 task.md 的 T4 步骤里出现，plan.md 未定义；按 F10/C20 的
  用量视图需要补齐。
- Project.workspace_path 存相对 HUICODE_PROJECT_ROOT 的路径，不存绝对路径。

本文件由 metadata 渲染生成（alembic.autogenerate.render_python_code），
再手工整理表头；表、列、约束和索引名与 models.py 完全一致，不靠手抄。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
# --- 由 models.py 的 metadata 渲染生成 ---
    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('workspaces',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_workspaces_created_by_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workspaces'))
    )
    op.create_index(op.f('ix_workspaces_created_by'), 'workspaces', ['created_by'], unique=False)
    op.create_table('audit_logs',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('resource_type', sa.String(length=32), nullable=False),
    sa.Column('resource_id', sa.Uuid(), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('metadata', sa.JSON(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_audit_logs_actor_user_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_audit_logs_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index('ix_audit_logs_request_id', 'audit_logs', ['request_id'], unique=False)
    op.create_index('ix_audit_logs_resource', 'audit_logs', ['resource_type', 'resource_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_workspace_id'), 'audit_logs', ['workspace_id'], unique=False)
    op.create_index('ix_audit_logs_workspace_id_created_at', 'audit_logs', ['workspace_id', 'created_at'], unique=False)
    op.create_table('projects',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('workspace_path', sa.String(length=1024), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('active', 'archived')", name=op.f('ck_projects_project_status')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_projects_created_by_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_projects_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_projects')),
    sa.UniqueConstraint('workspace_id', 'name', name='uq_projects_workspace_id_name')
    )
    op.create_index(op.f('ix_projects_workspace_id'), 'projects', ['workspace_id'], unique=False)
    op.create_table('workspace_members',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.CheckConstraint("role IN ('owner', 'admin', 'member', 'viewer')", name=op.f('ck_workspace_members_workspace_role')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_workspace_members_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_workspace_members_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('workspace_id', 'user_id', name=op.f('pk_workspace_members'))
    )
    op.create_index(op.f('ix_workspace_members_user_id'), 'workspace_members', ['user_id'], unique=False)
    op.create_table('sessions',
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('idle', 'running', 'waiting_approval', 'failed', 'completed', 'cancelled')", name=op.f('ck_sessions_session_status')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_sessions_created_by_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_sessions_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_sessions_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions'))
    )
    op.create_index(op.f('ix_sessions_project_id'), 'sessions', ['project_id'], unique=False)
    op.create_index(op.f('ix_sessions_workspace_id'), 'sessions', ['workspace_id'], unique=False)
    op.create_index('ix_sessions_workspace_id_updated_at', 'sessions', ['workspace_id', 'updated_at'], unique=False)
    op.create_table('runs',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('worker_id', sa.String(length=64), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('queued', 'running', 'waiting_approval', 'completed', 'failed', 'cancelled')", name=op.f('ck_runs_run_status')),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_runs_session_id_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_runs_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_runs')),
    sa.UniqueConstraint('session_id', 'idempotency_key', name='uq_runs_session_id_idempotency_key')
    )
    op.create_index(op.f('ix_runs_session_id'), 'runs', ['session_id'], unique=False)
    op.create_index('ix_runs_status_lease_expires_at', 'runs', ['status', 'lease_expires_at'], unique=False)
    op.create_index(op.f('ix_runs_workspace_id'), 'runs', ['workspace_id'], unique=False)
    op.create_table('artifacts',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('relative_path', sa.String(length=1024), nullable=True),
    sa.Column('content_ref', sa.String(length=512), nullable=False),
    sa.Column('redacted', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('diff', 'file_snapshot', 'tool_output')", name=op.f('ck_artifacts_artifact_kind')),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_artifacts_run_id_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_artifacts_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_artifacts'))
    )
    op.create_index(op.f('ix_artifacts_run_id'), 'artifacts', ['run_id'], unique=False)
    op.create_index(op.f('ix_artifacts_workspace_id'), 'artifacts', ['workspace_id'], unique=False)
    op.create_table('session_events',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=48), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('visibility', sa.String(length=16), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("visibility IN ('user', 'admin', 'internal')", name=op.f('ck_session_events_session_event_visibility')),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_session_events_run_id_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_session_events_session_id_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_session_events_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_session_events')),
    sa.UniqueConstraint('session_id', 'sequence', name='uq_session_events_session_id_sequence')
    )
    op.create_index(op.f('ix_session_events_run_id'), 'session_events', ['run_id'], unique=False)
    op.create_index(op.f('ix_session_events_workspace_id'), 'session_events', ['workspace_id'], unique=False)
    op.create_table('tool_approvals',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('tool_call_id', sa.String(length=128), nullable=False),
    sa.Column('tool_name', sa.String(length=64), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('risk_level', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('decided_by', sa.Uuid(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("risk_level IN ('low', 'medium', 'high')", name=op.f('ck_tool_approvals_tool_approval_risk_level')),
    sa.CheckConstraint("status IN ('pending', 'allowed', 'denied', 'expired', 'cancelled')", name=op.f('ck_tool_approvals_tool_approval_status')),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], name=op.f('fk_tool_approvals_decided_by_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_tool_approvals_run_id_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_tool_approvals_session_id_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_tool_approvals_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tool_approvals')),
    sa.UniqueConstraint('run_id', 'tool_call_id', name='uq_tool_approvals_run_id_tool_call_id')
    )
    op.create_index(op.f('ix_tool_approvals_session_id'), 'tool_approvals', ['session_id'], unique=False)
    op.create_index(op.f('ix_tool_approvals_status'), 'tool_approvals', ['status'], unique=False)
    op.create_index(op.f('ix_tool_approvals_workspace_id'), 'tool_approvals', ['workspace_id'], unique=False)
    op.create_table('usage_records',
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('tool_calls', sa.Integer(), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_usage_records_run_id_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_usage_records_session_id_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_usage_records_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usage_records')),
    sa.UniqueConstraint('run_id', name=op.f('uq_usage_records_run_id'))
    )
    op.create_index(op.f('ix_usage_records_session_id'), 'usage_records', ['session_id'], unique=False)
    op.create_index(op.f('ix_usage_records_workspace_id'), 'usage_records', ['workspace_id'], unique=False)
    # --- 生成结束 ---

def downgrade() -> None:
# --- 由 models.py 的 metadata 渲染生成 ---
    op.drop_index(op.f('ix_usage_records_workspace_id'), table_name='usage_records')
    op.drop_index(op.f('ix_usage_records_session_id'), table_name='usage_records')
    op.drop_table('usage_records')
    op.drop_index(op.f('ix_tool_approvals_workspace_id'), table_name='tool_approvals')
    op.drop_index(op.f('ix_tool_approvals_status'), table_name='tool_approvals')
    op.drop_index(op.f('ix_tool_approvals_session_id'), table_name='tool_approvals')
    op.drop_table('tool_approvals')
    op.drop_index(op.f('ix_session_events_workspace_id'), table_name='session_events')
    op.drop_index(op.f('ix_session_events_run_id'), table_name='session_events')
    op.drop_table('session_events')
    op.drop_index(op.f('ix_artifacts_workspace_id'), table_name='artifacts')
    op.drop_index(op.f('ix_artifacts_run_id'), table_name='artifacts')
    op.drop_table('artifacts')
    op.drop_index(op.f('ix_runs_workspace_id'), table_name='runs')
    op.drop_index('ix_runs_status_lease_expires_at', table_name='runs')
    op.drop_index(op.f('ix_runs_session_id'), table_name='runs')
    op.drop_table('runs')
    op.drop_index('ix_sessions_workspace_id_updated_at', table_name='sessions')
    op.drop_index(op.f('ix_sessions_workspace_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_project_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_workspace_members_user_id'), table_name='workspace_members')
    op.drop_table('workspace_members')
    op.drop_index(op.f('ix_projects_workspace_id'), table_name='projects')
    op.drop_table('projects')
    op.drop_index('ix_audit_logs_workspace_id_created_at', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_workspace_id'), table_name='audit_logs')
    op.drop_index('ix_audit_logs_resource', table_name='audit_logs')
    op.drop_index('ix_audit_logs_request_id', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_workspaces_created_by'), table_name='workspaces')
    op.drop_table('workspaces')
    op.drop_table('users')
    # --- 生成结束 ---
