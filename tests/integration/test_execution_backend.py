"""T12 受控执行后端（checklist C52）。

跑**真实进程**：真的起子进程、真的超时、真的杀进程树、真的读管道。这里没有一样东西
可以打桩——"超时后子进程树真的退出了吗"这个问题，只有去问操作系统才知道答案。

不需要数据库，所以不设 skip：`pytest tests` 一定跑到。
"""

import asyncio
import os
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from huicode.server.runtime.errors import (
    ALL_ERROR_CODES,
    LIMIT_ERROR_CODES,
    POLICY_ERROR_CODES,
    SHELL_ENV_REJECTED,
    SHELL_OUTPUT_EXCEEDED,
    SHELL_PATH_VIOLATION,
    SHELL_SPAWN_FAILED,
    SHELL_TIMEOUT,
)
from huicode.server.runtime.execution_backend import ExecutionRequest, LocalExecutionBackend
from huicode.server.runtime.limits import ResourceBudget
from huicode.server.runtime.workspace_resolver import PathViolation
from huicode.tools.execution import (
    ENV_ALLOWLIST,
    CommandRequest,
    CommandRunner,
    ExecutionEnvRejected,
    build_environment,
    is_sensitive_env_name,
)

PYTHON = sys.executable


def budget(**overrides) -> ResourceBudget:
    values = dict(
        max_run_seconds=1800, max_tool_seconds=120, max_shell_seconds=60,
        max_iterations=50, max_tool_calls=100, max_output_bytes=1_048_576,
    )
    values.update(overrides)
    values["max_tool_seconds"] = min(values["max_tool_seconds"], values["max_run_seconds"])
    values["max_shell_seconds"] = min(values["max_shell_seconds"], values["max_tool_seconds"])
    return ResourceBudget(**values)


def python_command(source: str) -> str:
    """把**单行**源码包成一条命令。

    多行代码不要走这里：`-c` 的实参里没法可靠地嵌换行（`\\n` 到了源码里是两个字面
    字符，直接语法错误），而层层转义引号很快就没人看得懂了。多行的用下面的脚本文件。
    """
    assert "\n" not in source, "多行源码请用 _BackendCase.script()"
    return f'"{PYTHON}" -c "{source}"'


class _BackendCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name).resolve()
        (self.workspace / "sub").mkdir()
        self.backend = LocalExecutionBackend()

    def tearDown(self):
        self._tmp.cleanup()

    def script(self, name: str, source: str) -> str:
        """在工作区里放一个脚本并返回执行它的命令。多行代码走这条路。"""
        path = self.workspace / name
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        return f'"{PYTHON}" "{path}"'

    def request(self, command: str, **overrides) -> ExecutionRequest:
        values = dict(
            execution_id=f"exec-{time.monotonic_ns()}",
            command=command,
            workspace=self.workspace,
        )
        values.update(overrides)
        return ExecutionRequest(**values)

    async def run_command(self, command: str, budget_overrides=None, **overrides):
        return await self.backend.execute(
            self.request(command, **overrides), budget(**(budget_overrides or {}))
        )


