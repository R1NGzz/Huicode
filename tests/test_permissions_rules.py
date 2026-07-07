import unittest

from huicode.permissions.base import PermissionRule
from huicode.permissions.rules import match_rule, parse_rule_key, target_value_for_call
from huicode.providers.base import ToolCall


class PermissionRuleTests(unittest.TestCase):
    def test_parse_rule_key(self) -> None:
        self.assertEqual(parse_rule_key("Bash(git *)"), ("Bash", "git *"))
        self.assertEqual(parse_rule_key("Read(src/**/*.py)"), ("Read", "src/**/*.py"))
        with self.assertRaises(ValueError):
            parse_rule_key("Bash git *")

    def test_target_value_for_call(self) -> None:
        self.assertEqual(target_value_for_call(ToolCall("1", "Bash", {"command": "git status"})), "git status")
        self.assertEqual(target_value_for_call(ToolCall("1", "Read", {"path": "README.md"})), "README.md")
        self.assertEqual(target_value_for_call(ToolCall("1", "Search", {"pattern": "TODO"})), "TODO")
        self.assertEqual(target_value_for_call(ToolCall("1", "Search", {"pattern": "TODO", "glob": "*.py"})), "*.py")

    def test_matches_exact_and_glob(self) -> None:
        self.assertTrue(
            match_rule(
                PermissionRule("Bash", "git *", "allow"),
                ToolCall("1", "Bash", {"command": "git status"}),
            )
        )
        self.assertTrue(
            match_rule(
                PermissionRule("Read", "README.md", "allow"),
                ToolCall("1", "Read", {"path": "README.md"}),
            )
        )
        self.assertTrue(
            match_rule(
                PermissionRule("Read", "src/**/*.py", "allow"),
                ToolCall("1", "Read", {"path": "src/pkg/app.py"}),
            )
        )
        self.assertFalse(
            match_rule(
                PermissionRule("Bash", "git *", "allow"),
                ToolCall("1", "Bash", {"command": "python -V"}),
            )
        )

    def test_glob_alias_matches_find(self) -> None:
        rule = PermissionRule("Find", "*.py", "allow")
        self.assertTrue(match_rule(rule, ToolCall("1", "Glob", {"pattern": "*.py"})))


if __name__ == "__main__":
    unittest.main()

