"""T4 核心业务模型与初始迁移。

用 SQLite 执行 0001_initial 的 upgrade/downgrade，再拿 models.py 的 metadata
和迁移建出来的schema 对比。SQLite 不能替代 PostgreSQL 的并发与时区行为，
但足以验证表、列、约束、外键和索引的结构一致。
"""

import importlib.util
import unittest
from pathlib import Path
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, insert, inspect, select
from sqlalchemy.exc import IntegrityError

from huicode.server.db.models import (
    Artifact,
    AuditLog,
    Base,
    Project,
    Run,
    Session,
    SessionEvent,
    ToolApproval,
    UsageRecord,
    User,
    Workspace,
    WorkspaceMember,
)

VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"

EXPECTED_TABLES = {
    "artifacts",
    "audit_logs",
    "projects",
    "refresh_tokens",
    "runs",
    "session_events",
    "sessions",
    "tool_approvals",
    "usage_records",
    "users",
    "workspace_members",
    "workspaces",
}


def load_migration_chain():
    """按 down_revision 把所有迁移串成执行顺序。

    不写死文件名：T5 加了 0002，之后还会有新的。硬编码列表每加一次迁移就得
    改一次测试，而漏改的表现是"测试通过但少跑了一个版本"。链断了直接报错。
    """
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
            raise AssertionError(
                f"迁移链断裂，无法确定顺序：{[m.revision for m in pending]}"
            )
    return ordered


def apply_migrations(connection, *, direction="upgrade"):
    context = MigrationContext.configure(connection)
    chain = load_migration_chain()
    if direction == "downgrade":
        chain = list(reversed(chain))
    for module in chain:
        module.op = Operations(context)
        getattr(module, direction)()


class ModelSchemaTests(unittest.TestCase):
    """迁移与模型的一致性，以及 upgrade / downgrade 可往返。"""

    def setUp(self):
        self.engine = create_engine("sqlite://")

        # SQLite 默认不校验外键，必须按连接打开，否则外键用例会假通过。
        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    def tearDown(self):
        self.engine.dispose()

    def _run(self, direction):
        with self.engine.begin() as connection:
            apply_migrations(connection, direction=direction)

    def test_migration_matches_model_metadata(self):
        """迁移建出来的 schema 与 models.py 的 metadata 之间不能有任何差异。

        差异为 0 才说明没人手抄错列名或漏掉索引；一旦模型改了而迁移没跟，
        这里会立刻失败。
        """
        self._run("upgrade")
        with self.engine.connect() as connection:
            diffs = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        self.assertEqual(diffs, [], f"迁移与模型不一致：{diffs}")

    def test_upgrade_creates_every_expected_table(self):
        self._run("upgrade")
        self.assertEqual(set(inspect(self.engine).get_table_names()), EXPECTED_TABLES)

    def test_downgrade_removes_everything(self):
        self._run("upgrade")
        self._run("downgrade")
        remaining = EXPECTED_TABLES & set(inspect(self.engine).get_table_names())
        self.assertEqual(remaining, set(), f"降级后仍有残留表：{remaining}")

    def test_workspace_scoped_indexes_exist(self):
        """工作区范围查询靠这些索引；索引名写错线上不会报错，只会变慢。"""
        self._run("upgrade")
        inspector = inspect(self.engine)
        expected = {
            "sessions": {"ix_sessions_workspace_id_updated_at"},
            "runs": {"ix_runs_status_lease_expires_at"},
            "session_events": {"uq_session_events_session_id_sequence"},
            "audit_logs": {"ix_audit_logs_workspace_id_created_at"},
        }
        for table, names in expected.items():
            actual = {item["name"] for item in inspector.get_indexes(table)}
            actual |= {item["name"] for item in inspector.get_unique_constraints(table)}
            missing = names - actual
            self.assertEqual(missing, set(), f"{table} 缺少索引/约束：{missing}")