class BasicExecutionTests(_BackendCase):
    async def test_successful_command_returns_output_and_exit_code(self):
        result = await self.run_command(python_command("print('hello')"))
        self.assertTrue(result.ok, result.stderr)
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello", result.stdout)
        self.assertIsNone(result.error_code)

    async def test_a_nonzero_exit_code_is_not_an_execution_failure(self):
        """命令自己的退出码不是执行边界的问题——那是它给出的结果。"""
        result = await self.run_command(python_command("import sys; sys.exit(3)"))
        self.assertEqual(result.returncode, 3)
        self.assertIsNone(result.error_code)
        self.assertFalse(result.ok)

    async def test_stderr_is_captured_separately(self):
        result = await self.run_command(python_command("import sys; sys.stderr.write('bad')"))
        self.assertIn("bad", result.stderr)
        self.assertNotIn("bad", result.stdout)

    async def test_a_missing_command_is_the_shell_reporting_a_nonzero_exit(self):
        """`shell=True` 下"命令不存在"是**外壳**的退出码，不是我们启动失败——
        外壳本身起来了，它找不到要跑的东西。这两件事不能混：一个是我们的执行边界
        出了问题，一个是命令自己的结果。"""
        result = await self.run_command("definitely-not-a-real-command-xyz")
        self.assertIsNone(result.error_code)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(result.stderr.strip(), "")

    @unittest.skipUnless(os.name == "nt", "只有 Windows 的外壳可替换：POSIX 上 /bin/sh 是写死的")
    async def test_an_unspawnable_shell_produces_a_spawn_failure(self):
        """换成不存在的 COMSPEC，外壳就起不来了——这才是 `shell_spawn_failed`。"""
        with patch.dict(os.environ, {"COMSPEC": "C:\\nope\\missing-cmd.exe"}, clear=False):
            result = await self.run_command(python_command("print('never')"))
        self.assertEqual(result.error_code, SHELL_SPAWN_FAILED)
        self.assertIn(result.error_code, ALL_ERROR_CODES)


