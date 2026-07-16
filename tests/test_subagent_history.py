import unittest

from huicode.providers.base import ConversationMessage, ToolCall
from huicode.subagents.history import select_protocol_safe_history


class SubagentHistoryTests(unittest.TestCase):
    def test_keeps_complete_group_and_drops_unpaired_tail(self) -> None:
        first = ToolCall("one", "Read", {"path": "a"})
        pending = ToolCall("two", "Read", {"path": "b"})
        messages = [
            ConversationMessage("user", "start"),
            ConversationMessage("assistant", "", tool_calls=[first]),
            ConversationMessage("tool", "", tool_call_id="one", tool_name="Read"),
            ConversationMessage("assistant", "continue"),
            ConversationMessage("assistant", "", tool_calls=[pending]),
        ]
        safe = select_protocol_safe_history(messages)
        self.assertEqual(len(safe), 4)
        self.assertEqual(safe[-1].content, "continue")
        messages[0] = ConversationMessage("user", "changed")
        self.assertEqual(safe[0].content, "start")

    def test_drops_orphan_tool_result(self) -> None:
        safe = select_protocol_safe_history(
            [ConversationMessage("tool", "", tool_call_id="missing"), ConversationMessage("user", "ok")]
        )
        self.assertEqual([message.role for message in safe], ["user"])


if __name__ == "__main__":
    unittest.main()
