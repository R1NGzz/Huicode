import tempfile
import unittest
from pathlib import Path

from huicode.permissions.base import PermissionRule
from huicode.permissions.config import (
    PermissionConfigPaths,
    append_persistent_rule,
    load_permission_config,
)
from huicode.permissions import PermissionConfigError


class PermissionConfigTests(unittest.TestCase):
    def test_loads_and_prioritizes_three_layers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            user = root / "user.yaml"
            project = root / "project.yaml"
            local = root / "local.yaml"
            user.write_text("mode: strict\nrules:\n  Bash(*): deny\n", encoding="utf-8")
            project.write_text("mode: default\nrules:\n  Bash(git *): allow\n", encoding="utf-8")
            local.write_text("mode: permissive\nrules:\n  Read(README.md): allow\n", encoding="utf-8")

            config = load_permission_config(PermissionConfigPaths(user, project, local))

        self.assertEqual(config.mode, "permissive")
        self.assertEqual([rule.source for rule in config.rules], ["local", "project", "user"])

    def test_rejects_invalid_mode_and_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad_mode = root / "bad-mode.yaml"
            bad_action = root / "bad-action.yaml"
            missing = root / "missing.yaml"
            bad_mode.write_text("mode: wild\n", encoding="utf-8")
            bad_action.write_text("rules:\n  Bash(git *): maybe\n", encoding="utf-8")

            with self.assertRaises(PermissionConfigError):
                load_permission_config(PermissionConfigPaths(bad_mode, missing, missing))
            with self.assertRaises(PermissionConfigError):
                load_permission_config(PermissionConfigPaths(bad_action, missing, missing))

    def test_append_persistent_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".huicode-permissions.local.yaml"
            append_persistent_rule(path, PermissionRule("Bash", "git status", "allow", raw="Bash(git status)"))

            text = path.read_text(encoding="utf-8")

        self.assertIn("rules:", text)
        self.assertIn("'Bash(git status)': allow", text)

    def test_windows_path_rule_colon_is_not_split_as_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / "local.yaml"
            missing = root / "missing.yaml"
            local.write_text(
                "mode: default\n"
                "rules:\n"
                "  Bash(dir /s /b C:\\Users\\Administrator\\Documents\\Huicode\\huicode): allow\n",
                encoding="utf-8",
            )

            config = load_permission_config(PermissionConfigPaths(missing, missing, local))

        self.assertEqual(config.rules[0].tool, "Bash")
        self.assertEqual(config.rules[0].action, "allow")
        self.assertIn("C:\\Users", config.rules[0].pattern)

    def test_append_quotes_windows_path_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".huicode-permissions.local.yaml"
            append_persistent_rule(
                path,
                PermissionRule(
                    "Bash",
                    "dir /s /b C:\\Users\\Administrator\\Documents\\Huicode",
                    "allow",
                    raw="Bash(dir /s /b C:\\Users\\Administrator\\Documents\\Huicode)",
                ),
            )

            text = path.read_text(encoding="utf-8")
            config = load_permission_config(PermissionConfigPaths(path.with_name("missing"), path.with_name("missing2"), path))

        self.assertIn("'Bash(dir /s /b C:\\Users\\Administrator\\Documents\\Huicode)': allow", text)
        self.assertEqual(config.rules[0].action, "allow")


if __name__ == "__main__":
    unittest.main()
