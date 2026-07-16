import tempfile
import threading
import time
import unittest
from pathlib import Path

from huicode.config import SubagentConfig
from huicode.permissions import PermissionContext
from huicode.prompts import PromptBundle
from huicode.subagents.catalog import AgentCatalog
from huicode.subagents.manager import SubagentManager
from huicode.subagents.tool import AgentTool
from huicode.subagents.types import ParentAgentSnapshot, PermissionSnapshot, SubagentResult
from huicode.tools.base import ToolContext
from huicode.tools.registry import create_default_registry


class AgentToolSchemaTests(unittest.TestCase):
    def test_schema_is_independent_of_catalog_and_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first = _manager(base)
            second = _manager(base)
            self.assertEqual(AgentTool(first).parameters, AgentTool(second).parameters)
            self.assertEqual(AgentTool(first).name, "Agent")
            first.close()
            second.close()


class AgentToolValidationTests(unittest.TestCase):
    def test_invalid_combinations_are_structured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = _manager(Path(directory))
            tool = AgentTool(manager)
            context = ToolContext(Path(directory))
            self.assertEqual(tool.run({"type": "bad", "task": "x"}, context).error.code, "invalid_request")
            self.assertEqual(tool.run({"type": "defined", "task": "x"}, context).error.code, "invalid_request")
            self.assertEqual(
                tool.run({"type": "fork", "task": "x", "role": "worker"}, context).error.code,
                "invalid_request",
            )
            manager.close()


class ForegroundBackgroundTests(unittest.TestCase):
    def test_fork_is_background_and_defined_can_finish_foreground(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manager = _manager(base, with_role=True)
            tool = AgentTool(manager)
            context = ToolContext(base)
            foreground = tool.run({"type": "defined", "task": "x", "role": "worker"}, context)
            background = tool.run({"type": "fork", "task": "y"}, context)
            self.assertTrue(foreground.ok)
            self.assertIn("summary", foreground.data)
            self.assertTrue(background.ok)
            self.assertTrue(background.data["background"])
            manager.close()

    def test_slow_defined_task_moves_to_background_after_timeout(self) -> None:
        gate = threading.Event()

        def slow(request, task):  # noqa: ANN001
            gate.wait(1)
            return SubagentResult(task.id, "completed", "later", "final", 1)

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manager = _manager(base, with_role=True)
            manager.runner = slow
            manager.config = SubagentConfig(foreground_timeout_seconds=0.05)
            result = AgentTool(manager).run(
                {"type": "defined", "task": "slow", "role": "worker"},
                ToolContext(base),
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.data["reason"], "timeout")
            self.assertEqual(result.data["status"], "running_background")
            gate.set()
            deadline = time.time() + 1
            while time.time() < deadline and manager.summary()["ready"] == 0:
                time.sleep(0.01)
            self.assertEqual(manager.summary()["ready"], 1)
            manager.close()


def _manager(base: Path, with_role: bool = False) -> SubagentManager:
    registry = create_default_registry(base)
    roots = {"plugin": (), "builtin": (), "user": (), "project": ()}
    if with_role:
        root = base / "agents"
        root.mkdir(exist_ok=True)
        (root / "worker.md").write_text(
            """---
name: worker
description: worker
allowed_tools: [Read]
denied_tools: []
model: inherit
max_iterations: 5
permission_mode: strict
---
work
""",
            encoding="utf-8",
        )
        roots["project"] = (root,)
    catalog = AgentCatalog(roots, registry, SubagentConfig())
    catalog.initialize()
    manager = SubagentManager(
        catalog,
        SubagentConfig(foreground_timeout_seconds=1),
        lambda request, task: SubagentResult(task.id, "completed", "summary", "final", 1),
    )
    manager.capture_parent(
        ParentAgentSnapshot(
            (), PromptBundle(), ("Read",), "chat", PermissionSnapshot(PermissionContext(base))
        )
    )
    return manager


if __name__ == "__main__":
    unittest.main()
