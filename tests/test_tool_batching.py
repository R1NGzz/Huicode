import tempfile
import unittest
from pathlib import Path

from huicode.agent import execute_tool_batches
from huicode.agent_events import AgentState
from huicode.providers.base import ToolCall
from huicode.tools.base import ToolContext
from huicode.tools.registry import create_default_registry


def _drain(generator):
    events = []
    try:
        while True:
            events.append(next(generator))
    except StopIteration as stop:
        return events, stop.value


class ToolBatchingTests(unittest.TestCase):
    def test_execute_tool_batches_runs_reads_before_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "a.txt").write_text("hello", encoding="utf-8")
            (workspace / "b.py").write_text("print('hi')\n", encoding="utf-8")
            registry = create_default_registry(workspace)
            state = AgentState()
            calls = [
                ToolCall(id="1", name="Read", arguments={"path": "a.txt"}),
                ToolCall(id="2", name="Find", arguments={"pattern": "*.py"}),
                ToolCall(id="3", name="Write", arguments={"path": "c.txt", "content": "done"}),
            ]

            events, outcomes = _drain(
                execute_tool_batches(
                    registry=registry,
                    context=ToolContext(workspace=workspace),
                    state=state,
                    calls=calls,
                    iteration=1,
                )
            )
            written = (workspace / "c.txt").read_text(encoding="utf-8")

            self.assertEqual(
                [(event.kind, event.tool_call.name if event.tool_call else None) for event in events],
                [
                    ("tool_call", "Read"),
                    ("tool_call", "Find"),
                    ("tool_result", "Read"),
                    ("tool_result", "Find"),
                    ("tool_call", "Write"),
                    ("tool_result", "Write"),
                ],
            )
            self.assertEqual([call.name for call, _ in outcomes], ["Read", "Find", "Write"])
            self.assertTrue(all(result.ok for _, result in outcomes))
            self.assertEqual([message.role for message in state.messages], ["tool", "tool", "tool"])
            self.assertEqual(written, "done")


if __name__ == "__main__":
    unittest.main()
