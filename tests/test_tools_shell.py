import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from huicode.permissions import PermissionContext
from huicode.providers.base import ToolCall
from huicode.tools.base import ToolContext
from huicode.tools.executor import execute_tool_call
from huicode.tools.registry import create_default_registry
from huicode.tools.shell import RunCommandTool, _decode_output, _prepare_command


class ShellToolTests(unittest.TestCase):
    def test_success_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = RunCommandTool().run(
                {"command": f'"{sys.executable}" -c "print(123)"'},
                ToolContext(workspace=Path(directory)),
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.data["returncode"], 0)
        self.assertIn("123", result.data["stdout"])

    def test_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = RunCommandTool().run(
                {"command": f'"{sys.executable}" -c "import sys; sys.exit(3)"'},
                ToolContext(workspace=Path(directory)),
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "nonzero_exit")
        self.assertEqual(result.error.details["returncode"], 3)

    def test_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = RunCommandTool().run(
                {"command": f'"{sys.executable}" -c "import time; time.sleep(2)"', "timeout_seconds": 1},
                ToolContext(workspace=Path(directory), timeout_seconds=1),
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "timeout")
        self.assertTrue(result.error.details["timed_out"])

    def test_decodes_utf8_local_encoding_and_none_output(self) -> None:
        self.assertEqual(_decode_output("会话恢复".encode("utf-8")), "会话恢复")
        self.assertEqual(_decode_output("中文输出".encode("gb18030")), "中文输出")
        self.assertEqual(_decode_output(None), "")

    @unittest.skipUnless(sys.platform == "win32", "Windows type 命令回归测试")
    def test_reads_utf8_jsonl_with_windows_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = workspace / "session.jsonl"
            session.write_text('{"content":"恢复 € 中文"}\n', encoding="utf-8")

            result = RunCommandTool().run(
                {"command": 'type "session.jsonl"'},
                ToolContext(workspace=workspace),
            )

        self.assertTrue(result.ok)
        self.assertIn("恢复 € 中文", result.data["stdout"])

    def test_normalizes_common_unix_ls_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("huicode.tools.shell.os.name", "nt"):
            result = RunCommandTool().run({"command": "ls -la"}, ToolContext(workspace=Path(directory)))

        self.assertTrue(result.ok)
        self.assertIn("dir /a", result.data["command"])

    def test_strips_trailing_head_limit_on_windows(self) -> None:
        with patch("huicode.tools.shell.os.name", "nt"):
            command, line_limit = _prepare_command("dir /b /s C:\\work | head -100")

        self.assertEqual(command, "dir /b /s C:\\work")
        self.assertEqual(line_limit, 100)

    def test_wraps_powershell_commands_on_windows(self) -> None:
        with patch("huicode.tools.shell.os.name", "nt"):
            command, line_limit = _prepare_command("Get-ChildItem -Recurse -Depth 2 -Name | Select-Object -First 100")

        self.assertTrue(command.startswith('powershell -NoProfile -Command "Get-ChildItem'))
        self.assertIn("Select-Object -First 100", command)
        self.assertIsNone(line_limit)

    def test_blacklisted_command_is_denied_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = execute_tool_call(
                create_default_registry(workspace),
                ToolCall("call_1", "Bash", {"command": "git reset --hard"}),
                ToolContext(workspace=workspace, permissions=PermissionContext(workspace=workspace, mode="permissive")),
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "permission_denied")
        self.assertEqual(result.error.details["source"], "blacklist")


if __name__ == "__main__":
    unittest.main()
