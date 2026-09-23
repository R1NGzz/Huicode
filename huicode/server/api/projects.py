"""单个项目的修改接口。

路径里只有 project_id，没有 workspace_id，所以工作区由 `require_project_role`
从项目反查（见 auth/dependencies.py）。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from huicode.server.api.workspaces import ProjectOut
from huicode.server.auth.dependencies import (
    get_current_user,
    get_session,
    require_project_role,
)
from huicode.server.db.models import Project, User
from huicode.server.domain import projects as domain

router = APIRouter(prefix="/api/projects", tags=["projects"])


class RenameProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


def _out(project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id, workspace_id=project.workspace_id, name=project.name,
        workspace_path=project.workspace_path, status=project.status,
    )


@router.patch("/{project_id}", response_model=ProjectOut)
async def rename_project(
    project_id: UUID,
    payload: RenameProjectRequest,
    request: Request,
    project: Project = Depends(require_project_role("admin")),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    updated = await domain.rename_project(
        session, workspace_id=project.workspace_id, project=project,
        name=payload.name, actor=user, request_id=request.state.request_id,
    )
    return _out(updated)


@router.post("/{project_id}/archive", response_model=ProjectOut)
async def archive_project(
    project_id: UUID,
    request: Request,
    project: Project = Depends(require_project_role("admin")),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    """归档幂等：重复调用返回当前状态，不重复写审计。"""
    archived = await domain.archive_project(
        session, workspace_id=project.workspace_id, project=project,
        actor=user, request_id=request.state.request_id,
    )
    return _out(archived)
