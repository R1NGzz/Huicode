import unittest

from huicode.agent_events import AgentEvent, AgentOptions, AgentState, ToolBatch


class AgentEventTests(unittest.TestCase):
    def test_defaults_cover_agent_state_and_options(self) -> None:
        options = AgentOptions()
        state = AgentState()
        batch = ToolBatch()

        self.assertEqual(options.max_iterations, 8)
        self.assertEqual(options.max_unknown_tools, 2)
        self.assertEqual(options.mode, "chat")
        self.assertEqual(options.read_only_tool_names, frozenset({"Read", "Find", "Search", "Glob"}))
        self.assertEqual(state.messages, [])
        self.assertEqual(state.last_plan, "")
        self.assertFalse(state.cancel_requested)
        self.assertEqual(state.unknown_tool_count, 0)
        self.assertEqual(state.iterations, 0)
        self.assertEqual(batch.parallel_read_calls, [])
        self.assertEqual(batch.serial_calls, [])

    def test_agent_event_fields_are_accessible(self) -> None:
        event = AgentEvent(kind="done", iteration=2, stop_reason="final", data={"mode": "plan"})

        self.assertEqual(event.kind, "done")
        self.assertEqual(event.iteration, 2)
        self.assertEqual(event.stop_reason, "final")
        self.assertEqual(event.data["mode"], "plan")


if __name__ == "__main__":
    unittest.main()
