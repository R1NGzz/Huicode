import unittest

from huicode.teams.scoping import ScopedToolRegistry
from huicode.teams.types import TeamRuntimeIdentity
from huicode.tools.base import ToolResult
from huicode.tools.registry import ToolRegistry
from huicode.tools.registry import create_default_registry
from pathlib import Path


class DummyTool:
    side_effect = False
    parameters = {"type": "object", "properties": {}}
    def __init__(self, name): self.name = name; self.description = name
    def spec(self):
        from huicode.providers.base import ToolSpec
        return ToolSpec(self.name, self.description, self.parameters)
    def run(self, args, context): return ToolResult.success({}, "ok")


class TeamScopingTests(unittest.TestCase):
    def make_registry(self):
        registry = ToolRegistry()
        for name in ("Read", "Write", "Bash", "Agent", "Team", "TeamTask", "TeamMessage", "TeamPlanRequest", "TeamPlanDecision", "TeamIntegrate"):
            registry.register(DummyTool(name))
        return registry

    def test_four_scopes(self):
        registry = self.make_registry()
        main = {item.name for item in ScopedToolRegistry(registry, TeamRuntimeIdentity("main")).list()}
        lead = {item.name for item in ScopedToolRegistry(registry, TeamRuntimeIdentity("team_lead", "t")).list()}
        member = {item.name for item in ScopedToolRegistry(registry, TeamRuntimeIdentity("team_member", "t", "m")).list()}
        sub = {item.name for item in ScopedToolRegistry(registry, TeamRuntimeIdentity("subagent")).list()}
        self.assertIn("Team", main); self.assertNotIn("TeamTask", main)
        self.assertIn("TeamPlanDecision", lead)
        self.assertIn("TeamPlanRequest", member); self.assertNotIn("TeamPlanDecision", member); self.assertNotIn("Agent", member)
        self.assertFalse(sub & {"Team", "TeamTask", "TeamMessage"})

    def test_coordinator_removes_write(self):
        scoped = ScopedToolRegistry(self.make_registry(), TeamRuntimeIdentity("team_lead", "t", coordinator=True))
        self.assertIsNone(scoped.get("Write"))

    def test_real_default_tools_serialize(self):
        scoped = ScopedToolRegistry(create_default_registry(Path.cwd()), TeamRuntimeIdentity("main"))
        names = {item.name for item in scoped.to_specs()}
        self.assertIn("Read", names)


if __name__ == "__main__":
    unittest.main()
