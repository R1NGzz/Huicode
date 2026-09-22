from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Database:
    """应用共享连接池；每次 transaction 创建独立 Session，不跨任务共享。"""

    def __init__(self, url: str):
        self.engine = create_async_engine(url, pool_pre_ping=True, hide_parameters=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        # begin 上下文在正常退出时提交；异常（含取消）时回滚并关闭会话。
        async with self.sessions.begin() as session:
            yield session

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self.engine.dispose()
