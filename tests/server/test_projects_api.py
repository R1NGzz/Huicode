"""T6 工作区、项目与路径解析的接口测试。

对应 T6 的验收要求：跨工作区访问、路径穿越、符号链接逃逸、归档项目写入，
以及"所有非法路径都被拒绝并留下审计记录"。

跑在真实 SQLite 文件上，迁移链全量执行后由应用自己的连接池接入。
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from huicode.server.app import create_app
from huicode.server.config import RuntimeLimits, ServerSettings
from huicode.server.db.models import AuditLog

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
TEST_SECRET = "test-secret-0123456789abcdefghijklmnop"
PASSWORD = "correct horse battery staple"


def _load(name):
    spec = importlib.util.spec_from_file_location(name.stem, VERSIONS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


class ProjectsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.db_path = base / "studio.db"
        self.project_root = base / "workspaces"
        self.project_root.mkdir()
        (self.project_root / "demo").mkdir()
        (self.project_root / "other").mkdir()
        self.outside = base / "outside"
        self.outside.mkdir()

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
        self.client = TestClient(create_app(settings))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    # ---------- helpers ----------

    def _register(self, email):
        response = self.client.post(
            "/api/auth/register",
            json={"email": email, "password": PASSWORD, "display_name": email.split("@")[0]},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["access_token"]

    def _headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _workspaces(self, token):
        response = self.client.get("/api/workspaces", headers=self._headers(token))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _default_workspace(self, token):
        return self._workspaces(token)[0]["id"]

    def _create_workspace(self, token, name="第二个工作区"):
        response = self.client.post(
            "/api/workspaces", headers=self._headers(token), json={"name": name},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _create_project(self, token, workspace_id, name, path):
        return self.client.post(
            f"/api/workspaces/{workspace_id}/projects",
            headers=self._headers(token),
            json={"name": name, "workspace_path": path},
        )

    def _audit_actions(self):
        engine = create_engine(f"sqlite:///{self.db_path.as_posix()}")
        try:
            with engine.connect() as connection:
                return list(connection.execute(select(AuditLog.action)).scalars().all())
        finally:
            engine.dispose()

    # ---------- 工作区 ----------

    def test_register_creates_owner_workspace(self):
        token = self._register("owner@example.com")
        workspaces = self._workspaces(token)
        self.assertEqual(len(workspaces), 1)
        self.assertEqual(workspaces[0]["role"], "owner")

    def test_create_workspace_makes_creator_owner(self):
        token = self._register("a@example.com")
        workspace_id = self._create_workspace(token)
        roles = {w["id"]: w["role"] for w in self._workspaces(token)}
        self.assertEqual(roles[workspace_id], "owner")

    def test_members_list_shows_self_as_owner(self):
        token = self._register("owner@example.com")
        workspace_id = self._default_workspace(token)
        response = self.client.get(
            f"/api/workspaces/{workspace_id}/members", headers=self._headers(token),
        )
        self.assertEqual(response.status_code, 200, response.text)
        members = response.json()
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0]["email"], "owner@example.com")
        self.assertEqual(members[0]["role"], "owner")

    def test_non_member_cannot_list_members(self):
        owner_token = self._register("owner@example.com")
        workspace_id = self._default_workspace(owner_token)
        stranger_token = self._register("stranger@example.com")

        response = self.client.get(
            f"/api/workspaces/{workspace_id}/members", headers=self._headers(stranger_token),
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    # ---------- 项目 CRUD ----------

    def test_create_project_under_project_root(self):
        token = self._register("owner@example.com")
        workspace_id = self._default_workspace(token)

        response = self._create_project(token, workspace_id, "示例项目", "demo")
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["workspace_path"], "demo")
        self.assertEqual(body["status"], "active")

        listed = self.client.get(
            f"/api/workspaces/{workspace_id}/projects", headers=self._headers(token),
        ).json()
        self.assertEqual([p["name"] for p in listed], ["示例项目"])

    def test_project_path_is_normalised(self):
        """入参里的 ./、反斜杠和重复分隔符不应在库里留下不同写法。"""
        token = self._register("owner@example.com")
        workspace_id = self._default_workspace(token)
        response = self._create_project(token, workspace_id, "示例项目", "./demo/")
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["workspace_path"], "demo")

    def test_rename_project(self):
        token = self._register("owner@example.com")
        workspace_id = self._default_workspace(token)
        project_id = self._create_project(token, workspace_id, "旧名", "demo").json()["id"]

        response = self.client.patch(
            f"/api/projects/{project_id}", headers=self._headers(token), json={"name": "新名"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "新名")
        self.assertIn("project.rename", self._audit_actions())

    def test_duplicate_project_name_is_rejected(self):
        token = self._register("owner@example.com")
        workspace_id = self._default_workspace(token)
        self._create_project(token, workspace_id, "同名", "demo")
        response = self._create_project(token, workspace_id, "同名", "other")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "project_name_taken")

    def test_duplicate_name_race_yields_409_not_500(self):
        """预检查不是并发保护：两个请求可以同时通过它，再由唯一约束拦下一个。

        这里把预检查打成"没查到"来模拟它被并发绕过，断言结果是 409 而不是 500——
        既验证 IntegrityError 被转成了领域错误，也验证 SAVEPOINT 没有把外层事务
        弄成不可用的失败态（那样后续审计写入会连带失败）。
        """
        from unittest import mock

        from huicode.server.domain import projects as domain_projects

        token = self._register("owner@example.com")
        workspace_id = self._default_workspace(token)
        self._create_project(token, workspace_id, "同名", "demo")

        with mock.patch.object(
            domain_projects, "_name_taken", new=mock.AsyncMock(return_value=False)
        ):
            response = self._create_project(token, workspace_id, "同名", "other")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["error"]["code"], "project_name_taken")
        # 冲突那次不应留下审计：写入在 SAVEPOINT 内被回滚了。
        self.assertNotIn("project.create", self._audit_actions()[1:])

    def test_missing_directory_is_rejected(self):
        token = self._register("owner@example.com")
        workspace_id = self._default_workspace(token)
        response = self._create_project(token, workspace_id, "不存在", "no-such-dir")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_project_path")

    # ---------- 路径安全 ----------

    def test_traversal_paths_are_rejected_and_audited(self):
        token = self._register("owner@example.com")
        workspace_id = self._default_workspace(token)

        attempts = [
            "..",
            "../outside",
            "demo/../../outside",
            r"..\outside",
            "/etc",
            "C:/Windows",
            "C:\\Windows",
            "//server/share",
        ]
        for index, attempt in enumerate(attempts):
            with self.subTest(attempt=attempt):
                response = self._create_project(token, workspace_id, f"p{index}", attempt)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["error"]["code"], "invalid_project_path")

        # 每一次都要留下审计，不能因为返回错误就被事务回滚掉。
        rejected = [a for a in self._audit_actions() if a == "project.path_rejected"]
        self.assertEqual(len(rejected), len(attempts))

    def test_link_escape_is_rejected_and_audited(self):
        link = self.project_root / "escape"
        if not _make_link(link, self.outside):
            self.skipTest("当前环境无法创建 junction/symlink")

        token = self._register("owner@example.com")
        workspace_id = self._default_workspace(token)
        response = self._create_project(token, workspace_id, "逃逸", "escape")
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("project.path_rejected", self._audit_actions())

    def test_error_response_does_not_leak_host_paths(self):
        token = self._register("owner@example.com")
        workspace_id = self._default_workspace(token)
        response = self._create_project(token, workspace_id, "越界", "../outside")
        self.assertNotIn(str(self.project_root), response.text)
        self.assertNotIn(str(self.outside), response.text)

    # ---------- 归档 ----------

    def test_archive_is_idempotent_and_hides_from_default_list(self):
        token = self._register("owner@example.com")
        workspace_id = self._default_workspace(token)
        project_id = self._create_project(token, workspace_id, "待归档", "demo").json()["id"]

        first = self.client.post(
            f"/api/projects/{project_id}/archive", headers=self._headers(token),
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["status"], "archived")

        second = self.client.post(
            f"/api/projects/{project_id}/archive", headers=self._headers(token),
        )
        self.assertEqual(second.status_code, 200)
        # 幂等：重复归档不重复写审计
        self.assertEqual(self._audit_actions().count("project.archive"), 1)

        default_list = self.client.get(
            f"/api/workspaces/{workspace_id}/projects", headers=self._headers(token),
        ).json()
        self.assertEqual(default_list, [])

        with_archived = self.client.get(
            f"/api/workspaces/{workspace_id}/projects?include_archived=true",
            headers=self._headers(token),
        ).json()
        self.assertEqual(len(with_archived), 1)

    def test_archived_project_cannot_be_renamed(self):
        token = self._register("owner@example.com")
        workspace_id = self._default_workspace(token)
        project_id = self._create_project(token, workspace_id, "已归档", "demo").json()["id"]
        self.client.post(f"/api/projects/{project_id}/archive", headers=self._headers(token))

        response = self.client.patch(
            f"/api/projects/{project_id}", headers=self._headers(token), json={"name": "改名"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "project_archived")

    # ---------- 跨工作区与角色 ----------

    def test_cross_workspace_project_access_is_404(self):
        owner_token = self._register("owner@example.com")
        workspace_id = self._default_workspace(owner_token)
        project_id = self._create_project(owner_token, workspace_id, "私密", "demo").json()["id"]

        stranger_token = self._register("stranger@example.com")
        for method, path, payload in (
            ("get", f"/api/workspaces/{workspace_id}/projects", None),
            ("patch", f"/api/projects/{project_id}", {"name": "篡改"}),
            ("post", f"/api/projects/{project_id}/archive", None),
        ):
            with self.subTest(path=path):
                response = getattr(self.client, method)(
                    path, headers=self._headers(stranger_token), **({"json": payload} if payload else {}),
                )
                self.assertEqual(response.status_code, 404, response.text)

    def test_role_gate_on_project_creation(self):
        owner_token = self._register("owner@example.com")
        workspace_id = self._default_workspace(owner_token)
        member_token = self._register("member@example.com")

        # 把第二个用户加进工作区，角色为 viewer
        self._set_role(workspace_id, self._user_id(member_token), "viewer")

        denied = self._create_project(member_token, workspace_id, "viewer 建的项目", "demo")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], "forbidden")

        # viewer 仍可读列表
        readable = self.client.get(
            f"/api/workspaces/{workspace_id}/projects", headers=self._headers(member_token),
        )
        self.assertEqual(readable.status_code, 200)

        # 提为 admin 后可创建
        self._set_role(workspace_id, self._user_id(member_token), "admin")
        allowed = self._create_project(member_token, workspace_id, "admin 建的项目", "other")
        self.assertEqual(allowed.status_code, 201, allowed.text)

    def _user_id(self, token):
        return self.client.get(
            "/api/auth/me", headers=self._headers(token),
        ).json()["id"]

    def _set_role(self, workspace_id, user_id, role):
        from sqlalchemy import insert, update
        from uuid import UUID as _UUID

        from huicode.server.db.models import WorkspaceMember

        engine = create_engine(f"sqlite:///{self.db_path.as_posix()}")
        try:
            with engine.begin() as connection:
                updated = connection.execute(
                    update(WorkspaceMember)
                    .where(
                        WorkspaceMember.workspace_id == _UUID(workspace_id),
                        WorkspaceMember.user_id == _UUID(user_id),
                    )
                    .values(role=role)
                )
                if updated.rowcount == 0:
                    connection.execute(
                        insert(WorkspaceMember).values(
                            workspace_id=_UUID(workspace_id), user_id=_UUID(user_id), role=role,
                        )
                    )
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
