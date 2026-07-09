import unittest

from huicode.config import ContextConfig
from huicode.context.estimator import TokenEstimator
from huicode.context.history import apply_summary, split_recent_messages
from huicode.context.segments import build_history_segments
from huicode.providers.base import ConversationMessage, ToolCall
from huicode.tools.base import ToolResult


class ContextHistoryTests(unittest.TestCase):
    def test_build_history_segments_keeps_tool_pairs_together(self) -> None:
        estimator = TokenEstimator()
        calls = [ToolCall("call_1", "Read", {"path": "README.md"}), ToolCall("call_2", "Find", {"pattern": "*"})]
        messages = [
            ConversationMessage("user", "查项目"),
            ConversationMessage("assistant", "", tool_calls=calls),
            ConversationMessage("tool", "ok", tool_call_id="call_1", tool_name="Read", tool_result=ToolResult.success({"content": "a"}, "ok")),
            ConversationMessage("tool", "ok", tool_call_id="call_2", tool_name="Find", tool_result=ToolResult.success({"count": 3}, "ok")),
            ConversationMessage("assistant", "结论"),
        ]

        segments = build_history_segments(messages, estimator)

        self.assertEqual(len(segments), 3)
        self.assertEqual(len(segments[1].messages), 3)
        self.assertTrue(segments[1].contains_tool_pair)

    def test_split_recent_messages_respects_minimum_recent_messages(self) -> None:
        estimator = TokenEstimator()
        config = ContextConfig(recent_keep_tokens=1000, min_recent_messages=5)
        messages = [ConversationMessage("user", f"msg-{index}") for index in range(8)]

        older, recent = split_recent_messages(messages, config, estimator)

        self.assertGreaterEqual(len(recent), 5)
        self.assertEqual(recent[-1].content, "msg-7")
        self.assertEqual(len(older) + len(recent), 8)

    def test_apply_summary_inserts_boundary_message(self) -> None:
        recent = [ConversationMessage("user", "最近消息"), ConversationMessage("assistant", "最近回复")]

        messages = apply_summary([ConversationMessage("user", "旧消息")], recent, "## 当前任务\n继续实现")

        self.assertEqual(messages[0].role, "user")
        self.assertIn("conversation_summary", messages[0].content)
        self.assertIn("compression_boundary", messages[1].content)
        self.assertIn("重新读取", messages[1].content)
        self.assertEqual(messages[2].content, "最近消息")
        self.assertEqual(messages[3].content, "最近回复")


if __name__ == "__main__":
    unittest.main()
