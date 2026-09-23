"""T11 脱敏（checklist C55–C58）。

分三层：规则本身、结构化/异常脱敏、以及**接入点**——事件落库、审计落库、
日志、API 错误响应。最后一层才是真正决定"密钥会不会漏出去"的地方，
所以它跑在真实 SQLite 文件上而不是打桩。
"""

import importlib.util
import logging
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from huicode.memory.scrub import MARKER, scrub_secrets
from huicode.server.api.errors import ApiError
from huicode.server.app import create_app
from huicode.server.config import RuntimeLimits, ServerSettings
from huicode.server.db.models import AuditLog
from huicode.server.db.session import Database
from huicode.server.domain import audit as audit_domain
from huicode.server.events import store as event_store
from huicode.server.events.types import RuntimeEvent
from huicode.server.runtime import scrubbing
from huicode.server.runtime.scrubber import (
    SecretScrubFilter,
    SecretScrubber,
    install_log_scrubbing,
)

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
TEST_SECRET = "test-secret-0123456789abcdefghijklmnop"
FAKE_OPENAI_KEY = "sk-abcdefghijklmnopqrstuvwxyz012345"
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"


def _load(name):
    spec = importlib.util.spec_from_file_location(name.stem, VERSIONS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PatternTests(unittest.TestCase):
    """每一类都要能被认出来，且**认完之后再脱一次结果不变**。"""

    CASES = (
        ("api key 赋值", f"api_key={FAKE_OPENAI_KEY}"),
        ("带前缀的键名", "openai_api_key=abcdefghijklmnop"),
        ("Authorization Bearer", f"Authorization: Bearer {FAKE_OPENAI_KEY}"),
        ("裸 Bearer", f"Bearer {FAKE_JWT}"),
        ("Cookie", "Cookie: session=abcdef123456; Path=/"),
        ("Password", "password: hunter2hunter2"),
        ("token 赋值", "token=abcdef1234567890"),
        ("私钥块", "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----"),
        ("连接串密码", "postgresql+asyncpg://user:s3cr3tp4ss@127.0.0.1:5432/db"),
        ("JWT", FAKE_JWT),
        ("GitHub token", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"),
        ("AWS key id", "AKIAIOSFODNN7EXAMPLE"),
        ("敏感环境变量", "HUICODE_JWT_SECRET=abcdefghijklmnopqrstuvwxyz123456"),
        ("JSON 里的键", '{"access_token": "abcdefghijklmnop", "name": "demo"}'),
    )

    def test_each_category_is_redacted(self):
        for label, text in self.CASES:
            with self.subTest(category=label):
                result = scrub_secrets(text)
                self.assertIn(MARKER, result, f"{label} 没有被脱敏")
                for fragment in (FAKE_OPENAI_KEY, FAKE_JWT, "s3cr3tp4ss", "hunter2hunter2"):
                    self.assertNotIn(fragment, result)
                self.assertNotEqual(result, text)

    def test_scrubbing_is_idempotent(self):
        """重复施加不能改变结果——落库/审计/响应可能过不止一道。"""
        for label, text in self.CASES:
            with self.subTest(category=label):
                once = scrub_secrets(text)
                self.assertEqual(scrub_secrets(once), once)

    def test_ordinary_config_values_are_not_touched(self):
        """误脱敏会让日志没法读，这几条是最容易被规则误伤的常见配置。"""
        for text in (
            "PORT=8000",
            "token_count=5",
            "max_tokens=4096",
            "model=gpt-4o",
            "temperature=0.2",
            "no secret here at all",
            "the token budget is exhausted",
        ):
            with self.subTest(text=text):
                self.assertEqual(scrub_secrets(text), text)


class StructureTests(unittest.TestCase):
    def test_sensitive_key_masks_the_whole_value_regardless_of_shape(self):
        """纯文本规则看不穿结构：这里没有任何 `password=...` 形态的文本。"""
        scrubber = SecretScrubber()
        result = scrubber.scrub_payload({
            "password": {"nested": "hunter2hunter2"},
            "items": [{"api_key": "abcdefghijklmnop"}],
            "name": "demo",
        })
        self.assertEqual(result["password"], MARKER)
        self.assertEqual(result["items"][0]["api_key"], MARKER)
        self.assertEqual(result["name"], "demo")

    def test_keys_that_merely_contain_a_sensitive_word_are_kept(self):
        scrubber = SecretScrubber()
        result = scrubber.scrub_payload({"max_tokens": 4096, "token_count": 3})
        self.assertEqual(result, {"max_tokens": 4096, "token_count": 3})

    def test_non_string_values_survive(self):
        scrubber = SecretScrubber()
        result = scrubber.scrub_payload({"count": 3, "ok": True, "ratio": 0.5, "none": None})
        self.assertEqual(result, {"count": 3, "ok": True, "ratio": 0.5, "none": None})

    def test_known_secrets_are_redacted_by_literal_value(self):
        """形状不匹配任何规则的密钥，靠配置里的真实值兜住。"""
        secret = "a-very-custom-secret-value"
        scrubber = SecretScrubber([secret])
        self.assertNotIn(secret, scrubber.scrub_text(f"用了 {secret} 去连"))
        self.assertIn(MARKER, scrubber.scrub_text(f"用了 {secret} 去连"))

    def test_short_known_secrets_are_ignored_to_avoid_masking_everything(self):
        scrubber = SecretScrubber(["abc"])
        self.assertEqual(scrubber.scrub_text("abc def"), "abc def")

    def test_from_settings_picks_up_the_jwt_secret_and_url_password(self):
        scrubber = SecretScrubber.from_settings(_settings())
        self.assertIn(MARKER, scrubber.scrub_text(f"secret is {TEST_SECRET}"))
        self.assertIn(MARKER, scrubber.scrub_text("url is postgresql://u:dbpassword123@h/db"))

    def test_scrub_event_returns_a_copy_and_keeps_metadata(self):
        event = RuntimeEvent(
            type="tool_call_finished", session_id=uuid4(), sequence=3,
            payload={"summary": f"用了 {FAKE_OPENAI_KEY}"},
        )
        scrubbed = SecretScrubber().scrub_event(event)
        self.assertNotIn(FAKE_OPENAI_KEY, scrubbed.payload["summary"])
        self.assertIn(MARKER, scrubbed.payload["summary"])
        # 原对象不被改动，其余字段保持
        self.assertIn(FAKE_OPENAI_KEY, event.payload["summary"])
        self.assertEqual(scrubbed.sequence, event.sequence)
        self.assertEqual(scrubbed.session_id, event.session_id)

    def test_scrub_exception_keeps_the_type_but_drops_the_value(self):
        error = ValueError(f"连接失败：password=hunter2hunter2")
        rendered = SecretScrubber().scrub_exception(error)
        self.assertTrue(rendered.startswith("ValueError: "))
        self.assertNotIn("hunter2hunter2", rendered)
        self.assertIn(MARKER, rendered)

    def test_scrub_payload_rejects_non_mappings(self):
        scrubber = SecretScrubber()
        self.assertEqual(scrubber.scrub_payload(None), {})
        self.assertEqual(scrubber.scrub_payload(["a"]), {})


class LogFilterTests(unittest.TestCase):
    def test_filter_redacts_the_formatted_message(self):
        scrubber = SecretScrubber()
        record = logging.LogRecord(
            "t", logging.INFO, __file__, 1,
            "调用失败 key=%s", (FAKE_OPENAI_KEY,), None,
        )
        self.assertTrue(SecretScrubFilter(scrubber).filter(record))
        self.assertNotIn(FAKE_OPENAI_KEY, record.getMessage())
        self.assertIn(MARKER, record.getMessage())

    def test_scrubbed_logger_output_contains_no_secret(self):
        logger = logging.getLogger("huicode.server.test.scrub")
        install_log_scrubbing("huicode.server.test.scrub", SecretScrubber())
        with self.assertLogs("huicode.server.test.scrub", level="INFO") as captured:
            logger.info("database url is postgresql://u:dbpassword123@h/db")
        self.assertNotIn("dbpassword123", " ".join(captured.output))
        self.assertIn(MARKER, " ".join(captured.output))

    def test_installing_twice_does_not_stack_filters(self):
        name = "huicode.server.test.idempotent"
        install_log_scrubbing(name, SecretScrubber())
        install_log_scrubbing(name, SecretScrubber())
        filters = [f for f in logging.getLogger(name).filters if isinstance(f, SecretScrubFilter)]
        self.assertEqual(len(filters), 1)


def _settings(**overrides):
    base = tempfile.mkdtemp()
    values = dict(
        environment="test",
        database_url="postgresql+asyncpg://u:dbpassword123@127.0.0.1:5432/huicode",
        redis_url="redis://127.0.0.1:6379/0",
        jwt_secret=TEST_SECRET,
        project_root=Path(base),
        cors_origins=(),
        log_level="INFO",
        limits=RuntimeLimits(),
    )
    values.update(overrides)
    return ServerSettings(**values)


class StorageTests(unittest.IsolatedAsyncioTestCase):
    """接入点：密钥不能进数据库、不能进 API 响应。"""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "scrub.db"
        engine = create_engine(f"sqlite:///{path.as_posix()}")
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            for name in ("0001_initial.py", "0002_auth_tokens.py"):
                module = _load(Path(name))
                module.op = Operations(context)
                module.upgrade()
        engine.dispose()

        self.database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
        scrubbing.configure(SecretScrubber.from_settings(_settings()))
        self.session_id, self.workspace_id, self.user_id = await self._seed()

    async def asyncTearDown(self):
        scrubbing.reset()
        await self.database.close()
        self.temp.cleanup()

    async def _seed(self):
        from huicode.server.db.models import Project, Session, User, Workspace, WorkspaceMember

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

    async def test_event_payload_is_scrubbed_before_it_reaches_the_database(self):
        """C56/C57：工具输出或模型消息里的密钥不能落库。"""
        event = RuntimeEvent(
            type="tool_call_finished", session_id=self.session_id, sequence=0,
            payload={"summary": f"调用 {FAKE_OPENAI_KEY} 失败", "ok": False},
        )
        async with self.database.transaction() as session:
            row = await event_store.append(session, event)

        async with self.database.transaction() as session:
            stored = await session.get(type(row), row.id)
        self.assertNotIn(FAKE_OPENAI_KEY, str(stored.payload))
        self.assertIn(MARKER, stored.payload["summary"])
        self.assertFalse(stored.payload["ok"])

    async def test_tool_arguments_are_scrubbed_on_the_way_to_the_database(self):
        """T7 引入工具参数值 + T11 脱敏，两条合起来才成立。

        单独验证 mapper 带上参数值（tests/server/test_event_types.py）说明不了
        "落库安全"；单独验证 store 脱敏说明不了"参数真的经过了这条路"。
        这条把两端接起来。
        """
        from huicode.agent_events import AgentEvent
        from huicode.server.events.mapper import map_agent_event
        from huicode.providers.base import ToolCall

        mapped = map_agent_event(
            AgentEvent(
                kind="tool_call",
                tool_call=ToolCall("c1", "Write", {"path": "a.py", "content": FAKE_OPENAI_KEY}),
            ),
            session_id=self.session_id, sequence=0,
        )
        self.assertEqual(mapped.payload["arguments"]["content"], FAKE_OPENAI_KEY)

        async with self.database.transaction() as session:
            row = await event_store.append(session, mapped)

        async with self.database.transaction() as session:
            stored = await session.get(type(row), row.id)
        self.assertNotIn(FAKE_OPENAI_KEY, str(stored.payload))
        self.assertIn(MARKER, stored.payload["arguments"]["content"])

    async def test_audit_metadata_is_scrubbed(self):
        async with self.database.transaction() as session:
            await audit_domain.record(
                session, workspace_id=self.workspace_id, actor_user_id=self.user_id,
                action="project.path_rejected", resource_type="project",
                request_id="req-1", metadata={"reason": f"用了 {TEST_SECRET}"},
            )

        async with self.database.transaction() as session:
            stored = await session.scalar(select(AuditLog.audit_metadata))
        self.assertNotIn(TEST_SECRET, str(stored))
        self.assertIn(MARKER, stored["reason"])

    async def test_unscrubbed_payload_still_contains_the_value_before_wiring(self):
        """反向对照：不经过 store，值当然还在。用来证明上面那条不是空断言。"""
        raw = {"summary": f"调用 {FAKE_OPENAI_KEY} 失败"}
        self.assertIn(FAKE_OPENAI_KEY, str(raw))


class ApiResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "resp.db"
        engine = create_engine(f"sqlite:///{path.as_posix()}")
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            for name in ("0001_initial.py", "0002_auth_tokens.py"):
                module = _load(Path(name))
                module.op = Operations(context)
                module.upgrade()
        engine.dispose()

        self.app = create_app(_settings(database_url=f"sqlite+aiosqlite:///{path.as_posix()}"))
        # 探针路由：抛出一个把配置值拼进消息的错误，验证处理器会脱敏。
        probe = APIRouter()

        @probe.get("/probe/leaky")
        async def leaky():
            raise ApiError(400, "leaky_error", f"连接失败 password=hunter2hunter2 key={FAKE_OPENAI_KEY}")

        self.app.include_router(probe)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        scrubbing.reset()
        self.temp.cleanup()

    def test_error_response_is_scrubbed(self):
        """C58：错误响应不能带敏感配置原文。"""
        response = self.client.get("/probe/leaky")
        self.assertEqual(response.status_code, 400)
        body = response.text
        self.assertNotIn("hunter2hunter2", body)
        self.assertNotIn(FAKE_OPENAI_KEY, body)
        self.assertIn(MARKER, body)
        self.assertEqual(response.json()["error"]["code"], "leaky_error")


if __name__ == "__main__":
    unittest.main()
