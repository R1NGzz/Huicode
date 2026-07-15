import tempfile
import unittest
from pathlib import Path

from huicode.hooks.config import HookConfigError, HookConfigPaths, load_hook_catalog
from huicode.hooks.types import CommandAction, PromptAction


def command_rule(rule_id: str, event: str = "turn_start", **extra):
    rule = {
        "id": rule_id,
        "event": event,
        "action": {"type": "command", "command": "echo ok"},
    }
    rule.update(extra)
    return rule


class HookConfigMergeTests(unittest.TestCase):
    def test_three_layers_override_and_keep_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = HookConfigPaths(root / "user.yaml", root / "project.yaml")
            paths.user.write_text(
                "hooks:\n  - id: shared\n    event: turn_start\n    action:\n      type: command\n      command: user\n"
                "  - id: user-only\n    event: turn_start\n    action:\n      type: command\n      command: user-only\n",
                encoding="utf-8",
            )
            paths.project.write_text(
                "hooks:\n  - id: project-only\n    event: turn_end\n    action:\n      type: command\n      command: project\n"
                "  - id: shared\n    event: turn_start\n    action:\n      type: command\n      command: project-shared\n",
                encoding="utf-8",
            )

            catalog = load_hook_catalog(paths, [command_rule("inline-only")])

        self.assertEqual([rule.id for rule in catalog.rules], ["user-only", "inline-only", "project-only", "shared"])
        self.assertEqual(catalog.rules[-1].source, "project")
        self.assertEqual(catalog.rules[-1].action.command, "project-shared")

    def test_disabled_rule_is_counted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = load_hook_catalog(
                HookConfigPaths(root / "none", root / "none2"),
                [command_rule("off", enabled=False)],
            )
        self.assertEqual(catalog.effective_count, 0)
        self.assertEqual(catalog.disabled_count, 1)


class HookConfigValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.paths = HookConfigPaths(root / "user.yaml", root / "project.yaml")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parses_condition_prompt_and_environment(self) -> None:
        rule = {
            "id": "inject",
            "event": "tool_after",
            "if": {
                "all": [
                    {"field": "tool.name", "exact": "Edit"},
                    {"field": "tool.arguments.path", "not": {"glob": "**/generated/**"}},
                ]
            },
            "action": {
                "type": "prompt",
                "content": "已处理 {{tool.arguments.path}}",
                "scope": "turn",
            },
        }
        catalog = load_hook_catalog(self.paths, [rule])
        self.assertIsInstance(catalog.rules[0].action, PromptAction)
        self.assertEqual(catalog.rules[0].condition.mode, "all")

        env_rule = command_rule(
            "env",
            action={"type": "command", "command": "${PY}", "env": {"VALUE": "${VALUE}"}},
        )
        catalog = load_hook_catalog(self.paths, [env_rule], environ={"PY": "python", "VALUE": "中文"})
        action = catalog.rules[0].action
        self.assertIsInstance(action, CommandAction)
        self.assertEqual(action.command, "python")
        self.assertEqual(action.env["VALUE"], "中文")

    def test_rejects_duplicate_invalid_regex_and_bad_combinations(self) -> None:
        with self.assertRaisesRegex(HookConfigError, "重复 id"):
            load_hook_catalog(self.paths, [command_rule("same"), command_rule("same")])

        regex_rule = command_rule(
            "regex",
            **{"if": {"all": [{"field": "turn.input", "regex": "["}]}},
        )
        with self.assertRaisesRegex(HookConfigError, "无效正则"):
            load_hook_catalog(self.paths, [regex_rule])

        with self.assertRaisesRegex(HookConfigError, "不允许异步"):
            load_hook_catalog(self.paths, [command_rule("async", "tool_before", **{"async": True})])

        subagent = {
            "id": "sub",
            "event": "tool_before",
            "action": {"type": "subagent", "task": "check"},
        }
        with self.assertRaisesRegex(HookConfigError, "不允许 subagent"):
            load_hook_catalog(self.paths, [subagent])

        mixed = command_rule(
            "mixed",
            **{
                "if": {
                    "all": [{"field": "turn.input", "exact": "x"}],
                    "any": [{"field": "turn.input", "exact": "y"}],
                }
            },
        )
        with self.assertRaisesRegex(HookConfigError, "只能包含 all 或 any"):
            load_hook_catalog(self.paths, [mixed])

        with self.assertRaisesRegex(HookConfigError, "未定义环境变量"):
            load_hook_catalog(
                self.paths,
                [command_rule("env", action={"type": "command", "command": "${MISSING}"})],
                environ={},
            )

    def test_error_contains_id_source_and_field(self) -> None:
        with self.assertRaises(HookConfigError) as caught:
            load_hook_catalog(self.paths, [command_rule("bad", timeout_seconds=0)])
        text = str(caught.exception)
        self.assertIn("bad", text)
        self.assertIn("huicode.yaml", text)
        self.assertIn("timeout_seconds", text)

    def test_rejects_unknown_actions_empty_conditions_and_multiple_matchers(self) -> None:
        unknown = command_rule("unknown")
        unknown["action"] = {"type": "mystery"}
        with self.assertRaisesRegex(HookConfigError, "未知动作"):
            load_hook_catalog(self.paths, [unknown])

        empty = command_rule("empty", **{"if": {"all": []}})
        with self.assertRaisesRegex(HookConfigError, "非空列表"):
            load_hook_catalog(self.paths, [empty])

        multiple = command_rule(
            "multiple",
            **{"if": {"all": [{"field": "turn.input", "exact": "x", "glob": "*"}]}},
        )
        with self.assertRaisesRegex(HookConfigError, "一种匹配方式"):
            load_hook_catalog(self.paths, [multiple])


if __name__ == "__main__":
    unittest.main()
