"""FastAPI 依赖：数据库会话、当前用户、工作区角色。

这里刻意不把"读工作区"和"校验角色"分开成两步，因为分开之后每个路由都要记得
自己调校验，漏一次就是一个越权接口。`require_workspace_role` 把两件事绑在同一个
依赖里，路由函数拿到 WorkspaceMember 就说明校验已经过了。

**找不到成员与没有权限都返回 404**：若"不是成员"返回 403 而"是成员但角色不够"
返回 403/404 有别，就给了攻击者一个探测"这个 workspace_id 是否存在"的口子。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from huicode.server.api.errors import ApiError, forbidden, not_found, unauthenticated
from huicode.server.auth import permissions
from huicode.server.auth.tokens import TokenError, decode_access_token
from huicode.server.config import ServerSettings
from huicode.server.db.models import Project, User, WorkspaceMember
from huicode.server.runtime.workspace_resolver import WorkspacePathResolver

# auto_error=False：缺 Authorization 头时由我们抛 ApiError，
# 这样错误响应与其它接口同形（带 code 和 request_id），而不是 FastAPI 的默认体。
_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> ServerSettings:
    return request.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """每个请求一个 Session；请求结束即提交或回滚。"""
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise ApiError(503, "database_unavailable", "数据库暂时不可用")
    async with database.transaction() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
    settings: ServerSettings = Depends(get_settings),
) -> User:
    if credentials is None or not credentials.credentials:
        raise unauthenticated()
    try:
        user_id = decode_access_token(settings.jwt_secret, credentials.credentials)
    except TokenError:
        # 不把"过期"和"签名错误"的区别透给客户端。
        raise unauthenticated("登录状态无效或已过期") from None
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        # 用户被停用后，已签发的 access token 在有效期内也必须失效，
        # 否则"禁用账号"要等最长 15 分钟才生效。
        raise unauthenticated("登录状态无效或已过期")
    return user


def require_workspace_role(minimum: str):
    """返回一个依赖，校验当前用户在该工作区至少具有 minimum 角色。

    用法：``member = Depends(require_workspace_role("member"))``，
    路由函数直接拿到 WorkspaceMember。
    """

    async def dependency(
        workspace_id: UUID,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> WorkspaceMember:
        member = await session.get(WorkspaceMember, (workspace_id, user.id))
        if member is None:
            raise not_found()
        if not permissions.has_at_least(member.role, minimum):
            raise forbidden(f"需要 {minimum} 及以上权限")
        return member

    return dependency


def require_project_role(minimum: str):
    """按项目校验角色。返回 Project，供路由直接使用。

    `/api/projects/{project_id}` 的路径里没有 workspace_id，所以要先从项目反查
    工作区再校验成员关系。三者——项目不存在、项目不属于当前用户所在的任何工作区、
    是成员但角色不够——前两种一律 404，只有第三种是 403。若"不是成员"返回 403，
    就等于提供了一个探测 project_id 是否存在的接口。
    """

    async def dependency(
        project_id: UUID,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> Project:
        project = await session.get(Project, project_id)
        if project is None:
            raise not_found()
        member = await session.get(WorkspaceMember, (project.workspace_id, user.id))
        if member is None:
            raise not_found()
        if not permissions.has_at_least(member.role, minimum):
            raise forbidden(f"需要 {minimum} 及以上权限")
        return project

    return dependency


def get_resolver(settings: ServerSettings = Depends(get_settings)) -> WorkspacePathResolver:
    return WorkspacePathResolver(settings.project_root)
