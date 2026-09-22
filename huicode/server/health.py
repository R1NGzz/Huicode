"""依赖连接的生命周期和有界就绪探测。"""

import asyncio
from contextlib import AsyncExitStack

from redis.asyncio import Redis

from huicode.server.config import ServerSettings
from huicode.server.db.session import Database


class DependencyHealth:
    def __init__(self, settings: ServerSettings):
        self.settings = settings
        self.database = None
        self.redis = None
        self.resources = AsyncExitStack()

    async def open(self):
        # 客户端按需连接；依赖离线时 API 仍可提供存活探测。
        try:
            self.database = Database(self.settings.database_url)
            self.resources.push_async_callback(self.database.close)
            self.redis = Redis.from_url(
                self.settings.redis_url, socket_connect_timeout=1, socket_timeout=1,
            )
            self.resources.push_async_callback(self.redis.aclose)
        except Exception:
            await self.close()
            raise

    async def close(self):
        await self.resources.aclose()

    async def database_check(self):
        if self.database is None:
            raise RuntimeError("数据库客户端未初始化")
        await self.database.ping()

    async def redis_check(self):
        if self.redis is None:
            raise RuntimeError("Redis 客户端未初始化")
        await self.redis.ping()

    async def check(self):
        async def probe(callback):
            try:
                async with asyncio.timeout(2):
                    await callback()
                return "ok"
            except Exception:
                # 不把带连接地址或密码的依赖异常返回给客户端。
                return "unavailable"

        database, redis = await asyncio.gather(probe(self.database_check), probe(self.redis_check))
        return {"database": database, "redis": redis}
