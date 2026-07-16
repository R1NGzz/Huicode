import tempfile
import unittest
from pathlib import Path

from huicode.permissions import PermissionContext, clone_permission_context
from huicode.subagents.filtering import (
    TaskAwareToolRegistry,
    filtered_registry,
    resolve_subagent_tool_names,
)
from huicode.subagents.types import AgentDefinition
from huicode.subagents.types import SubagentTask
from huicode.tools.registry import create_default_registry


class ToolFilteringTests(unittest.TestCase):
    def test_layers_only_remove_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            registry = create_default_registry(base)
            definition = AgentDefinition(
                "worker", "x", ("Read", "Find", "Write"), ("Write",), "inherit", 10,
                "strict", "body", "project", base / "worker.md",
            )
            names = resolve_subagent_tool_names(
                registry,
                ("Read", "Find", "Write", "Bash", "Agent", "Skill"),
                kind="defined",
                definition=definition,
                background=True,
                background_allowed=("Read", "Find", "Search"),
                mode="plan",
            )
            child = filtered_registry(registry, names)
        self.assertEqual(names, frozenset({"Read", "Find"}))
        self.assertIsNone(child.get("Write"))

    def test_background_transition_changes_provider_and_executor_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            registry = create_default_registry(base)
            definition = AgentDefinition(
                "worker", "x", ("Read", "Write"), (), "inherit", 10,
                "default", "body", "project", base / "worker.md",
            )
            task = SubagentTask("task", "defined", "worker", "x")
            dynamic = TaskAwareToolRegistry(
                registry,
                task,
                ("Read", "Write"),
                kind="defined",
                definition=definition,
                background_allowed=("Read",),
                mode="chat",
                read_only_names=frozenset({"Read", "Find", "Search"}),
            )
            self.assertIsNotNone(dynamic.get("Write"))
            self.assertIn("Write", {spec.name for spec in dynamic.to_specs()})
            task.background_event.set()
            self.assertIsNone(dynamic.get("Write"))
            self.assertNotIn("Write", {spec.name for spec in dynamic.to_specs()})


class PermissionSnapshotTests(unittest.TestCase):
    def test_child_mode_only_tightens_and_state_is_copied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            parent = PermissionContext(base, mode="default")
            child = clone_permission_context(parent, base, requested_mode="permissive")
            self.assertEqual(child.mode, "default")
            child.session_rules.append(object())  # type: ignore[arg-type]
            self.assertEqual(parent.session_rules, [])
            self.assertIsNone(child.confirmer)
            self.assertIsNone(child.persistent_path)


if __name__ == "__main__":
    unittest.main()
