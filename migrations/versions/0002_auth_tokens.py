"""认证所需的可撤销刷新令牌表

Revision ID: 0002_auth_tokens
Revises: 0001_initial
Create Date: 2026-09-22

T4 的十一张表里没有刷新令牌的存放位置。T5 需要它，理由见 models.py 的
RefreshToken 与 docs/web-studio-learning/T05-*.md：

- 刷新令牌必须可撤销（C16：已注销的 refresh token 不能换取有效身份），
  无状态 JWT 做不到，必须落库。
- 只存 SHA-256 哈希，原文仅在签发时返回一次（C57）。

与 0001 一样由 metadata 渲染生成，不手抄。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_auth_tokens"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
# --- 由 models.py 的 metadata 渲染生成 ---
    op.create_table('refresh_tokens',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replaced_by_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['replaced_by_id'], ['refresh_tokens.id'], name=op.f('fk_refresh_tokens_replaced_by_id_refresh_tokens'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash'))
    )
    op.create_index('ix_refresh_tokens_user_id_expires_at', 'refresh_tokens', ['user_id', 'expires_at'], unique=False)
    # --- 生成结束 ---

def downgrade() -> None:
# --- 由 models.py 的 metadata 渲染生成 ---
    op.drop_index('ix_refresh_tokens_user_id_expires_at', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    # --- 生成结束 ---
