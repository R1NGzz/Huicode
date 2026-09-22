"""在真实 PostgreSQL 上执行迁移链（checklist C68 / C73）。

**为什么必须有这个文件。** T3/T4/T5 的全部验证都跑在 SQLite 上，而 SQLite 与
PostgreSQL 的差异不是细节：SQLite 不保存 tzinfo（T5 踩到过）、没有真正的并发锁、
类型系统宽松、`json` 与 `jsonb` 的区分根本不存在。结构一致性用 SQLite 验是有效的，
但"迁移在目标数据库上能否执行"只有真库能回答。

默认跳过。启用：

    $env:HUICODE_TEST_DATABASE_URL="postgresql+asyncpg://huicode:huicode-dev-password@localhost:5432/huicode"
    .\\.venv\\Scripts\\python.exe -m pytest tests/integration -v

启动数据库的容器命令见 docs/web-studio-local-development.md。
"""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from huicode.server.db.models import Base

TEST_DATABASE_URL = os.environ.get("HUICODE_TEST_DATABASE_URL", "").strip()
VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"

EXPECTED_TABLES = set(Base.metadata.tables) | {"alembic_version"}

# 迁移在 PostgreSQL 上真正建出来的类型。写死期望值是有意的：
# 这些是当初在 SQLite 上无法确认、只能靠真库回答的部分。
EXPECTED_TYPES = {
    ("users", "id"): "uuid",
    ("users", "created_at"): "timestamp with time zone",
    ("users", "is_active"): "boolean",
    ("runs", "prompt"): "text",
    ("runs", "lease_expires_at"): "timestamp with time zone",
    ("session_events", "payload"): "json",
    ("refresh_tokens", "expires_at"): "timestamp with time zone",
}


def load_migration_chain():
    modules = []
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "revision"):
            modules.append(module)
    ordered, pending = [], list(modules)
    while pending:
        for module in pending:
            parent = module.down_revision
            if parent is None or any(done.revision == parent for done in ordered):
                ordered.append(module)
                pending.remove(module)
                break
        else:
            raise AssertionError(f"迁移链断裂：{[m.revision for m in pending]}")
    return ordered


def _apply(sync_connection, direction="upgrade"):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    context = MigrationContext.configure(sync_connection)
    chain = load_migration_chain()
    if direction == "downgrade":
        chain = list(reversed(chain))
    for module in chain:
        module.op = Operations(context)
        getattr(module, direction)()


@unittest.skipUnless(TEST_DATABASE_URL, "未设置 HUICODE_TEST_DATABASE_URL，跳过真库集成测试")
class PostgresMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(TEST_DATABASE_URL)
        # 从干净状态开始：先把可能存在的旧版本降掉。
        try:
            async with self.engine.begin() as connection:
                await connection.run_sync(lambda c: _apply(c, "downgrade"))
        except Exception:
            # 首次运行或库里有残留时，直接清掉 schema。
            async with self.engine.begin() as connection:
                await connection.execute(text("DROP SCHEMA public CASCADE"))
                await connection.execute(text("CREATE SCHEMA public"))

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _upgrade(self):
        async with self.engine.begin() as connection:
            await connection.run_sync(lambda c: _apply(c, "upgrade"))

    async def _tables(self):
        async with self.engine.connect() as connection:
            rows = await connection.execute(
                text("select tablename from pg_tables where schemaname='public'")
            )
            return {row[0] for row in rows}

    async def test_migration_chain_runs_on_real_postgres(self):
        await self._upgrade()
        self.assertEqual(await self._tables(), EXPECTED_TABLES)

    async def test_downgrade_and_upgrade_round_trip(self):
        """T4 的验收要求"在空数据库执行升级和降级"；这条只能在真库上做。"""
        await self._upgrade()
        async with self.engine.begin() as connection:
            await connection.run_sync(lambda c: _apply(c, "downgrade"))
        remaining = await self._tables()
        self.assertEqual(remaining, {"alembic_version"}, f"降级后仍有残留：{remaining}")

        await self._upgrade()
        self.assertEqual(await self._tables(), EXPECTED_TABLES)

    async def test_column_types_are_postgres_native(self):
        """确认迁移不是按 SQLite 的类型生成的。"""
        await self._upgrade()
        async with self.engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "select table_name, column_name, data_type from information_schema.columns "
                    "where table_schema='public'"
                )
            )
            actual = {(r[0], r[1]): r[2] for r in rows}
        for key, expected in EXPECTED_TYPES.items():
            self.assertEqual(actual.get(key), expected, f"{key} 类型不符")

    async def test_unique_constraints_and_replay_indexes_exist(self):
        await self._upgrade()
        async with self.engine.connect() as connection:
            constraints = {
                r[0]
                for r in await connection.execute(
                    text(
                        "select conname from pg_constraint "
                        "where connamespace='public'::regnamespace and contype='u'"
                    )
                )
            }
            indexes = {
                r[0]
                for r in await connection.execute(
                    text("select indexname from pg_indexes where schemaname='public'")
                )
            }
        self.assertIn("uq_session_events_session_id_sequence", constraints)
        self.assertIn("uq_runs_session_id_idempotency_key", constraints)
        self.assertIn("uq_tool_approvals_run_id_tool_call_id", constraints)
        # SSE 断线补偿与 T15 恢复扫描依赖的两个索引
        self.assertIn("ix_sessions_workspace_id_updated_at", indexes)
        self.assertIn("ix_runs_status_lease_expires_at", indexes)

    async def test_json_payload_behaviour_on_postgres(self):
        """payload 建出来是 json 而不是 jsonb。

        这条测试的作用是**把这个事实钉住**：SQLAlchemy 的 sa.JSON 在 PostgreSQL 上
        映射为 json（保留原始文本、不可索引），要 jsonb 需显式用 JSONB。
        当前选择见 T4 学习记录的说明；若将来改为 JSONB，这条断言会提醒改这里。
        """
        await self._upgrade()
        async with self.engine.connect() as connection:
            data_type = await connection.scalar(
                text(
                    "select data_type from information_schema.columns "
                    "where table_schema='public' and table_name='session_events' "
                    "and column_name='payload'"
                )
            )
        self.assertEqual(data_type, "json")
