"""T8 事件存储在真实 PostgreSQL 与真实 Redis 上的验证。

SQLite 版本在 tests/server/test_event_store.py，覆盖同样的逻辑但跑得快。这里存在的
理由是两个**只在真环境才成立**的性质：

1. **`SELECT ... FOR UPDATE` 在 SQLite 上会被忽略**，所以并发追加的串行化在
   SQLite 上根本没有被验证过。这里用两个并发事务真正同时抢同一个会话的序号。
2. **通知确实到达 Redis 订阅者**。假 pubsub 只能验证调用顺序，验证不了真的发布/订阅。

默认跳过。启用方式见 tests/integration/__init__.py。
"""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from huicode.server.db.models import (
    Project,
    Session,
    SessionEvent,
    User,
    Workspace,
    WorkspaceMember,
)
from huicode.server.db.session import Database
from huicode.server.events import store as event_store
from huicode.server.events.publisher import EventPublisher
from huicode.server.events.subscriber import EventSubscriber
from huicode.server.events.types import RuntimeEvent
from tests.integration._migrations import reset_database

TEST_DATABASE_URL = os.environ.get("HUICODE_TEST_DATABASE_URL", "").strip()
# 默认用 127.0.0.1 而非 localhost：Windows 上 localhost 会先解析到 IPv6 的 ::1，
# 而 Docker 发布的端口只监听 IPv4，表现为连接超时（不是拒绝，所以更难看出来）。
TEST_REDIS_URL = os.environ.get("HUICODE_TEST_REDIS_URL", "redis://127.0.0.1:6379/0").strip()


@unittest.skipUnless(TEST_DATABASE_URL, "未设置 HUICODE_TEST_DATABASE_URL，跳过真库集成测试")
class PostgresEventStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            await reset_database(engine)
        finally:
            await engine.dispose()

        self.database = Database(TEST_DATABASE_URL)
        self.session_id, self.workspace_id, self.creator = await self._seed()

    async def asyncTearDown(self):
        await self.database.close()

    async def _seed(self):
        async with self.database.transaction() as session:
            user = User(email=f"{uuid4()}@example.com", password_hash="x", display_name="t")
            session.add(user)
            await session.flush()
            workspace = Workspace(name="w", created_by=user.id)
            session.add(workspace)
            await session.flush()
            session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
            project = Project(
                workspace_id=workspace.id, name="p", workspace_path="demo",
                status="active", created_by=user.id,
            )
            session.add(project)
            await session.flush()
            chat = Session(
                project_id=project.id, workspace_id=workspace.id,
                title="s", status="idle", created_by=user.id,
            )
            session.add(chat)
            await session.flush()
            return chat.id, workspace.id, user.id

    def make_event(self, session_id):
        return RuntimeEvent(
            type="assistant_text_delta", session_id=session_id, sequence=0,
            payload={"delta": "x"},
        )

    async def test_sequential_appends_number_correctly(self):
        for expected in (1, 2, 3):
            async with self.database.transaction() as session:
                row = await event_store.append(session, self.make_event(self.session_id))
            self.assertEqual(row.sequence, expected)

    async def test_for_update_serialises_concurrent_appends(self):
        """两个事务真的同时抢同一个会话的序号。

        `FOR UPDATE` 锁住父会话行，第二个事务必须等第一个提交后才能取 MAX，
        否则两者会拿到同一个序号——而唯一约束会让其中一个失败，表现为随机 500。
        这条测试在 SQLite 上无法成立，因为那边 `FOR UPDATE` 是空操作。
        """
        started = asyncio.Event()

        async def appender():
            async with self.database.transaction() as session:
                # 先读一次会话行，确保两个事务都已经进入
                await session.get(Session, self.session_id)
                started.set()
                await asyncio.sleep(0.15)  # 让另一个事务也进来
                return await event_store.append(session, self.make_event(self.session_id))

        results = await asyncio.gather(
            appender(), appender(), appender(), return_exceptions=True,
        )
        failures = [r for r in results if isinstance(r, Exception)]
        self.assertEqual(failures, [], f"并发追加失败：{failures}")

        sequences = sorted(row.sequence for row in results)
        self.assertEqual(sequences, [1, 2, 3], f"序号重复或跳号：{sequences}")

        async with self.database.transaction() as session:
            self.assertEqual(await event_store.latest_sequence(session, self.session_id), 3)

    async def test_unique_constraint_exists_as_the_backstop(self):
        """序号分配的锁若失效，唯一约束必须拦住，而不是写入重复序号。

        IntegrityError 必须让它穿出事务上下文，由 `begin()` 回滚之后再断言——
        在事务内部捕获的话，退出时提交一个已中止的事务会再抛一次。
        """
        async with self.database.transaction() as session:
            await event_store.append(session, self.make_event(self.session_id))

        with self.assertRaises(IntegrityError):
            async with self.database.transaction() as session:
                await session.execute(
                    insert(SessionEvent).values(
                        id=uuid4(), workspace_id=self.workspace_id, session_id=self.session_id,
                        sequence=1, event_type="run_started", payload={}, visibility="user",
                        created_at=datetime.now(timezone.utc),
                    )
                )
                await session.flush()


