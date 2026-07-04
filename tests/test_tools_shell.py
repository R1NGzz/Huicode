import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from huicode.tools.base import ToolContext
from huicode.tools.shell import RunCommandTool


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

    def test_normalizes_common_unix_ls_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("huicode.tools.shell.os.name", "nt"):
            result = RunCommandTool().run({"command": "ls -la"}, ToolContext(workspace=Path(directory)))

        self.assertTrue(result.ok)
        self.assertIn("dir /a", result.data["command"])


if __name__ == "__main__":
    unittest.main()
