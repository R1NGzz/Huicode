"""工作区数据访问基类；成员授权在 service 中校验后传入 workspace_id。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class WorkspaceRepository:
    def __init__(self, session: AsyncSession, workspace_id: UUID):
        if not isinstance(workspace_id, UUID):
            raise ValueError("workspace_id 必须为 UUID")
        self.session = session
        self.workspace_id = workspace_id

    def scoped_select(self, model):
        return select(model).where(model.workspace_id == self.workspace_id)

    async def get(self, model, resource_id: UUID):
        return await self.session.scalar(self.scoped_select(model).where(model.id == resource_id))

    def add(self, entity):
        if entity.workspace_id != self.workspace_id:
            raise ValueError("资源不属于当前工作区")
        self.session.add(entity)

    # 不提供 commit；业务服务可组合多个 Repository 为一个原子事务。
