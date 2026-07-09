import unittest

from huicode.config import LLMConfig
from huicode.context.summarizer import HistorySummarizer
from huicode.providers.base import ConversationMessage, StreamEvent, ToolCall


class ScriptedProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, events):
        self.events = events
        self.calls = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools or []),
                "allow_tool_calls": allow_tool_calls,
                "prompt": prompt,
            }
        )
        yield from self.events


class ContextSummarizerTests(unittest.TestCase):
    def test_summarizes_and_drops_draft(self) -> None:
        provider = ScriptedProvider(
            [
                StreamEvent(kind="text", text="<draft>分析草稿</draft>"),
                StreamEvent(kind="text", text="<summary>## 当前任务\n继续实现</summary>"),
            ]
        )
        summarizer = HistorySummarizer()
        config = LLMConfig("openai", "fake", "https://example.test", "key")

        result = summarizer.summarize(provider, [ConversationMessage("user", "hi")], config)

        self.assertTrue(result.ok)
        self.assertEqual(result.summary_text, "## 当前任务\n继续实现")
        self.assertFalse(provider.calls[0]["allow_tool_calls"])
        self.assertEqual(provider.calls[0]["tools"], [])

    def test_tool_call_during_summary_is_failure(self) -> None:
        provider = ScriptedProvider(
            [
                StreamEvent(
                    kind="tool_call",
                    tool_call=ToolCall(id="call_1", name="Read", arguments={"path": "README.md"}),
                )
            ]
        )
        summarizer = HistorySummarizer()
        config = LLMConfig("openai", "fake", "https://example.test", "key")

        result = summarizer.summarize(provider, [ConversationMessage("user", "hi")], config)

        self.assertFalse(result.ok)
        self.assertIn("工具调用", result.error_message)

    def test_missing_summary_tag_is_failure(self) -> None:
        provider = ScriptedProvider([StreamEvent(kind="text", text="没有正式标签")])
        summarizer = HistorySummarizer()
        config = LLMConfig("openai", "fake", "https://example.test", "key")

        result = summarizer.summarize(provider, [ConversationMessage("user", "hi")], config)

        self.assertFalse(result.ok)
        self.assertIn("summary", result.error_message)


if __name__ == "__main__":
    unittest.main()

