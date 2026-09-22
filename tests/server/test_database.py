import asyncio
import tempfile
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import String, Uuid, func, select
from sqlalchemy.orm import Mapped, mapped_column

from huicode.server.db.base import Base, IdentityMixin, TimestampMixin
from huicode.server.db.repositories import WorkspaceRepository
from huicode.server.db.session import Database


class Probe(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "test_transaction_probe"
    workspace_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database("sqlite+aiosqlite:///" + (Path(self.temp.name) / "test.db").as_posix())
        async with self.database.engine.begin() as connection:
            await connection.run_sync(Probe.__table__.create)
        self.workspace = uuid4()

    async def asyncTearDown(self):
        await self.database.close()
        self.temp.cleanup()

    async def count(self):
        async with self.database.transaction() as session:
            return await session.scalar(select(func.count()).select_from(Probe))

    async def test_commit_visible_from_new_session_and_defaults(self):
        async with self.database.transaction() as session:
            row = Probe(workspace_id=self.workspace, name="committed")
            WorkspaceRepository(session, self.workspace).add(row)
        self.assertIsInstance(row.id, UUID)
        self.assertIsNotNone(row.created_at)
        self.assertEqual(await self.count(), 1)
        await self.database.ping()

    async def test_exception_rolls_back_flushed_changes(self):
        with self.assertRaisesRegex(RuntimeError, "business failure"):
            async with self.database.transaction() as session:
                session.add(Probe(workspace_id=self.workspace, name="rollback"))
                await session.flush()
                raise RuntimeError("business failure")
        self.assertEqual(await self.count(), 0)

    async def test_task_cancellation_rolls_back(self):
        flushed = asyncio.Event()

        async def operation():
            async with self.database.transaction() as session:
                session.add(Probe(workspace_id=self.workspace, name="cancelled"))
                await session.flush()
                flushed.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(operation())
        await asyncio.wait_for(flushed.wait(), timeout=3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(await self.count(), 0)

    async def test_scoped_get_and_cross_workspace_write_rejection(self):
        async with self.database.transaction() as session:
            row = Probe(workspace_id=self.workspace, name="private")
            session.add(row)
        async with self.database.transaction() as session:
            other = WorkspaceRepository(session, uuid4())
            self.assertIsNone(await other.get(Probe, row.id))
            with self.assertRaises(ValueError):
                other.add(Probe(workspace_id=self.workspace, name="forbidden"))
            self.assertIsNotNone(await WorkspaceRepository(session, self.workspace).get(Probe, row.id))

    async def test_two_repositories_share_one_business_transaction(self):
        with self.assertRaises(RuntimeError):
            async with self.database.transaction() as session:
                first = WorkspaceRepository(session, self.workspace)
                second = WorkspaceRepository(session, self.workspace)
                first.add(Probe(workspace_id=self.workspace, name="first"))
                second.add(Probe(workspace_id=self.workspace, name="second"))
                await session.flush()
                raise RuntimeError("second operation failed")
        self.assertEqual(await self.count(), 0)
