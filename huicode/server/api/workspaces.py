"""工作区与项目的读写接口。

角色门槛按 checklist C6：**创建、重命名、归档项目要求 admin 及以上**（plan.md：
admin 管理项目、成员、审计和用量）；查看成员与项目列表要求 member / viewer。

非法路径的审计有个容易写错的地方：**必须先写审计、再返回错误响应**，不能抛异常。
抛异常会让请求级事务回滚，审计那行就没了——而"谁在什么时候试图越界"正是这条
审计唯一的价值。这个坑在 T5 的刷新令牌重放上踩过一次。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from huicode.server.api.errors import ApiError, error_response
from huicode.server.auth.dependencies import (
    get_current_user,
    get_resolver,
    get_session,
    require_workspace_role,
)
from huicode.server.db.models import User, WorkspaceMember
from huicode.server.domain import audit
from huicode.server.domain import projects as domain
from huicode.server.domain.errors import InvalidProjectPath
from huicode.server.runtime.workspace_resolver import WorkspacePathResolver

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    role: str


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    role: str


class ProjectOut(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    workspace_path: str
    status: str


class CreateWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    # 相对服务端项目根目录的路径，不是宿主机绝对路径（C48）。
    workspace_path: str


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[WorkspaceOut]:
    rows = await domain.list_workspaces(session, user.id)
    return [WorkspaceOut(id=w.id, name=w.name, role=role) for w, role in rows]


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    payload: CreateWorkspaceRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceOut:
    workspace = await domain.create_workspace(
        session, actor=user, name=payload.name, request_id=request.state.request_id,
    )
    return WorkspaceOut(id=workspace.id, name=workspace.name, role="owner")


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
async def list_members(
    workspace_id: UUID,
    _member: WorkspaceMember = Depends(require_workspace_role("member")),
    session: AsyncSession = Depends(get_session),
) -> list[MemberOut]:
    rows = await domain.list_members(session, workspace_id)
    return [
        MemberOut(
            user_id=user.id, email=user.email, display_name=user.display_name, role=member.role,
        )
        for member, user in rows
    ]


@router.get("/{workspace_id}/projects", response_model=list[ProjectOut])
async def list_projects(
    workspace_id: UUID,
    include_archived: bool = False,
    _member: WorkspaceMember = Depends(require_workspace_role("viewer")),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectOut]:
    rows = await domain.list_projects(session, workspace_id, include_archived=include_archived)
    return [
        ProjectOut(
            id=p.id, workspace_id=p.workspace_id, name=p.name,
            workspace_path=p.workspace_path, status=p.status,
        )
        for p in rows
    ]


@router.post("/{workspace_id}/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    workspace_id: UUID,
    payload: CreateProjectRequest,
    request: Request,
    _member: WorkspaceMember = Depends(require_workspace_role("admin")),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    resolver: WorkspacePathResolver = Depends(get_resolver),
):
    try:
        project = await domain.create_project(
            session, workspace_id=workspace_id, actor=user, name=payload.name,
            workspace_path=payload.workspace_path, resolver=resolver,
            request_id=request.state.request_id,
        )
    except InvalidProjectPath as exc:
        # 见模块顶部说明：先落审计，再正常返回错误，事务才会把审计提交掉。
        await audit.record(
            session, workspace_id=workspace_id, actor_user_id=user.id,
            action="project.path_rejected", resource_type="project",
            request_id=request.state.request_id, metadata={"reason": exc.message},
        )
        return error_response(request, ApiError(400, "invalid_project_path", exc.message))

    return ProjectOut(
        id=project.id, workspace_id=project.workspace_id, name=project.name,
        workspace_path=project.workspace_path, status=project.status,
    )
