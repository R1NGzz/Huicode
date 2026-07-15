import unittest
from pathlib import Path

from huicode.hooks.events import event_payload, make_event, tool_data
from huicode.hooks.matching import match_condition
from huicode.hooks.types import HookCondition, HookPredicate
from huicode.providers.base import ToolCall


class HookMatchingTests(unittest.TestCase):
    def test_exact_glob_regex_and_not(self) -> None:
        payload = {"tool": {"name": "Edit", "arguments": {"path": "src/main.py"}}}
        condition = HookCondition(
            "all",
            (
                HookPredicate("tool.name", "exact", "Edit"),
                HookPredicate("tool.arguments.path", "glob", "src/*.py"),
                HookPredicate("tool.arguments.path", "regex", r"\.py$"),
                HookPredicate("tool.arguments.path", "glob", "generated/*", negate=True),
            ),
        )
        self.assertTrue(match_condition(condition, payload))
        self.assertFalse(match_condition(HookCondition("all", (HookPredicate("tool.name", "exact", "edit"),)), payload))

    def test_all_any_unconditional_and_missing_field(self) -> None:
        payload = {"turn": {"input": "hello"}}
        self.assertTrue(match_condition(None, payload))
        self.assertTrue(
            match_condition(
                HookCondition(
                    "any",
                    (HookPredicate("turn.input", "exact", "no"), HookPredicate("turn.input", "exact", "hello")),
                ),
                payload,
            )
        )
        self.assertFalse(match_condition(HookCondition("all", (HookPredicate("turn.missing", "exact", "x"),)), payload))
        self.assertTrue(
            match_condition(HookCondition("all", (HookPredicate("turn.missing", "exact", "x", negate=True),)), payload)
        )

    def test_tool_alias_uses_same_canonical_name_as_permissions(self) -> None:
        payload = event_payload(
            make_event(
                "tool_before",
                session_id="session",
                workspace=Path.cwd(),
                data=tool_data(ToolCall("call-1", "Glob", {"pattern": "**/*.py"})),
            )
        )
        condition = HookCondition("all", (HookPredicate("tool.name", "exact", "Find"),))
        self.assertTrue(match_condition(condition, payload))


if __name__ == "__main__":
    unittest.main()
