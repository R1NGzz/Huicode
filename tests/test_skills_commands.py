import tempfile
import unittest
from pathlib import Path

from huicode.commands import CommandContext, CommandDispatcher, CommandParser, create_builtin_registry
from huicode.commands.skills import registry_with_skill_commands
from huicode.skills.catalog import SkillCatalogBuilder
from huicode.skills.manager import SkillManager
from huicode.tools.registry import create_default_registry


class FakeRuntime:
    def __init__(self) -> None:
        self.messages = []
        self.skills = []

    def show_message(self, message, *, error=False):  # noqa: ANN001
        self.messages.append((message, error))

    def run_skill(self, name, arguments):  # noqa: ANN001
        self.skills.append((name, arguments))
        return ""

    def __getattr__(self, name):  # noqa: ANN001
        return lambda *args, **kwargs: ""


class SkillCommandTests(unittest.TestCase):
    def test_catalog_registers_help_completion_and_preserves_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roots = {name: base / name for name in ("builtin", "user", "project")}
            roots["project"].mkdir()
            (roots["project"] / "focus.md").write_text(
                """---
name: focus
description: Focus task
allowed_tools: []
mode: shared
---
Do {{args}}
""",
                encoding="utf-8",
            )
            manager = SkillManager(SkillCatalogBuilder(roots, create_default_registry(base)))
            snapshot = manager.initialize()
            registry = registry_with_skill_commands(create_builtin_registry(), snapshot)
            runtime = FakeRuntime()
            context = CommandContext(runtime, runtime, registry)
            dispatcher = CommandDispatcher(registry)

            dispatcher.dispatch(CommandParser().parse("/focus Focus On API"), context)
            dispatcher.dispatch(CommandParser().parse("/help"), context)

        self.assertEqual(runtime.skills, [("focus", "Focus On API")])
        self.assertIn("/focus [arguments]", runtime.messages[-1][0])
        self.assertIn("focus", [name for name, _ in registry.completion_entries()])

    def test_review_is_not_hardcoded_in_core_registry(self) -> None:
        registry = create_builtin_registry()

        self.assertIsNone(registry.resolve("review"))


if __name__ == "__main__":
    unittest.main()