class ModelBehaviourTests(unittest.TestCase):
    """建表后插入真实关联数据，确认外键、唯一约束和检查约束真的生效。"""

    def setUp(self):
        self.engine = create_engine("sqlite://")

        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        with self.engine.begin() as connection:
            apply_migrations(connection)

    def tearDown(self):
        self.engine.dispose()

    def _chain(self, connection, *, session_id=None, idempotency_key=None, status="queued"):
        """建一条 user → workspace → project → session → run 的完整链路。"""
        user_id, workspace_id, project_id = uuid4(), uuid4(), uuid4()
        run_id = session_id or uuid4()
        connection.execute(
            insert(User).values(
                id=user_id, email=f"{user_id}@example.com",
                password_hash="x", display_name="tester",
            )
        )
        connection.execute(insert(Workspace).values(id=workspace_id, name="w", created_by=user_id))
        connection.execute(
            insert(WorkspaceMember).values(workspace_id=workspace_id, user_id=user_id, role="owner")
        )
        connection.execute(
            insert(Project).values(
                id=project_id, workspace_id=workspace_id, name="p",
                workspace_path="demo", status="active", created_by=user_id,
            )
        )
        connection.execute(
            insert(Session).values(
                id=run_id, project_id=project_id, workspace_id=workspace_id,
                title="s", status="idle", created_by=user_id,
            )
        )
        run = uuid4()
        connection.execute(
            insert(Run).values(
                id=run, session_id=run_id, workspace_id=workspace_id, status=status,
                prompt="hi", idempotency_key=idempotency_key,
            )
        )
        return dict(
            user_id=user_id, workspace_id=workspace_id, project_id=project_id,
            session_id=run_id, run_id=run,
        )

    def test_full_chain_and_workspace_scoped_read(self):
        with self.engine.begin() as connection:
            ids = self._chain(connection)
            rows = connection.execute(
                select(Project.id).where(Project.workspace_id == ids["workspace_id"])
            ).scalars().all()
        self.assertEqual(rows, [ids["project_id"]])

    def test_session_event_sequence_is_unique_per_session(self):
        with self.engine.begin() as connection:
            ids = self._chain(connection)
            values = dict(
                workspace_id=ids["workspace_id"], session_id=ids["session_id"],
                run_id=ids["run_id"], sequence=1, event_type="run_queued",
                payload={"a": 1}, visibility="user",
            )
            connection.execute(insert(SessionEvent).values(**values))
            with self.assertRaises(IntegrityError):
                connection.execute(insert(SessionEvent).values(**values, id=uuid4()))

    def test_tool_approval_is_unique_per_run_and_tool_call(self):
        """C30 的幂等前提：同一 Run 的同一次工具调用只能有一条审批。"""
        with self.engine.begin() as connection:
            ids = self._chain(connection)
            values = dict(
                workspace_id=ids["workspace_id"], session_id=ids["session_id"],
                run_id=ids["run_id"], tool_call_id="call-1", tool_name="Write",
                summary="写文件", risk_level="high", status="pending",
            )
            connection.execute(insert(ToolApproval).values(**values))
            with self.assertRaises(IntegrityError):
                connection.execute(insert(ToolApproval).values(**values, id=uuid4()))

    def test_run_idempotency_key_unique_within_session_but_null_repeatable(self):
        """C31 要求同一幂等键只产生一个 Run；空键不应互相冲突。"""
        with self.engine.begin() as connection:
            ids = self._chain(connection, idempotency_key="key-1")
            with self.assertRaises(IntegrityError):
                connection.execute(
                    insert(Run).values(
                        session_id=ids["session_id"], workspace_id=ids["workspace_id"],
                        status="queued", prompt="again", idempotency_key="key-1",
                    )
                )
            for prompt in ("first", "second"):
                connection.execute(
                    insert(Run).values(
                        session_id=ids["session_id"], workspace_id=ids["workspace_id"],
                        status="queued", prompt=prompt,
                    )
                )
            count = connection.execute(
                select(Run.id).where(Run.session_id == ids["session_id"])
            ).scalars().all()
        self.assertEqual(len(count), 3)

    def test_usage_record_is_one_row_per_run(self):
        """C20 要求 Run、时间线、用量视图三处数字一致，按 Run 汇总成一行。"""
        with self.engine.begin() as connection:
            ids = self._chain(connection)
            values = dict(
                workspace_id=ids["workspace_id"], session_id=ids["session_id"],
                run_id=ids["run_id"], model="m", input_tokens=10, output_tokens=5,
                tool_calls=1, duration_ms=100,
            )
            connection.execute(insert(UsageRecord).values(**values))
            with self.assertRaises(IntegrityError):
                connection.execute(insert(UsageRecord).values(**values, id=uuid4()))

    def test_check_constraints_reject_unknown_enum_values(self):
        with self.engine.begin() as connection:
            ids = self._chain(connection)
            with self.assertRaises(IntegrityError):
                connection.execute(
                    insert(WorkspaceMember).values(
                        workspace_id=ids["workspace_id"], user_id=ids["user_id"], role="root",
                    )
                )
            with self.assertRaises(IntegrityError):
                connection.execute(
                    insert(SessionEvent).values(
                        workspace_id=ids["workspace_id"], session_id=ids["session_id"],
                        sequence=99, event_type="x", payload={}, visibility="public",
                    )
                )

    def test_foreign_keys_are_enforced(self):
        with self.engine.begin() as connection:
            with self.assertRaises(IntegrityError):
                connection.execute(
                    insert(Project).values(
                        workspace_id=uuid4(), name="orphan", workspace_path="x",
                        status="active", created_by=uuid4(),
                    )
                )

    def test_audit_log_keeps_metadata_column_name(self):
        """属性名是 audit_metadata，列名必须是 metadata，否则审计查询会对不上。"""
        self.assertIn("metadata", {c.name for c in AuditLog.__table__.columns})
        with self.engine.begin() as connection:
            ids = self._chain(connection)
            # 走 Table 构造插入：在 ORM 命名空间里 `metadata` 指向 Base.metadata，
            # insert(AuditLog).values(metadata=...) 会去找 MetaData 而不是这一列。
            # 这正是模型里把属性命名为 audit_metadata、列名保留 metadata 的原因。
            connection.execute(
                insert(AuditLog.__table__).values(
                    workspace_id=ids["workspace_id"], actor_user_id=ids["user_id"],
                    action="run.create", resource_type="run", resource_id=ids["run_id"],
                    request_id="req-1", metadata={"k": "v"},
                )
            )
            stored = connection.execute(select(AuditLog.audit_metadata)).scalar_one()
        self.assertEqual(stored, {"k": "v"})

    def test_artifact_row_links_to_run(self):
        with self.engine.begin() as connection:
            ids = self._chain(connection)
            connection.execute(
                insert(Artifact).values(
                    workspace_id=ids["workspace_id"], run_id=ids["run_id"], kind="diff",
                    relative_path="a.py", content_ref="artifacts/1", redacted=True,
                )
            )
            kind = connection.execute(select(Artifact.kind)).scalar_one()
        self.assertEqual(kind, "diff")


if __name__ == "__main__":
    unittest.main()
