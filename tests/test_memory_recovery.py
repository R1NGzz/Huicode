import unittest

from huicode.memory.recovery import recover_safe_messages
from huicode.providers.base import ConversationMessage, ToolCall
from huicode.tools.base import ToolResult


class MemoryRecoveryTests(unittest.TestCase):
    def test_keeps_matched_tool_pairs(self) -> None:
        messages = [
            ConversationMessage(role="user", content="read"),
            ConversationMessage(
                role="assistant",
                content="",
                tool_calls=[ToolCall("call_1", "Read", {"path": "a.txt"})],
            ),
            ConversationMessage(
                role="tool",
                content="ok",
                tool_call_id="call_1",
                tool_name="Read",
                tool_result=ToolResult.success({"content": "x"}, "ok"),
            ),
            ConversationMessage(role="assistant", content="done"),
        ]

        safe, truncated, reason = recover_safe_messages(messages)

        self.assertFalse(truncated)
        self.assertEqual(len(safe), 4)
        self.assertEqual(reason, "")

    def test_truncates_unmatched_tool_call(self) -> None:
        messages = [
            ConversationMessage(role="user", content="read"),
            ConversationMessage(
                role="assistant",
                content="",
                tool_calls=[ToolCall("call_1", "Read", {"path": "a.txt"})],
            ),
            ConversationMessage(role="assistant", content="bad tail"),
        ]

        safe, truncated, reason = recover_safe_messages(messages)

        self.assertTrue(truncated)
        self.assertEqual([message.role for message in safe], ["user"])
        self.assertIn("未配对", reason)

    def test_truncates_orphan_tool_message(self) -> None:
        messages = [
            ConversationMessage(role="user", content="hi"),
            ConversationMessage(role="tool", content="orphan", tool_call_id="call_1"),
        ]

        safe, truncated, reason = recover_safe_messages(messages)

        self.assertTrue(truncated)
        self.assertEqual([message.role for message in safe], ["user"])
        self.assertIn("孤立", reason)


if __name__ == "__main__":
    unittest.main()
