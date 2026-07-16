import tempfile
import unittest
from pathlib import Path

from huicode.hooks.actions import HookActionExecutor
from huicode.hooks.types import HookRule, SubagentAction


class HookSubmissionTests(unittest.TestCase):
    def test_submits_role_and_task(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            executor = HookActionExecutor(Path(directory))
            executor.set_subagent_submitter(lambda role, task: calls.append((role, task)) or "task-1")
            result = executor.execute(
                HookRule("sub", "turn_end", SubagentAction(task="review {{turn.id}}", role="reviewer")),
                {"agent_scope": "main", "turn": {"id": "abc"}},
            )
        self.assertEqual(result.status, "success")
        self.assertEqual(calls, [("reviewer", "review abc")])


class RecursionGuardTests(unittest.TestCase):
    def test_subagent_scope_does_not_submit(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            executor = HookActionExecutor(Path(directory), lambda role, task: calls.append((role, task)) or "x")
            result = executor.execute(
                HookRule("sub", "turn_end", SubagentAction(task="again")),
                {"agent_scope": "subagent:defined:worker:task-1"},
            )
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.message, "recursion_guard")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