class WorkingDirectoryTests(_BackendCase):
    """C52：工作目录被限制在 workspace。"""

    async def test_the_workspace_root_is_the_default(self):
        result = await self.run_command(python_command("import os; print(os.getcwd())"))
        self.assertTrue(result.ok, result.stderr)
        self.assertEqual(Path(result.stdout.strip()).resolve(), self.workspace)

    async def test_a_subdirectory_can_be_used(self):
        result = await self.run_command(
            python_command("import os; print(os.getcwd())"), cwd="sub"
        )
        self.assertTrue(result.ok, result.stderr)
        self.assertEqual(Path(result.stdout.strip()).resolve(), self.workspace / "sub")

    def test_a_parent_directory_escape_is_rejected(self):
        with self.assertRaises(PathViolation):
            self.backend.resolve_cwd(self.request("x", cwd=".."))

    def test_an_absolute_path_is_rejected(self):
        for cwd in ("/etc", "C:\\Windows", "\\\\server\\share"):
            with self.subTest(cwd=cwd):
                with self.assertRaises(PathViolation):
                    self.backend.resolve_cwd(self.request("x", cwd=cwd))

    def test_a_nested_escape_is_rejected(self):
        with self.assertRaises(PathViolation):
            self.backend.resolve_cwd(self.request("x", cwd="sub/../../etc"))

    def test_a_non_directory_is_rejected(self):
        (self.workspace / "file.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(PathViolation):
            self.backend.resolve_cwd(self.request("x", cwd="file.txt"))

    async def test_an_escape_returns_a_path_violation_code(self):
        """失败的**形状**也要对：不是抛异常穿透到调用方，而是一个带码的结果。"""
        result = await self.run_command("echo nope", cwd="..")
        self.assertEqual(result.error_code, SHELL_PATH_VIOLATION)
        self.assertEqual(result.stdout, "")


class TimeoutTests(_BackendCase):
    async def test_a_hanging_command_times_out(self):
        started = time.monotonic()
        result = await self.run_command(
            python_command("import time; time.sleep(30)"),
            budget_overrides={"max_shell_seconds": 1},
            timeout_seconds=60,
        )
        elapsed = time.monotonic() - started
        self.assertEqual(result.error_code, SHELL_TIMEOUT)
        self.assertTrue(result.timed_out)
        self.assertLess(elapsed, 20, "预算把 60 秒的请求收到了 1 秒")

    async def test_the_budget_wins_over_a_longer_request(self):
        """C54：调用方要不到比预算更多的资源。"""
        result = await self.run_command(
            python_command("import time; time.sleep(30)"),
            budget_overrides={"max_shell_seconds": 1},
            timeout_seconds=600,
        )
        self.assertEqual(result.error_code, SHELL_TIMEOUT)

    async def test_a_short_request_is_not_stretched_by_a_large_budget(self):
        """收口是取交集：调用方要 1 秒就在 1 秒停，预算给 60 秒也不等。"""
        started = time.monotonic()
        result = await self.run_command(
            python_command("import time; time.sleep(30)"),
            budget_overrides={"max_shell_seconds": 60},
            timeout_seconds=1,
        )
        self.assertEqual(result.error_code, SHELL_TIMEOUT)
        self.assertLess(time.monotonic() - started, 20)


class ProcessTreeTests(_BackendCase):
    """C52：超时后**整个子进程树**退出，而不只是直接子进程。

    只杀直接子进程的话，`shell=True` 下留下的是真正的命令（它是 cmd.exe 的子进程），
    它会继续跑、继续写文件，而调用方以为已经停了。
    """

    def _write_scripts(self) -> tuple[Path, Path]:
        workspace = self.workspace
        child = workspace / "_tick_child.py"
        child.write_text(
            textwrap.dedent(
                """
                import pathlib, sys, time
                marker = pathlib.Path(sys.argv[1])
                # 有界循环：万一终止没生效，也不会在开发机上留下一个永远跑的进程。
                for _ in range(150):
                    marker.write_text(str(time.time()), encoding="utf-8")
                    time.sleep(0.1)
                """
            ),
            encoding="utf-8",
        )
        parent = workspace / "_tick_parent.py"
        parent.write_text(
            textwrap.dedent(
                """
                import pathlib, subprocess, sys, time
                here = pathlib.Path(__file__).parent
                subprocess.Popen([sys.executable, str(here / "_tick_child.py"), sys.argv[1]])
                time.sleep(60)
                """
            ),
            encoding="utf-8",
        )
        return child, parent

    async def test_a_timed_out_command_takes_its_grandchildren_with_it(self):
        _child, parent = self._write_scripts()
        marker = self.workspace / "tick.txt"

        result = await self.run_command(
            f'"{PYTHON}" "{parent}" "{marker}"',
            budget_overrides={"max_shell_seconds": 1},
        )
        self.assertEqual(result.error_code, SHELL_TIMEOUT)
        self.assertTrue(result.tree_killed)

        # 先确认**孙进程真的跑起来过**。少了这一步，一个从来没启动过的孙进程也会
        # 让下面的比较通过——那样的"通过"什么都没证明。
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(marker.exists(), "孙进程从未写出标记文件，这个用例没有测到东西")

        # 再确认它**停了**：还活着的话标记文件会继续被改写。
        first = marker.read_text(encoding="utf-8")
        time.sleep(1.5)
        second = marker.read_text(encoding="utf-8")
        self.assertEqual(
            first, second,
            "孙进程还在写文件——说明只杀了直接子进程，没有终止整棵树",
        )

    async def test_cancel_stops_a_running_command(self):
        """取消是 T9 的令牌在进程层面的落点：按 execution_id 找到进程树并终止。"""
        result_holder: dict = {}
        request = self.request(python_command("import time; time.sleep(30)"))
        task = asyncio.ensure_future(self.backend.execute(request, budget()))
        try:
            for _ in range(100):
                if self.backend.runner.running_ids():
                    break
                await asyncio.sleep(0.05)
            self.assertIn(request.execution_id, self.backend.runner.running_ids())
            await self.backend.cancel(request.execution_id)
            result_holder["result"] = await asyncio.wait_for(task, 20)
        finally:
            if not task.done():
                task.cancel()

        result = result_holder["result"]
        self.assertIsNotNone(result.returncode, "取消之后进程应当已经退出")
        self.assertLess(result.duration_ms, 20_000)

    async def test_cancelling_an_unknown_execution_is_not_an_error(self):
        await self.backend.cancel("nothing-is-running-with-this-id")


class OutputLimitTests(_BackendCase):
    """C52 的"输出截断"在这里是**内存护栏**：先读完再截断等于内存已经没了。"""

    async def test_oversized_output_terminates_the_command(self):
        result = await self.run_command(
            self.script(
                "_flood.py",
                """
                import sys
                while True:
                    sys.stdout.write('x' * 4096)
                    sys.stdout.flush()
                """,
            ),
            budget_overrides={"max_output_bytes": 64 * 1024},
        )
        self.assertEqual(result.error_code, SHELL_OUTPUT_EXCEEDED)
        self.assertTrue(result.output_truncated)
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 64 * 1024)

    async def test_output_within_the_limit_is_untouched(self):
        result = await self.run_command(
            python_command("print('y' * 100)"), budget_overrides={"max_output_bytes": 4096}
        )
        self.assertIsNone(result.error_code)
        self.assertFalse(result.output_truncated)
        self.assertIn("y" * 100, result.stdout)

    async def test_both_streams_share_one_budget(self):
        """分开记账的话 `cmd 2>&1` 这类写法等于把上限翻倍。"""
        result = await self.run_command(
            self.script(
                "_both.py",
                """
                import sys
                while True:
                    sys.stdout.write('a' * 2048); sys.stdout.flush()
                    sys.stderr.write('b' * 2048); sys.stderr.flush()
                """,
            ),
            budget_overrides={"max_output_bytes": 32 * 1024},
        )
        self.assertEqual(result.error_code, SHELL_OUTPUT_EXCEEDED)
        total = len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))
        self.assertLessEqual(total, 32 * 1024 + 64)


