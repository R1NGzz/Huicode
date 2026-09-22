"""迁移只读取数据库地址，不依赖 JWT 或 Web 工作目录配置。"""

import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from huicode.server.config import _service_url
from huicode.server.db.models import Base

target_metadata = Base.metadata


def configure_and_run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def online(url):
    engine = create_async_engine(url, poolclass=NullPool, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(configure_and_run)
    finally:
        await engine.dispose()


url = _service_url(os.environ, "HUICODE_DATABASE_URL", {"postgresql+asyncpg"})
if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online(url))
