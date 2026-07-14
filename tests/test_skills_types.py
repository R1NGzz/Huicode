import unittest

from huicode.agent_events import AgentState
from huicode.skills.types import SkillCatalogSnapshot, SkillRuntimeState


class SkillTypesTests(unittest.TestCase):
    def test_runtime_state_defaults_are_empty(self) -> None:
        state = SkillRuntimeState()

        self.assertEqual(state.active, {})
        self.assertIsNone(state.turn_model_override)
        self.assertEqual(state.nesting_depth, 0)

    def test_catalog_definitions_are_read_only(self) -> None:
        snapshot = SkillCatalogSnapshot.create({}, ())

        with self.assertRaises(TypeError):
            snapshot.definitions["x"] = object()  # type: ignore[index]

    def test_agent_state_has_skill_runtime(self) -> None:
        state = AgentState()

        self.assertIsInstance(state.skills, SkillRuntimeState)


if __name__ == "__main__":
    unittest.main()
