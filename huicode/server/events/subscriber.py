"""事件订阅：先补齐数据库，再跟随实时通知。

顺序是固定的，不能颠倒：

```text
客户端带上最后收到的 sequence
   → 从数据库补齐 sequence > after 的事件（这一步不依赖 Redis）
   → 补齐后再进入实时跟随
```

**Redis 只用来降低延迟。** 即使 Redis 完全不可用、或者通知全丢，订阅者也会按
`safety_poll_seconds` 周期回数据库读一次，事件一条都不会少。所以"Redis 挂掉"
的表现是延迟变大，不是丢数据——这正是计划要求的补偿路径。

`safety_poll_seconds` 不能省。如果只在收到通知时读库，那么"Redis 连着但某条通知
丢了"就会永久卡住，而这是最难排查的一类故障。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from uuid import UUID

from huicode.server.db.models import SessionEvent
from huicode.server.db.session import Database
from huicode.server.events import store as event_store
from huicode.server.events.publisher import EventPublisher

logger = logging.getLogger("huicode.server.events")

DEFAULT_POLL_SECONDS = 1.0
DEFAULT_SAFETY_POLL_SECONDS = 2.0


class EventSubscriber:
    def __init__(
        self,
        database: Database,
        publisher: EventPublisher | None = None,
        *,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        safety_poll_seconds: float = DEFAULT_SAFETY_POLL_SECONDS,
        batch: int = event_store.DEFAULT_BATCH,
    ):
        self.database = database
        self.publisher = publisher
        self.poll_seconds = poll_seconds
        self.safety_poll_seconds = safety_poll_seconds
        self.batch = batch

    # -- 公开接口 -------------------------------------------------------

    async def catch_up(self, session_id: UUID, after_sequence: int = 0) -> list[SessionEvent]:
        """一次性补齐：返回数据库里 sequence > after_sequence 的全部事件。

        断线重连时先调它，再进 `stream`。单独暴露是为了让调用方能在建立长连接
        之前就返回一批数据。
        """
        collected: list[SessionEvent] = []
        cursor = after_sequence
        while True:
            async with self.database.transaction() as session:
                rows = await event_store.list_after(
                    session, session_id, cursor, limit=self.batch,
                )
            if not rows:
                return collected
            collected.extend(rows)
            cursor = rows[-1].sequence
            if len(rows) < self.batch:
                return collected

    async def stream(
        self, session_id: UUID, after_sequence: int = 0, *, idle_timeout: float | None = None,
    ) -> AsyncIterator[SessionEvent]:
        """先补齐，再持续产出新事件。

        `idle_timeout` 为 None 时一直跟随；设为秒数时，静默超过该时长即结束
        （测试用它来避免无限等待，SSE 也可以在客户端断开时用它收尾）。
        """
        last = after_sequence
        for row in await self.catch_up(session_id, after_sequence):
            last = row.sequence
            yield row

        if self.publisher is not None and self.publisher.redis is not None:
            source = self._follow_redis(session_id, last, idle_timeout=idle_timeout)
        else:
            source = self._poll_database(session_id, last, idle_timeout=idle_timeout)

        async for row in source:
            yield row

    # -- 内部 -----------------------------------------------------------

    async def _new_events(self, session_id: UUID, after: int) -> list[SessionEvent]:
        async with self.database.transaction() as session:
            return await event_store.list_after(session, session_id, after, limit=self.batch)

    async def _poll_database(
        self, session_id: UUID, after: int, *, idle_timeout: float | None,
    ) -> AsyncIterator[SessionEvent]:
        """Redis 不可用时的退化路径：纯轮询。延迟高，但不丢事件。"""
        last = after
        idle_since = time.monotonic()
        while True:
            rows = await self._new_events(session_id, last)
            if rows:
                idle_since = time.monotonic()
                for row in rows:
                    last = row.sequence
                    yield row
                continue
            if idle_timeout is not None and time.monotonic() - idle_since >= idle_timeout:
                return
            await asyncio.sleep(self.poll_seconds)

    async def _follow_redis(
        self, session_id: UUID, after: int, *, idle_timeout: float | None,
    ) -> AsyncIterator[SessionEvent]:
        """订阅通知；收到通知立刻读库，等待超时也读一次。

        读库的时机有两个，缺一不可：

        - **收到通知**：延迟接近零，这是 Redis 存在的意义；
        - **`safety_poll_seconds` 内没有通知**：兜底。只依赖通知的话，
          "Redis 连着但某条通知丢了"会让订阅者永久停在原地，且看不出哪里错了。
          这是最难排查的一类故障，所以宁可有这一次多余查询。

        注意这里的超时是拿 `get_message` 的等待当节拍用的，不是"每轮都查库"——
        否则 Redis 就白接了。
        """
        last = after
        idle_since = time.monotonic()
        pubsub = self.publisher.redis.pubsub()
        channel = EventPublisher.channel(session_id)
        try:
            await pubsub.subscribe(channel)
            while True:
                try:
                    await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=self.safety_poll_seconds,
                    )
                except Exception:
                    logger.warning("event_subscribe_failed: 退化为数据库轮询")
                    async for row in self._poll_database(session_id, last, idle_timeout=idle_timeout):
                        yield row
                    return

                rows = await self._new_events(session_id, last)
                if rows:
                    idle_since = time.monotonic()
                    for row in rows:
                        last = row.sequence
                        yield row
                elif idle_timeout is not None and time.monotonic() - idle_since >= idle_timeout:
                    return
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                pass
