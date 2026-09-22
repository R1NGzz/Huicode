"""T5 认证、令牌与工作区角色。

跑在真实 SQLite 文件上：迁移 0001 + 0002 先建表，应用再通过自己的连接池接入。
这比打桩更能发现问题——例如事务边界、唯一约束和登录时的真实查询。

仍然不是 PostgreSQL；并发与隔离级别相关行为不在本文件的覆盖范围内。
"""

import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from huicode.server.api.errors import forbidden
from huicode.server.app import create_app
from huicode.server.auth import permissions, tokens
from huicode.server.auth.dependencies import require_workspace_role
from huicode.server.config import RuntimeLimits, ServerSettings
from huicode.server.db.models import WorkspaceMember

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
TEST_SECRET = "test-secret-0123456789abcdefghijklmnop"
PASSWORD = "correct horse battery staple"


def _load(filename):
    spec = importlib.util.spec_from_file_location(filename.stem, VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "auth.db"
        self.project_root = Path(self.temp.name) / "workspaces"
        self.project_root.mkdir()

        # 用迁移建表，顺带验证 0001 → 0002 能顺序执行。
        engine = create_engine(f"sqlite:///{self.db_path.as_posix()}")
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            for name in ("0001_initial.py", "0002_auth_tokens.py"):
                module = _load(Path(name))
                module.op = Operations(context)
                module.upgrade()
        engine.dispose()

        settings = ServerSettings(
            environment="test",
            database_url=f"sqlite+aiosqlite:///{self.db_path.as_posix()}",
            redis_url="redis://localhost:6379/0",
            jwt_secret=TEST_SECRET,
            project_root=self.project_root,
            cors_origins=(),
            log_level="INFO",
            limits=RuntimeLimits(),
        )
        self.app = create_app(settings)

        # 角色依赖目前没有真实路由挂载（工作区/项目接口属于 T6），
        # 这里挂一个探针路由，把依赖本身的行为测掉。
        @self.app.get("/probe/{workspace_id}")
        async def probe(member: WorkspaceMember = Depends(require_workspace_role("admin"))):
            return {"role": member.role, "workspace_id": str(member.workspace_id)}

        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    # ---------- helpers ----------

    def register(self, email="alice@example.com", password=PASSWORD, display_name="Alice"):
        return self.client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "display_name": display_name},
        )

    def login(self, email="alice@example.com", password=PASSWORD):
        return self.client.post("/api/auth/login", json={"email": email, "password": password})

    def auth_header(self, token):
        return {"Authorization": f"Bearer {token}"}

    # ---------- registration ----------

    def test_register_creates_user_default_workspace_and_owner(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIn("access_token", body)
        self.assertIn("refresh_token", body)

        me = self.client.get("/api/auth/me", headers=self.auth_header(body["access_token"]))
        self.assertEqual(me.status_code, 200)
        profile = me.json()
        self.assertEqual(profile["email"], "alice@example.com")
        self.assertEqual(len(profile["workspaces"]), 1)
        self.assertEqual(profile["workspaces"][0]["role"], "owner")

    def test_register_normalises_email_case(self):
        self.register(email="Alice@Example.COM")
        self.assertEqual(self.login(email="alice@example.com").status_code, 200)
        # 归一化后是同一个账号，重复注册必须被拒。
        self.assertEqual(self.register(email="ALICE@example.com").status_code, 409)

    def test_register_rejects_duplicate_email(self):
        self.register()
        response = self.register()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "email_taken")

    def test_register_rejects_weak_password_and_bad_email(self):
        short = self.register(password="short")
        self.assertEqual(short.status_code, 422)
        self.assertEqual(short.json()["error"]["code"], "validation_error")

        bad_email = self.register(email="not-an-email")
        self.assertEqual(bad_email.status_code, 422)

    # ---------- login ----------

    def test_login_with_wrong_password_is_rejected(self):
        self.register()
        response = self.login(password="wrong password entirely")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credentials")

    def test_unknown_email_and_wrong_password_are_indistinguishable(self):
        """两种失败必须完全同形，否则登录接口就是一个账号枚举器。"""
        self.register()
        wrong_password = self.login(password="wrong password entirely")
        unknown_email = self.login(email="nobody@example.com")
        self.assertEqual(wrong_password.status_code, unknown_email.status_code)
        self.assertEqual(wrong_password.json()["error"], unknown_email.json()["error"])

    # ---------- access token ----------

    def test_me_requires_a_token(self):
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthenticated")

    def test_expired_access_token_is_rejected(self):
        self.register()
        user_id = UUID(self.client.get("/api/auth/me", headers=self.auth_header(
            self.login().json()["access_token"])).json()["id"])
        stale = tokens.create_access_token(
            TEST_SECRET, user_id, issued_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        response = self.client.get("/api/auth/me", headers=self.auth_header(stale))
        self.assertEqual(response.status_code, 401)

    def test_token_signed_with_another_secret_is_rejected(self):
        body = self.register().json()
        forged = tokens.create_access_token("attacker-secret-0123456789abcdefgh", uuid4())
        self.assertEqual(
            self.client.get("/api/auth/me", headers=self.auth_header(forged)).status_code, 401
        )
        self.assertEqual(
            self.client.get("/api/auth/me", headers=self.auth_header(body["refresh_token"])).status_code,
            401,
        )

    def test_refresh_token_cannot_be_used_as_access_token(self):
        """refresh token 是不透明串，拿它当 Bearer 必须失败而不是被误当成合法令牌。"""
        body = self.register().json()
        response = self.client.get("/api/auth/me", headers=self.auth_header(body["refresh_token"]))
        self.assertEqual(response.status_code, 401)

    # ---------- refresh rotation ----------

    def test_refresh_rotates_tokens_and_old_one_stops_working(self):
        first = self.register().json()
        rotated = self.client.post(
            "/api/auth/refresh", json={"refresh_token": first["refresh_token"]}
        )
        self.assertEqual(rotated.status_code, 200)
        second = rotated.json()
        self.assertNotEqual(second["refresh_token"], first["refresh_token"])

        # 新 access token 可用
        self.assertEqual(
            self.client.get("/api/auth/me", headers=self.auth_header(second["access_token"])).status_code,
            200,
        )
        # 旧 refresh token 已撤销
        replay = self.client.post(
            "/api/auth/refresh", json={"refresh_token": first["refresh_token"]}
        )
        self.assertEqual(replay.status_code, 401)

    def test_replaying_a_rotated_token_revokes_the_whole_chain(self):
        """已轮换的令牌被重放时，整条链都要失效——否则窃取者与被窃者可以并存。"""
        first = self.register().json()
        second = self.client.post(
            "/api/auth/refresh", json={"refresh_token": first["refresh_token"]}
        ).json()

        self.client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})

        after = self.client.post("/api/auth/refresh", json={"refresh_token": second["refresh_token"]})
        self.assertEqual(after.status_code, 401)

    def test_logout_revokes_refresh_token_and_is_idempotent(self):
        body = self.register().json()
        first = self.client.post("/api/auth/logout", json={"refresh_token": body["refresh_token"]})
        self.assertEqual(first.status_code, 204)
        second = self.client.post("/api/auth/logout", json={"refresh_token": body["refresh_token"]})
        self.assertEqual(second.status_code, 204)

        refused = self.client.post("/api/auth/refresh", json={"refresh_token": body["refresh_token"]})
        self.assertEqual(refused.status_code, 401)

    # ---------- secrets in responses and logs ----------

    def test_password_and_tokens_never_appear_in_responses_or_logs(self):
        with self.assertLogs("huicode.server.requests", level="INFO") as captured:
            registered = self.register()
            logged_in = self.login()
        blob = " ".join(captured.output)
        for secret in (PASSWORD, registered.json()["access_token"], registered.json()["refresh_token"]):
            self.assertNotIn(secret, blob)
        # 响应里也不该出现密码或哈希
        self.assertNotIn(PASSWORD, registered.text)
        self.assertNotIn("password_hash", registered.text)
        self.assertNotIn(PASSWORD, logged_in.text)

    # ---------- workspace roles ----------

    def _set_role(self, workspace_id, user_id, role):
        import asyncio

        from sqlalchemy import update
        from sqlalchemy.ext.asyncio import create_async_engine

        async def run():
            engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path.as_posix()}")
            async with engine.begin() as connection:
                await connection.execute(
                    update(WorkspaceMember)
                    .where(
                        WorkspaceMember.workspace_id == workspace_id,
                        WorkspaceMember.user_id == user_id,
                    )
                    .values(role=role)
                )
            await engine.dispose()

        asyncio.run(run())

    def test_role_dependency_allows_and_denies_by_rank(self):
        registered = self.register(email="owner@example.com").json()
        header = self.auth_header(registered["access_token"])
        profile = self.client.get("/api/auth/me", headers=header).json()
        workspace_id = UUID(profile["workspaces"][0]["id"])
        user_id = UUID(profile["id"])

        # 注册者默认是 owner，admin 门槛应通过
        allowed = self.client.get(f"/probe/{workspace_id}", headers=header)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["role"], "owner")

        # 降成 viewer 后同一请求被拒。角色是每次请求现查的，改库立即生效，
        # 不需要重新登录——这正是把角色放数据库而不是塞进 JWT 的理由。
        self._set_role(workspace_id, user_id, "viewer")
        denied = self.client.get(f"/probe/{workspace_id}", headers=header)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], "forbidden")

        # 升回 admin 又可以通过，确认判据是等级而不是"是成员就算"
        self._set_role(workspace_id, user_id, "admin")
        self.assertEqual(self.client.get(f"/probe/{workspace_id}", headers=header).status_code, 200)

    def test_non_member_gets_404_not_403(self):
        """非成员与权限不足必须同形，否则可以拿状态码探测 workspace_id 是否存在。"""
        stranger = self.register(email="stranger@example.com").json()
        response = self.client.get(
            f"/probe/{uuid4()}", headers=self.auth_header(stranger["access_token"])
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_unknown_role_ranks_below_everything(self):
        self.assertFalse(permissions.has_at_least("root", "viewer"))
        self.assertFalse(permissions.has_at_least("", "viewer"))
        self.assertTrue(permissions.has_at_least("admin", "member"))
        self.assertTrue(permissions.has_at_least("owner", "owner"))


class PasswordAndTokenUnitTests(unittest.TestCase):
    def test_hash_is_not_reversible_and_verifies(self):
        from huicode.server.auth import passwords

        digest = passwords.hash_password(PASSWORD)
        self.assertNotIn(PASSWORD, digest)
        self.assertTrue(passwords.verify_password(digest, PASSWORD))
        self.assertFalse(passwords.verify_password(digest, "something else"))

    def test_verify_returns_false_on_corrupt_hash(self):
        from huicode.server.auth import passwords

        self.assertFalse(passwords.verify_password("not-a-hash", PASSWORD))

    def test_password_policy_bounds(self):
        from huicode.server.auth import passwords

        with self.assertRaises(passwords.PasswordPolicyError):
            passwords.hash_password("short")
        with self.assertRaises(passwords.PasswordPolicyError):
            passwords.hash_password("x" * 2000)

    def test_refresh_hash_is_stable_and_not_the_raw_token(self):
        raw = tokens.generate_refresh_token()
        self.assertNotEqual(tokens.hash_refresh_token(raw), raw)
        self.assertEqual(tokens.hash_refresh_token(raw), tokens.hash_refresh_token(raw))
        self.assertEqual(len(tokens.hash_refresh_token(raw)), 64)
        self.assertNotEqual(tokens.generate_refresh_token(), raw)


if __name__ == "__main__":
    unittest.main()
