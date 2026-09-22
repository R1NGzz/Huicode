"""认证接口：注册、登录、刷新、退出、当前用户。

设计要点：

- 注册同时创建默认工作区和 owner 成员关系，且与建用户在同一个事务里。
  T6 之后所有资源都挂在工作区下，注册若不建工作区，新用户登录后无处可去。
- 邮箱统一小写存储并据此判重，解决 T4 留下的"Alice@x.com 与 alice@x.com 是两个账号"。
- 任何响应都不回显密码或令牌以外的凭据；refresh token 原文只在签发时返回一次。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from huicode.server.api.errors import (
    ApiError,
    conflict,
    error_response,
    invalid_credentials,
    unauthenticated,
)
from huicode.server.auth import passwords, tokens
from huicode.server.auth.dependencies import get_current_user, get_session, get_settings
from huicode.server.config import ServerSettings
from huicode.server.db.base import as_utc
from huicode.server.db.models import RefreshToken, User, Workspace, WorkspaceMember

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
MAX_EMAIL_LENGTH = 320
MAX_DISPLAY_NAME_LENGTH = 120

# 登录时邮箱不存在也要跑一次哈希校验，让"账号不存在"和"密码错误"耗时接近。
# 否则响应时间本身就是一个账号枚举接口。
_DUMMY_HASH = passwords.hash_password("timing-equalisation-placeholder")


def _normalise_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if len(email) > MAX_EMAIL_LENGTH or not _EMAIL_PATTERN.match(email):
        raise ApiError(422, "validation_error", "邮箱格式不正确")
    return email


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str
    display_name: str = Field(min_length=1, max_length=MAX_DISPLAY_NAME_LENGTH)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class WorkspaceSummary(BaseModel):
    id: UUID
    name: str
    role: str


class UserProfile(BaseModel):
    id: UUID
    email: str
    display_name: str
    workspaces: list[WorkspaceSummary] = []


async def _issue_token_pair(
    session: AsyncSession, settings: ServerSettings, user_id: UUID,
) -> tuple[TokenPair, RefreshToken]:
    access_token = tokens.create_access_token(settings.jwt_secret, user_id)
    raw_refresh = tokens.generate_refresh_token()
    row = RefreshToken(
        user_id=user_id,
        token_hash=tokens.hash_refresh_token(raw_refresh),
        expires_at=tokens.refresh_token_expiry(),
    )
    session.add(row)
    pair = TokenPair(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=int(tokens.ACCESS_TOKEN_TTL.total_seconds()),
    )
    return pair, row


async def _revoke_all_active(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


@router.post("/register", response_model=TokenPair, status_code=201)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_session),
    settings: ServerSettings = Depends(get_settings),
) -> TokenPair:
    email = _normalise_email(payload.email)
    try:
        passwords.validate_password_policy(payload.password)
    except passwords.PasswordPolicyError as exc:
        # 策略异常是 ValueError 子类，不转成 ApiError 就会变成 500。
        raise ApiError(422, "validation_error", str(exc)) from None

    existing = await session.scalar(select(User.id).where(User.email == email))
    if existing is not None:
        raise conflict("email_taken", "该邮箱已注册")

    user = User(
        email=email,
        password_hash=passwords.hash_password(payload.password),
        display_name=payload.display_name.strip(),
    )
    session.add(user)
    await session.flush()  # 拿到 user.id，下面两条要引用它

    workspace = Workspace(name=f"{user.display_name} 的工作区", created_by=user.id)
    session.add(workspace)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))

    pair, _ = await _issue_token_pair(session, settings, user.id)
    return pair


@router.post("/login", response_model=TokenPair)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
    settings: ServerSettings = Depends(get_settings),
) -> TokenPair:
    email = _normalise_email(payload.email)
    user = await session.scalar(select(User).where(User.email == email))

    if user is None:
        passwords.verify_password(_DUMMY_HASH, payload.password)
        raise invalid_credentials()
    if not passwords.verify_password(user.password_hash, payload.password):
        raise invalid_credentials()
    if not user.is_active:
        raise invalid_credentials()

    pair, _ = await _issue_token_pair(session, settings, user.id)
    return pair


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: ServerSettings = Depends(get_settings),
):
    try:
        token_hash = tokens.hash_refresh_token(payload.refresh_token)
    except tokens.TokenError:
        raise unauthenticated("刷新令牌无效") from None

    row = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is None:
        raise unauthenticated("刷新令牌无效")

    now = datetime.now(timezone.utc)
    if row.revoked_at is not None:
        # 已撤销的令牌又被使用 = 要么被窃取重放，要么客户端状态错乱。
        # 两种情况下都不能继续信任这条链，整用户撤销。
        #
        # 这里必须 return 而不是 raise：抛异常会让 get_session 的事务回滚，
        # 上面这次撤销就白做了，而"检测到重放就作废整条链"恰恰是这里唯一
        # 有价值的部分。
        await _revoke_all_active(session, row.user_id)
        return error_response(request, unauthenticated("刷新令牌无效"))
    if as_utc(row.expires_at) <= now:
        raise unauthenticated("刷新令牌已过期")

    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        await _revoke_all_active(session, row.user_id)
        return error_response(request, unauthenticated("刷新令牌无效"))

    pair, new_row = await _issue_token_pair(session, settings, row.user_id)
    await session.flush()
    row.revoked_at = now
    row.replaced_by_id = new_row.id
    return pair


@router.post("/logout", status_code=204)
async def logout(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """退出登录。幂等：令牌不存在或已撤销同样返回 204。"""
    try:
        token_hash = tokens.hash_refresh_token(payload.refresh_token)
    except tokens.TokenError:
        return Response(status_code=204)
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    return Response(status_code=204)


@router.get("/me", response_model=UserProfile)
async def me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserProfile:
    rows = (
        await session.execute(
            select(Workspace.id, Workspace.name, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user.id)
            .order_by(Workspace.created_at)
        )
    ).all()
    return UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        workspaces=[WorkspaceSummary(id=row[0], name=row[1], role=row[2]) for row in rows],
    )