@unittest.skipUnless(TEST_DATABASE_URL, "未设置 HUICODE_TEST_DATABASE_URL，跳过真库集成测试")
class RedisPubSubTests(unittest.IsolatedAsyncioTestCase):
    """通知链路：数据库提交 → 发布 → 订阅者收到 → 回数据库补齐。"""

    async def asyncSetUp(self):
        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            await reset_database(engine)
        finally:
            await engine.dispose()

        self.database = Database(TEST_DATABASE_URL)
        self.redis = Redis.from_url(TEST_REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        try:
            await self.redis.ping()
        except Exception as exc:  # pragma: no cover - 环境问题
            await self.database.close()
            await self.redis.aclose()
            self.skipTest(f"Redis 不可用：{type(exc).__name__}")

        self.publisher = EventPublisher(self.redis)
        self.session_id, _, _ = await self._seed()

    async def asyncTearDown(self):
        await self.redis.aclose()
        await self.database.close()

    async def _seed(self):
        async with self.database.transaction() as session:
            user = User(email=f"{uuid4()}@example.com", password_hash="x", display_name="t")
            session.add(user)
            await session.flush()
            workspace = Workspace(name="w", created_by=user.id)
            session.add(workspace)
            await session.flush()
            session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
            project = Project(
                workspace_id=workspace.id, name="p", workspace_path="demo",
                status="active", created_by=user.id,
            )
            session.add(project)
            await session.flush()
            chat = Session(
                project_id=project.id, workspace_id=workspace.id,
                title="s", status="idle", created_by=user.id,
            )
            session.add(chat)
            await session.flush()
            return chat.id, workspace.id, user.id

    async def _append_and_publish(self, text):
        async with self.database.transaction() as session:
            row = await event_store.append(
                session,
                RuntimeEvent(
                    type="assistant_text_delta", session_id=self.session_id,
                    sequence=0, payload={"delta": text},
                ),
            )
        # 提交之后再发布——顺序不能反，否则订阅者可能比数据库先看到序号
        await self.publisher.publish(self.session_id, row.sequence)
        return row

    async def test_publish_reaches_a_real_subscriber(self):
        subscriber = EventSubscriber(
            self.database, self.publisher, poll_seconds=0.1, safety_poll_seconds=5.0,
        )
        collected = []

        async def consume():
            async for row in subscriber.stream(self.session_id, 0, idle_timeout=10.0):
                collected.append(row.sequence)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.4)  # 等订阅建立
        await self._append_and_publish("hello")
        await asyncio.sleep(1.0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertIn(1, collected, "通知没有通过 Redis 到达订阅者")

    async def test_catch_up_after_disconnect_returns_everything_missed(self):
        """断线期间产生的事件，重连后按 sequence 补齐、不重不漏。"""
        for index in range(4):
            await self._append_and_publish(f"chunk-{index}")

        subscriber = EventSubscriber(self.database, self.publisher)
        missed = await subscriber.catch_up(self.session_id, after_sequence=1)
        self.assertEqual([row.sequence for row in missed], [2, 3, 4])

        replay = await subscriber.catch_up(self.session_id, after_sequence=4)
        self.assertEqual(replay, [])


if __name__ == "__main__":
    unittest.main()