class EnvironmentTests(_BackendCase):
    """C52：环境变量按策略过滤。"""

    def test_the_allowlist_keeps_the_essentials(self):
        env = build_environment()
        self.assertIn("PATH", {name.upper() for name in env})

    def test_an_inherited_secret_is_dropped_silently(self):
        """调用方没提过它，静默过滤正是"按策略过滤"的意思。"""
        with patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "AKIAIOSFODNN7EXAMPLE"}, clear=False):
            env = build_environment()
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)

    def test_huicode_config_never_reaches_a_child(self):
        with patch.dict(
            os.environ,
            {"HUICODE_DATABASE_URL": "postgresql://u:pass@h/db", "HUICODE_PROJECT_ROOT": "/x"},
            clear=False,
        ):
            env = build_environment()
        self.assertFalse([name for name in env if name.upper().startswith("HUICODE_")])

    def test_a_sensitive_variable_cannot_be_requested_explicitly(self):
        """**显式请求要报错，不能静默丢弃**：静默丢弃会让命令在一个与调用方认知不同
        的环境里运行，它可能因此连到别的服务。"""
        with self.assertRaises(ExecutionEnvRejected):
            build_environment({"GITHUB_TOKEN": "ghp_abcdefghijklmnopqrstuvwxyz0123456789"})

    def test_a_malformed_variable_name_is_rejected(self):
        for name in ("", "A=B", "with\x00nul"):
            with self.subTest(name=name):
                with self.assertRaises(ExecutionEnvRejected):
                    build_environment({name: "x"})

    def test_an_ordinary_variable_can_be_added(self):
        env = build_environment({"NODE_ENV": "test"})
        self.assertEqual(env["NODE_ENV"], "test")

    async def test_a_rejected_variable_returns_a_code_instead_of_running(self):
        result = await self.run_command(
            python_command("print('should not run')"),
            env={"AWS_SECRET_ACCESS_KEY": "AKIAIOSFODNN7EXAMPLE"},
        )
        self.assertEqual(result.error_code, SHELL_ENV_REJECTED)
        self.assertNotIn("should not run", result.stdout)

    async def test_the_child_really_does_not_see_the_inherited_secret(self):
        with patch.dict(os.environ, {"MY_CUSTOM_API_KEY": "super-secret-value"}, clear=False):
            result = await self.run_command(
                python_command("import os; print(os.environ.get('MY_CUSTOM_API_KEY', 'ABSENT'))")
            )
        self.assertTrue(result.ok, result.stderr)
        self.assertIn("ABSENT", result.stdout)
        self.assertNotIn("super-secret-value", result.stdout)

    def test_the_sensitive_name_rule_catches_what_the_text_rule_misses(self):
        """`AWS_SECRET_ACCESS_KEY` 末段是 `KEY`，文本脱敏规则不认光秃秃的 key。
        环境变量名判断刻意更宽——误判只是少传一个变量，漏判是密钥进子进程。"""
        for name in (
            "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "DB_PASSWORD", "MY_API_KEY",
            "STRIPE_SECRET", "SSH_AUTH_SOCK", "DATABASE_URL", "HUICODE_JWT_SECRET",
        ):
            with self.subTest(name=name):
                self.assertTrue(is_sensitive_env_name(name))

    def test_ordinary_names_are_not_swept_up(self):
        for name in ("PATH", "SYSTEMROOT", "HOME", "JAVA_HOME", "NODE_ENV", "LANG", "MONKEY"):
            with self.subTest(name=name):
                self.assertFalse(is_sensitive_env_name(name))

    def test_the_allowlist_itself_contains_nothing_sensitive(self):
        """纵深防御的前提是这一层本身干净——将来有人往白名单里加了个密钥变量，
        这条会红。"""
        for name in ENV_ALLOWLIST:
            with self.subTest(name=name):
                self.assertFalse(is_sensitive_env_name(name))


