import tempfile
import unittest
from pathlib import Path

from huicode.config import ContextConfig
from huicode.context.estimator import TokenEstimator
from huicode.context.lightweight import compact_single_tool_result, compact_tool_groups
from huicode.context.store import ToolResultStore
from huicode.providers.base import ConversationMessage, ToolCall
from huicode.tools.base import ToolResult


class ContextLightweightTests(unittest.TestCase):
    def test_spills_large_single_tool_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            estimator = TokenEstimator()
            store = ToolResultStore(workspace, estimator)
            config = ContextConfig(single_tool_result_tokens=20, preview_chars=80)
            call = ToolCall("call_1", "Read", {"path": "big.txt"})
            result = ToolResult.success({"content": "x" * 500}, "ok")

            compacted, spill = compact_single_tool_result(call, result, store, config, estimator, iteration=1)

            self.assertIsNotNone(spill)
            assert spill is not None
            self.assertTrue((workspace / spill.path).is_file())
            self.assertIn("__spilled__", compacted.data)
            self.assertIn("preview", compacted.data)
            self.assertIn("content", (workspace / spill.path).read_text(encoding="utf-8"))

    def test_group_compacts_largest_results_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            estimator = TokenEstimator()
            store = ToolResultStore(workspace, estimator)
            config = ContextConfig(single_tool_result_tokens=10, tool_result_group_tokens=70)
            calls = [
                ToolCall("call_1", "Read", {"path": "a.txt"}),
                ToolCall("call_2", "Read", {"path": "b.txt"}),
                ToolCall("call_3", "Read", {"path": "c.txt"}),
            ]
            messages = [
                ConversationMessage("assistant", "", tool_calls=calls),
                ConversationMessage("tool", "ok", tool_call_id="call_1", tool_name="Read", tool_result=ToolResult.success({"content": "x" * 800}, "ok-a")),
                ConversationMessage("tool", "ok", tool_call_id="call_2", tool_name="Read", tool_result=ToolResult.success({"content": "y" * 200}, "ok-b")),
                ConversationMessage("tool", "ok", tool_call_id="call_3", tool_name="Read", tool_result=ToolResult.success({"content": "z" * 20}, "ok-c")),
            ]

            updated, report = compact_tool_groups(messages, store, config, estimator, iteration=2)

            self.assertIsNotNone(report)
            assert report is not None
            self.assertGreaterEqual(report.spilled_count, 1)
            self.assertIn("__spilled__", updated[1].tool_result.data)
            self.assertNotIn("__spilled__", updated[3].tool_result.data)

    def test_user_messages_are_not_changed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            estimator = TokenEstimator()
            store = ToolResultStore(workspace, estimator)
            config = ContextConfig(single_tool_result_tokens=10, tool_result_group_tokens=40)
            user = ConversationMessage("user", "请保留原句")
            call = ToolCall("call_1", "Read", {"path": "a.txt"})
            messages = [
                user,
                ConversationMessage("assistant", "", tool_calls=[call]),
                ConversationMessage("tool", "ok", tool_call_id="call_1", tool_name="Read", tool_result=ToolResult.success({"content": "x" * 500}, "ok")),
            ]

            updated, _ = compact_tool_groups(messages, store, config, estimator, iteration=3)

            self.assertEqual(updated[0].content, "请保留原句")


if __name__ == "__main__":
    unittest.main()

