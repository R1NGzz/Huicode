import tempfile
import unittest
from pathlib import Path

from huicode.skills.catalog import SkillCatalogBuilder
from huicode.skills.manager import SkillManager
from huicode.skills.types import SkillRuntimeState
from huicode.tools.registry import create_default_registry

from tests.test_skills_catalog import write_skill


class SkillManagerTests(unittest.TestCase):
    def test_activate_replace_intersection_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roots = {name: base / name for name in ("builtin", "user", "project")}
            write_skill(roots["project"], "one.md", "one", "one", ("Read", "Find"))
            write_skill(roots["project"], "two.md", "two", "two", ("Find", "Search"))
            manager = SkillManager(SkillCatalogBuilder(roots, create_default_registry(base)))
            manager.initialize()
            state = SkillRuntimeState()

            first = manager.activate_shared(state, "one", "A")
            replaced = manager.activate_shared(state, "one", "B")
            manager.activate_shared(state, "two", "C")

            self.assertEqual(first.activated_order, replaced.activated_order)
            self.assertEqual(len(state.active), 2)
            self.assertEqual(manager.active_allowed_tools(state), {"Find"})
            manager.clear_state(state)
            self.assertEqual(state.active, {})
            self.assertEqual(len(manager.snapshot.definitions), 2)

    def test_reload_updates_active_and_rolls_back_invalid_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roots = {name: base / name for name in ("builtin", "user", "project")}
            write_skill(roots["project"], "one.md", "one", "v1", ("Read",))
            manager = SkillManager(SkillCatalogBuilder(roots, create_default_registry(base)))
            manager.initialize()
            state = SkillRuntimeState()
            manager.activate_shared(state, "one", "ARG")

            write_skill(roots["project"], "one.md", "one", "version-two", ("Read",))
            self.assertTrue(manager.reload_if_changed(state))
            self.assertIn("Run one", state.active["one"].rendered_body)
            generation = manager.snapshot.generation

            write_skill(roots["project"], "one.md", "one", "invalid-version", ("Missing",))
            self.assertFalse(manager.reload_if_changed(state))
            self.assertEqual(manager.snapshot.generation, generation)
            self.assertIn("未知工具", state.reload_error)


if __name__ == "__main__":
    unittest.main()
