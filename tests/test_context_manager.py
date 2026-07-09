import tempfile
import unittest
from pathlib import Path

from huicode.agent_events import AgentState
from huicode.config import ContextConfig, LLMConfig
from huicode.context.estimator import TokenEstimator
from huicode.context.manager import ContextManager
from huicode.context.summarizer import HistorySummarizer
from huicode.prompts.base import PromptBundle
from huicode.providers.base import ConversationMessage, ToolCall, ToolSpec
from huicode.tools.base import ToolContext, ToolResult


class FakeSummaryProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, responses):
        self.responses = list(responses)

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):
        text = self.responses.pop(0)
        if isinstance(text, Exception):
            raise text
        if text == "__tool_call__":
            from huicode.providers.base import StreamEvent

            yield StreamEvent(kind="tool_call", tool_call=ToolCall("call_1", "Read", {"path": "a.txt"}))
            return
        from huicode.providers.base import StreamEvent

        yield StreamEvent(kind="text", text=text)


class ContextManagerTests(unittest.TestCase):
    def test_prepare_before_request_triggers_summary_when_over_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            manager = ContextManager(
                workspace,
                ContextConfig(window_tokens=60, auto_margin_tokens=20, recent_keep_tokens=10, min_recent_messages=2),
            )
            state = AgentState(
                messages=[
                    ConversationMessage("user", "旧消息" * 60),
                    ConversationMessage("assistant", "旧回复" * 60),
                    ConversationMessage("user", "新消息"),
                    ConversationMessage("assistant", "新回复"),
                ]
            )
            report = manager.prepare_before_request(
                FakeSummaryProvider(["<summary>## 当前任务\n继续</summary>"]),
                state,
                ToolContext(workspace),
                LLMConfig("openai", "fake", "https://example.test", "key"),
                PromptBundle(),
                [],
            )

            self.assertTrue(report.history_changed)
            self.assertEqual(report.reports[-1].kind, "summary")
            self.assertIn("conversation_summary", state.messages[0].content)
            self.assertEqual(state.context.summary_count, 1)

    def test_manual_compact_ignores_auto_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            manager = ContextManager(
                workspace,
                ContextConfig(window_tokens=10000, manual_margin_tokens=3000, recent_keep_tokens=10, min_recent_messages=2),
            )
            state = AgentState(
                messages=[
                    ConversationMessage("user", "旧消息" * 20),
                    ConversationMessage("assistant", "旧回复" * 20),
                    ConversationMessage("user", "新消息"),
                    ConversationMessage("assistant", "新回复"),
                ]
            )

            report = manager.manual_compact(
                FakeSummaryProvider(["<summary>## 当前任务\n继续</summary>"]),
                state,
                ToolContext(workspace),
                LLMConfig("openai", "fake", "https://example.test", "key"),
                PromptBundle(),
                [],
            )

            self.assertEqual(report.kind, "summary")
            self.assertTrue(report.summary_created)

    def test_summary_failures_open_fuse_after_three_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            manager = ContextManager(
                workspace,
                ContextConfig(window_tokens=60, auto_margin_tokens=20, recent_keep_tokens=10, min_recent_messages=2),
            )
            state = AgentState(
                messages=[
                    ConversationMessage("user", "旧消息" * 60),
                    ConversationMessage("assistant", "旧回复" * 60),
                    ConversationMessage("user", "新消息"),
                    ConversationMessage("assistant", "新回复"),
                ]
            )
            provider = FakeSummaryProvider(["没有summary", "没有summary", "没有summary"])
            config = LLMConfig("openai", "fake", "https://example.test", "key")
            for _ in range(3):
                manager.prepare_before_request(provider, state, ToolContext(workspace), config, PromptBundle(), [])

            self.assertTrue(state.context.summary_fuse_open)
            self.assertEqual(state.context.summary_failure_count, 3)

    def test_fuse_still_allows_lightweight_spill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            manager = ContextManager(workspace, ContextConfig(single_tool_result_tokens=10))
            state = AgentState()
            state.context.summary_fuse_open = True
            result, report = manager.compact_tool_result(
                ToolCall("call_1", "Read", {"path": "a.txt"}),
                ToolResult.success({"content": "x" * 400}, "ok"),
                ToolContext(workspace),
                iteration=1,
            )

            self.assertIsNotNone(report)
            self.assertIn("__spilled__", result.data)

    def test_reset_clears_context_state(self) -> None:
        manager = ContextManager(Path.cwd(), ContextConfig())
        state = AgentState()
        state.context.last_input_tokens = 99
        state.context.summary_failure_count = 2
        state.context.summary_fuse_open = True

        manager.reset(state)

        self.assertIsNone(state.context.last_input_tokens)
        self.assertEqual(state.context.summary_failure_count, 0)
        self.assertFalse(state.context.summary_fuse_open)


if __name__ == "__main__":
    unittest.main()
