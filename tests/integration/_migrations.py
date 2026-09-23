"""集成测试共用的迁移执行助手。

被 tests/integration 下多个文件使用：真库上的迁移验证、以及需要"库结构已就绪"的
接口级集成测试。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def load_migration_chain():
    """按 down_revision 串成执行顺序；链断直接报错，不静默少跑。"""
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


def apply_on_sync_connection(sync_connection, direction: str = "upgrade") -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    context = MigrationContext.configure(sync_connection)
    chain = load_migration_chain()
    if direction == "downgrade":
        chain = list(reversed(chain))
    for module in chain:
        module.op = Operations(context)
        getattr(module, direction)()


async def reset_database(engine: AsyncEngine) -> None:
    """清空 public schema 并升级到 head。

    先尝试正常降级；库里有残留或不一致时退回 DROP SCHEMA。
    只用于专用测试库——它会删掉 public schema 下的所有东西。
    """
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda c: apply_on_sync_connection(c, "downgrade"))
    except Exception:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    async with engine.begin() as connection:
        await connection.run_sync(apply_on_sync_connection)