class RunnerTests(unittest.TestCase):
    """核心执行器的同步接口（CLI 的 Shell 工具走这条路）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name).resolve()
        self.runner = CommandRunner()

    def tearDown(self):
        self._tmp.cleanup()

    def test_it_runs_in_the_given_directory(self):
        result = self.runner.run(
            CommandRequest(
                execution_id="sync-1",
                command=python_command("import os; print(os.getcwd())"),
                cwd=self.workspace,
            )
        )
        self.assertTrue(result.ok, result.stderr)
        self.assertEqual(Path(result.stdout.strip()).resolve(), self.workspace)

    def test_a_cap_clamps_the_request(self):
        result = self.runner.run(
            CommandRequest(
                execution_id="sync-2",
                command=python_command("import time; time.sleep(30)"),
                cwd=self.workspace,
                timeout_seconds=600,
            ),
            timeout_cap=1,
        )
        self.assertEqual(result.error_code, SHELL_TIMEOUT)

    def test_the_process_table_is_clean_after_a_run(self):
        self.runner.run(
            CommandRequest(execution_id="sync-3", command=python_command("print(1)"), cwd=self.workspace)
        )
        self.assertEqual(self.runner.running_ids(), frozenset())


class ErrorCodeTests(unittest.TestCase):
    def test_every_shell_failure_has_a_registered_code(self):
        for code in (
            SHELL_TIMEOUT, SHELL_OUTPUT_EXCEEDED, SHELL_SPAWN_FAILED,
            SHELL_ENV_REJECTED, SHELL_PATH_VIOLATION,
        ):
            with self.subTest(code=code):
                self.assertIn(code, ALL_ERROR_CODES)

    def test_limits_and_policy_rejections_are_told_apart(self):
        """超限是"资源不够"，策略拒绝是"有人在做不该做的事"——运维上要分开看。"""
        self.assertIn(SHELL_TIMEOUT, LIMIT_ERROR_CODES)
        self.assertIn(SHELL_OUTPUT_EXCEEDED, LIMIT_ERROR_CODES)
        self.assertNotIn(SHELL_TIMEOUT, POLICY_ERROR_CODES)
        self.assertIn(SHELL_PATH_VIOLATION, POLICY_ERROR_CODES)
        self.assertIn(SHELL_ENV_REJECTED, POLICY_ERROR_CODES)
        self.assertEqual(LIMIT_ERROR_CODES & POLICY_ERROR_CODES, frozenset())


if __name__ == "__main__":
    unittest.main()
