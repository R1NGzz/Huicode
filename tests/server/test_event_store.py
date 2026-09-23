"""T8 事件持久化、发布与补偿。

跑在真实 SQLite 文件上（迁移链全量执行）。真实 PostgreSQL 与真 Redis 的版本在
tests/integration/test_event_store.py；这里覆盖逻辑本身，跑得快。

`FOR UPDATE` 在 SQLite 上会被忽略，所以**这里的并发用例不能证明行锁有效**——
它证明的是"约束与重试路径能把冲突变成正确结果，而不是 500"。行锁本身只在
PostgreSQL 集成测试里验。
"""

import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select

from huicode.server.db.models import (
    Project,
    Run,
    Session,
    SessionEvent,
    User,
    Workspace,
    WorkspaceMember,
)
from huicode.server.db.session import Database
from huicode.server.events import store as event_store
from huicode.server.events.errors import EventStoreError
from huicode.server.events.publisher import EventPublisher
from huicode.server.events.subscriber import EventSubscriber
from huicode.server.events.types import RuntimeEvent

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def _load(name):
    spec = importlib.util.spec_from_file_location(name.stem, VERSIONS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakePubSub:
    """够用的 pubsub 替身：按需返回消息，否则等待到超时。"""

    def __init__(self, messages=None):
        self.messages = list(messages or [])
        self.subscribed = None

    async def subscribe(self, channel):
        self.subscribed = channel

    async def get_message(self, ignore_subscribe_messages=True, timeout=None):
        if self.messages:
            return self.messages.pop(0)
        await asyncio.sleep(min(timeout or 0, 0.05))
        return None

    async def unsubscribe(self, channel):
        pass

    async def aclose(self):
        pass


class FakeRedis:
    def __init__(self, messages=None, fail_publish=False):
        self.pubsubs = []
        self.published = []
        self.fail_publish = fail_publish
        self._messages = messages

    def pubsub(self):
        created = FakePubSub(self._messages)
        self.pubsubs.append(created)
        return created

    async def publish(self, channel, payload):
        if self.fail_publish:
            raise ConnectionError("redis down")
        self.published.append((channel, payload))
        return 1


class EventStoreTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "events.db"
        engine = create_engine(f"sqlite:///{path.as_posix()}")
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            for name in ("0001_initial.py", "0002_auth_tokens.py"):
                module = _load(Path(name))
                module.op = Operations(context)
                module.upgrade()
        engine.dispose()

        self.database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
        self.session_id, self.workspace_id = await self._seed()

    async def asyncTearDown(self):
        await self.database.close()
        self.temp.cleanup()

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
            return chat.id, workspace.id

    async def _make_session(self):
        """再建一个会话，用于验证序号是按会话独立的。"""
        async with self.database.transaction() as session:
            project = (
                await session.scalars(
                    select(Project).where(Project.workspace_id == self.workspace_id)
                )
            ).first()
            chat = Session(
                project_id=project.id, workspace_id=self.workspace_id,
                title="s2", status="idle", created_by=project.created_by,
            )
            session.add(chat)
            await session.flush()
            return chat.id

    def make_event(self, session_id, event_type="assistant_text_delta", **payload):
        return RuntimeEvent(
            type=event_type, session_id=session_id, sequence=0,
            payload=payload or {"delta": "x"},
        )

    async def append(self, event):
        async with self.database.transaction() as session:
            return await event_store.append(session, event)


class AppendTests(EventStoreTestCase):
    async def test_sequence_starts_at_one_and_increases(self):
        first = await self.append(self.make_event(self.session_id))
        second = await self.append(self.make_event(self.session_id))
        third = await self.append(self.make_event(self.session_id))
        self.assertEqual([first.sequence, second.sequence, third.sequence], [1, 2, 3])

    async def test_sequences_are_per_session(self):
        other = await self._make_session()
        await self.append(self.make_event(self.session_id))
        await self.append(self.make_event(self.session_id))
        first_of_other = await self.append(self.make_event(other))
        self.assertEqual(first_of_other.sequence, 1)

    async def test_workspace_comes_from_the_parent_session(self):
        """调用方无法把事件写进别的工作区：归属取自会话行。"""
        row = await self.append(self.make_event(self.session_id))
        self.assertEqual(row.workspace_id, self.workspace_id)

    async def test_repeated_event_id_is_idempotent_and_does_not_advance_sequence(self):
        event = self.make_event(self.session_id)
        first = await self.append(event)
        again = await self.append(event)

        self.assertEqual(first.id, again.id)
        self.assertEqual(first.sequence, again.sequence)
        async with self.database.transaction() as session:
            self.assertEqual(await event_store.latest_sequence(session, self.session_id), 1)

        # 序号不因重试产生空洞：下一条仍然是 2
        nxt = await self.append(self.make_event(self.session_id))
        self.assertEqual(nxt.sequence, 2)

    async def test_appending_to_an_unknown_session_is_rejected(self):
        with self.assertRaises(EventStoreError) as caught:
            await self.append(self.make_event(uuid4()))
        self.assertEqual(caught.exception.code, "session_not_found")

    async def test_payload_and_visibility_are_persisted(self):
        event = RuntimeEvent(
            type="error", session_id=self.session_id, sequence=0,
            payload={"message": "上游超时"}, visibility="admin",
        )
        row = await self.append(event)
        self.assertEqual(row.event_type, "error")
        self.assertEqual(row.payload, {"message": "上游超时"})
        self.assertEqual(row.visibility, "admin")


class ReadTests(EventStoreTestCase):
    async def test_list_after_returns_only_newer_events_in_order(self):
        for _ in range(4):
            await self.append(self.make_event(self.session_id))

        async with self.database.transaction() as session:
            rows = await event_store.list_after(session, self.session_id, 2)
        self.assertEqual([row.sequence for row in rows], [3, 4])

    async def test_list_after_zero_returns_everything(self):
        for _ in range(3):
            await self.append(self.make_event(self.session_id))
        async with self.database.transaction() as session:
            rows = await event_store.list_after(session, self.session_id, 0)
        self.assertEqual(len(rows), 3)

    async def test_list_after_respects_limit(self):
        for _ in range(5):
            await self.append(self.make_event(self.session_id))
        async with self.database.transaction() as session:
            rows = await event_store.list_after(session, self.session_id, 0, limit=2)
        self.assertEqual([row.sequence for row in rows], [1, 2])

    async def test_list_after_rejects_a_negative_cursor(self):
        async with self.database.transaction() as session:
            with self.assertRaises(EventStoreError):
                await event_store.list_after(session, self.session_id, -1)

    async def test_latest_sequence_of_an_empty_session_is_zero(self):
        async with self.database.transaction() as session:
            self.assertEqual(await event_store.latest_sequence(session, self.session_id), 0)


class PublisherTests(unittest.IsolatedAsyncioTestCase):
    async def test_channels_are_per_session(self):
        self.assertNotEqual(
            EventPublisher.channel(uuid4()), EventPublisher.channel(uuid4()),
        )

    async def test_publish_without_redis_reports_failure_without_raising(self):
        self.assertFalse(await EventPublisher(None).publish(uuid4(), 1))

    async def test_publish_sends_a_notification_not_the_payload(self):
        redis = FakeRedis()
        session_id = uuid4()
        self.assertTrue(await EventPublisher(redis).publish(session_id, 7))
        channel, payload = redis.published[0]
        self.assertEqual(channel, EventPublisher.channel(session_id))
        self.assertIn(str(session_id), payload)
        self.assertIn("7", payload)

    async def test_publish_failure_is_reported_not_raised(self):
        """事件此时已经提交，发布失败不能让调用方以为写入失败。"""
        self.assertFalse(await EventPublisher(FakeRedis(fail_publish=True)).publish(uuid4(), 1))


class SubscriberTests(EventStoreTestCase):
    async def test_catch_up_returns_everything_after_the_cursor(self):
        for _ in range(3):
            await self.append(self.make_event(self.session_id))
        subscriber = EventSubscriber(self.database)
        rows = await subscriber.catch_up(self.session_id, 1)
        self.assertEqual([row.sequence for row in rows], [2, 3])

    async def test_catch_up_drains_more_than_one_batch(self):
        for _ in range(5):
            await self.append(self.make_event(self.session_id))
        subscriber = EventSubscriber(self.database, batch=2)
        rows = await subscriber.catch_up(self.session_id, 0)
        self.assertEqual([row.sequence for row in rows], [1, 2, 3, 4, 5])

    async def test_stream_without_redis_catches_up_then_polls(self):
        """Redis 不可用时的补偿路径：仍然能拿到实时追加的事件。"""
        for _ in range(2):
            await self.append(self.make_event(self.session_id))

        subscriber = EventSubscriber(self.database, poll_seconds=0.05)
        collected = []

        async def consume():
            async for row in subscriber.stream(self.session_id, 0, idle_timeout=2.0):
                collected.append(row.sequence)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.25)
        await self.append(self.make_event(self.session_id))
        await asyncio.sleep(0.3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(collected[:2], [1, 2])
        self.assertIn(3, collected)

    async def test_stream_stops_after_idle_timeout(self):
        subscriber = EventSubscriber(self.database, poll_seconds=0.05)
        seen = [row.sequence async for row in subscriber.stream(self.session_id, 0, idle_timeout=0.2)]
        self.assertEqual(seen, [])

    async def test_missed_notification_is_recovered_by_the_safety_poll(self):
        """Redis 连着但通知丢了——只靠通知的订阅者会永久卡住。"""
        redis = FakeRedis(messages=[])  # 永远不发消息
        subscriber = EventSubscriber(
            self.database, EventPublisher(redis), poll_seconds=0.05, safety_poll_seconds=0.1,
        )
        collected = []

        async def consume():
            async for row in subscriber.stream(self.session_id, 0, idle_timeout=3.0):
                collected.append(row.sequence)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.2)
        await self.append(self.make_event(self.session_id))
        await asyncio.sleep(0.4)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertIn(1, collected, "兜底轮询没有补上丢失的通知")

    async def test_redis_error_degrades_to_polling(self):
        class ExplodingPubSub(FakePubSub):
            async def get_message(self, ignore_subscribe_messages=True, timeout=None):
                raise ConnectionError("redis gone")

        class ExplodingRedis(FakeRedis):
            def pubsub(self):
                return ExplodingPubSub()

        subscriber = EventSubscriber(
            self.database, EventPublisher(ExplodingRedis()), poll_seconds=0.05,
        )
        collected = []

        async def consume():
            async for row in subscriber.stream(self.session_id, 0, idle_timeout=2.0):
                collected.append(row.sequence)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.2)
        await self.append(self.make_event(self.session_id))
        await asyncio.sleep(0.4)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertIn(1, collected)


if __name__ == "__main__":
    unittest.main()
