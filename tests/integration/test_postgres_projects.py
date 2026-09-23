"""T6 工作区 / 项目 / 路径拒绝在真实 PostgreSQL 上的冒烟验证。

SQLite 版本在 tests/server/test_projects_api.py。这里重复一小部分覆盖面，是为了
抓住只在 PostgreSQL 上才暴露的问题——最典型的是 `audit_logs.metadata`：
SQLAlchemy 的声明式基类把 `metadata` 用作保留属性，模型里把属性命名为
`audit_metadata`、列名保留 `metadata`，这条映射在 PG 上是否真的能写入，
SQLite 通过不代表 PG 通过（保留字、驱动参数绑定都可能不同）。

默认跳过，启用方式见 tests/integration/__init__.py。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from huicode.server.app import create_app
from huicode.server.config import RuntimeLimits, ServerSettings
from tests.integration._migrations import reset_database

TEST_DATABASE_URL = os.environ.get("HUICODE_TEST_DATABASE_URL", "").strip()
TEST_SECRET = "test-secret-0123456789abcdefghijklmnop"
PASSWORD = "correct horse battery staple"


def _run(coroutine):
    return asyncio.run(coroutine)


async def _fetch_actions(url: str) -> list[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(text("select action from audit_logs"))
            return [row[0] for row in rows]
    finally:
        await engine.dispose()


def _make_link(link: Path, target: Path) -> bool:
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True, text=True,
            )
            return result.returncode == 0 and link.exists()
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False


@unittest.skipUnless(TEST_DATABASE_URL, "未设置 HUICODE_TEST_DATABASE_URL，跳过真库集成测试")
class PostgresProjectsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.project_root = base / "workspaces"
        self.project_root.mkdir()
        (self.project_root / "demo").mkdir()
        (self.project_root / "other").mkdir()
        self.outside = base / "outside"
        self.outside.mkdir()

        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            _run(reset_database(engine))
        finally:
            _run(engine.dispose())

        settings = ServerSettings(
            environment="test",
            database_url=TEST_DATABASE_URL,
            redis_url="redis://localhost:6379/0",
            jwt_secret=TEST_SECRET,
            project_root=self.project_root,
            cors_origins=(),
            log_level="INFO",
            limits=RuntimeLimits(),
        )
        self.client = TestClient(create_app(settings))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def _token(self, email):
        response = self.client.post(
            "/api/auth/register",
            json={"email": email, "password": PASSWORD, "display_name": "tester"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["access_token"]

    def _headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _workspace(self, token):
        return self.client.get("/api/workspaces", headers=self._headers(token)).json()[0]["id"]

    def test_project_lifecycle_on_postgres(self):
        token = self._token("pg-owner@example.com")
        workspace_id = self._workspace(token)

        created = self.client.post(
            f"/api/workspaces/{workspace_id}/projects",
            headers=self._headers(token),
            json={"name": "真库项目", "workspace_path": "demo"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        project_id = created.json()["id"]

        renamed = self.client.patch(
            f"/api/projects/{project_id}", headers=self._headers(token), json={"name": "改名后"},
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["name"], "改名后")

        archived = self.client.post(
            f"/api/projects/{project_id}/archive", headers=self._headers(token),
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(archived.json()["status"], "archived")

        # audit_logs 的列名是 metadata，属性名是 audit_metadata。
        # 上面三次写操作各写一行审计；能读出来就说明这条映射在 PG 上成立。
        actions = _run(_fetch_actions(TEST_DATABASE_URL))
        self.assertIn("project.create", actions)
        self.assertIn("project.rename", actions)
        self.assertIn("project.archive", actions)

    def test_traversal_rejected_and_audited_on_postgres(self):
        token = self._token("pg-traversal@example.com")
        workspace_id = self._workspace(token)

        for attempt in ("../outside", "/etc", "C:/Windows", ".."):
            with self.subTest(attempt=attempt):
                response = self.client.post(
                    f"/api/workspaces/{workspace_id}/projects",
                    headers=self._headers(token),
                    json={"name": f"越界-{attempt}", "workspace_path": attempt},
                )
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["error"]["code"], "invalid_project_path")

        rejected = [a for a in _run(_fetch_actions(TEST_DATABASE_URL)) if a == "project.path_rejected"]
        self.assertEqual(len(rejected), 4, "非法路径的审计被回滚了")

    def test_link_escape_rejected_on_postgres(self):
        link = self.project_root / "escape"
        if not _make_link(link, self.outside):
            self.skipTest("当前环境无法创建 junction/symlink")

        token = self._token("pg-link@example.com")
        workspace_id = self._workspace(token)
        response = self.client.post(
            f"/api/workspaces/{workspace_id}/projects",
            headers=self._headers(token),
            json={"name": "链接逃逸", "workspace_path": "escape"},
        )
        self.assertEqual(response.status_code, 400, response.text)

    def test_workspace_isolation_on_postgres(self):
        owner_token = self._token("pg-a@example.com")
        workspace_id = self._workspace(owner_token)
        project_id = self.client.post(
            f"/api/workspaces/{workspace_id}/projects",
            headers=self._headers(owner_token),
            json={"name": "私密项目", "workspace_path": "demo"},
        ).json()["id"]

        stranger_token = self._token("pg-b@example.com")
        response = self.client.patch(
            f"/api/projects/{project_id}",
            headers=self._headers(stranger_token),
            json={"name": "篡改"},
        )
        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
