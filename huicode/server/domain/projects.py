"""工作区与项目的业务规则。

**每一条查询都显式带 workspace_id。** 这是 C12–C15 的落点：越权最典型的形状就是
"知道别人的 id 就能读"，所以这里不提供 `get_project(session, project_id)` 这种入口，
只有 `get_project(session, workspace_id, project_id)`。少了工作区条件，调用方就算
想越权也得先自己把 workspace_id 编出来，而不是"忘了传"。

项目目录一律经 `WorkspacePathResolver` 解析后才落库，`workspace_path` 存的是
**相对服务端项目根目录的规范化路径**（POSIX 分隔符），不存绝对路径。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from huicode.server.db.models import Project, User, Workspace, WorkspaceMember
from huicode.server.domain import audit
from huicode.server.domain.errors import (
    ArchivedProject,
    DuplicateProjectName,
    InvalidName,
    InvalidProjectPath,
)
from huicode.server.runtime.workspace_resolver import PathViolation, WorkspacePathResolver

MAX_WORKSPACE_NAME = 120
MAX_PROJECT_NAME = 160
PROJECT_ACTIVE = "active"
PROJECT_ARCHIVED = "archived"


def _clean_name(value: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise InvalidName("名称必须是字符串")
    name = value.strip()
    if not name:
        raise InvalidName("名称不能为空")
    if len(name) > limit:
        raise InvalidName(f"名称不能超过 {limit} 个字符")
    # 换行和制表符会让审计日志和界面出现难以察觉的伪造行。
    if any(character in name for character in "\r\n\t\x00"):
        raise InvalidName("名称包含不允许的控制字符")
    return name


# --------------------------------------------------------------------------- 工作区


async def list_workspaces(
    session: AsyncSession, user_id: UUID,
) -> list[tuple[Workspace, str]]:
    """当前用户所属的工作区及其角色。"""
    rows = (
        await session.execute(
            select(Workspace, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(Workspace.created_at)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def create_workspace(
    session: AsyncSession, *, actor: User, name: str, request_id: str,
) -> Workspace:
    """创建者自动成为 owner。没有这一条，新工作区将无人可管理。"""
    clean = _clean_name(name, limit=MAX_WORKSPACE_NAME)
    workspace = Workspace(name=clean, created_by=actor.id)
    session.add(workspace)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=workspace.id, user_id=actor.id, role="owner"))
    await audit.record(
        session, workspace_id=workspace.id, actor_user_id=actor.id,
        action="workspace.create", resource_type="workspace",
        resource_id=workspace.id, request_id=request_id,
    )
    return workspace


async def list_members(
    session: AsyncSession, workspace_id: UUID,
) -> list[tuple[WorkspaceMember, User]]:
    rows = (
        await session.execute(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(User.email)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


# --------------------------------------------------------------------------- 项目


async def list_projects(
    session: AsyncSession, workspace_id: UUID, *, include_archived: bool = False,
) -> list[Project]:
    statement = select(Project).where(Project.workspace_id == workspace_id)
    if not include_archived:
        statement = statement.where(Project.status == PROJECT_ACTIVE)
    return list((await session.scalars(statement.order_by(Project.created_at))).all())


async def get_project(
    session: AsyncSession, workspace_id: UUID, project_id: UUID,
) -> Project | None:
    return await session.scalar(
        select(Project).where(
            Project.workspace_id == workspace_id, Project.id == project_id,
        )
    )


async def _name_taken(
    session: AsyncSession, workspace_id: UUID, name: str, *, exclude_id: UUID | None = None,
) -> bool:
    """项目名是否已被占用。

    这只是为了给出友好错误，**不是并发保护**——两个请求可以同时查完再同时插入。
    最终判据是数据库上的 `uq_projects_workspace_id_name`，见下面的 begin_nested。
    """
    statement = select(Project.id).where(
        Project.workspace_id == workspace_id, Project.name == name,
    )
    if exclude_id is not None:
        statement = statement.where(Project.id != exclude_id)
    return await session.scalar(statement) is not None


async def create_project(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor: User,
    name: str,
    workspace_path: str,
    resolver: WorkspacePathResolver,
    request_id: str,
) -> Project:
    clean = _clean_name(name, limit=MAX_PROJECT_NAME)

    try:
        directory = resolver.resolve_project_directory(workspace_path)
    except PathViolation as exc:
        # 转成领域错误，让 API 层能识别"这是路径问题"并记审计。
        raise InvalidProjectPath(str(exc)) from None

    # 存规范化后的相对路径：入参可能带 "./"、反斜杠或重复分隔符，
    # 存原样会让"同一个目录"在库里有多份不同写法。
    relative = directory.relative_to(resolver.project_root).as_posix()

    if await _name_taken(session, workspace_id, clean):
        raise DuplicateProjectName("该项目名已存在")

    project = Project(
        workspace_id=workspace_id, name=clean, workspace_path=relative,
        status=PROJECT_ACTIVE, created_by=actor.id,
    )
    try:
        # 用 SAVEPOINT 包住这一次写入：唯一约束被触发时只回滚这一段，
        # 外层事务仍然可用，可以把 IntegrityError 转成 409 而不是漏成 500。
        async with session.begin_nested():
            session.add(project)
            await session.flush()
    except IntegrityError:
        raise DuplicateProjectName("该项目名已存在") from None

    await audit.record(
        session, workspace_id=workspace_id, actor_user_id=actor.id,
        action="project.create", resource_type="project",
        resource_id=project.id, request_id=request_id,
        metadata={"name": clean},
    )
    return project


async def rename_project(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project: Project,
    name: str,
    actor: User,
    request_id: str,
) -> Project:
    if project.status == PROJECT_ARCHIVED:
        raise ArchivedProject("已归档的项目不能重命名")

    clean = _clean_name(name, limit=MAX_PROJECT_NAME)
    if clean == project.name:
        return project

    if await _name_taken(session, workspace_id, clean, exclude_id=project.id):
        raise DuplicateProjectName("该项目名已存在")

    previous = project.name
    project.name = clean
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        raise DuplicateProjectName("该项目名已存在") from None

    await audit.record(
        session, workspace_id=workspace_id, actor_user_id=actor.id,
        action="project.rename", resource_type="project",
        resource_id=project.id, request_id=request_id,
        metadata={"from": previous, "to": clean},
    )
    return project


async def archive_project(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project: Project,
    actor: User,
    request_id: str,
) -> Project:
    """归档是幂等的：重复调用返回当前状态，不重复写审计。"""
    if project.status == PROJECT_ARCHIVED:
        return project

    project.status = PROJECT_ARCHIVED
    await audit.record(
        session, workspace_id=workspace_id, actor_user_id=actor.id,
        action="project.archive", resource_type="project",
        resource_id=project.id, request_id=request_id,
    )
    return project
