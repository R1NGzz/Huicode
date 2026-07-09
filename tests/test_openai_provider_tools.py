import unittest
from unittest.mock import patch

from huicode.config import LLMConfig
from huicode.providers.base import ConversationMessage, ToolCall, ToolSpec
from huicode.providers.openai import OpenAIProvider
from huicode.sse import SSEEvent
from huicode.tools.base import ToolResult


class OpenAIProviderToolTests(unittest.TestCase):
    def test_sends_tool_schema_and_parses_fragmented_arguments(self) -> None:
        config = LLMConfig("openai", "gpt-test", "https://api.openai.com/v1", "key")
        events = [
            SSEEvent(None, '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"Read","arguments":"{\\"pa"}}]}}]}'),
            SSEEvent(None, '{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"th\\":\\"README.md\\"}"}}]}}]}'),
            SSEEvent(None, "[DONE]"),
        ]
        tool = ToolSpec("Read", "读取文件", {"type": "object", "properties": {"path": {"type": "string"}}})

        with patch("huicode.providers.openai.post_sse", return_value=iter(events)) as mock_post:
            chunks = list(OpenAIProvider(config).stream_chat([ConversationMessage("user", "读 README")], [tool]))

        self.assertEqual(chunks[0].kind, "tool_call")
        self.assertEqual(chunks[0].tool_call.name, "Read")
        self.assertEqual(chunks[0].tool_call.arguments, {"path": "README.md"})
        payload = mock_post.call_args.kwargs["payload"]
        self.assertEqual(payload["tools"][0]["function"]["name"], "Read")
        self.assertFalse(payload["parallel_tool_calls"])

    def test_serializes_tool_history_and_can_disable_tools(self) -> None:
        config = LLMConfig("openai", "gpt-test", "https://api.openai.com/v1", "key")
        call = ToolCall(id="call_1", name="Read", arguments={"path": "README.md"}, raw_arguments='{"path":"README.md"}')
        messages = [
            ConversationMessage("user", "读 README"),
            ConversationMessage("assistant", "", tool_calls=[call]),
            ConversationMessage("tool", "", tool_call_id="call_1", tool_name="Read", tool_result=ToolResult.success({"content": "hi"}, "ok")),
        ]

        with patch("huicode.providers.openai.post_sse", return_value=iter([SSEEvent(None, "[DONE]")])) as mock_post:
            list(OpenAIProvider(config).stream_chat(messages, tools=[], allow_tool_calls=False))

        payload = mock_post.call_args.kwargs["payload"]
        self.assertEqual(payload["messages"][1]["tool_calls"][0]["id"], "call_1")
        self.assertEqual(payload["messages"][2]["role"], "tool")
        self.assertEqual(payload["tool_choice"], "none")

    def test_forwards_usage_event_when_present(self) -> None:
        config = LLMConfig("openai", "gpt-test", "https://api.openai.com/v1", "key")
        events = [
            SSEEvent(None, '{"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":7}}'),
            SSEEvent(None, "[DONE]"),
        ]

        with patch("huicode.providers.openai.post_sse", return_value=iter(events)):
            chunks = list(OpenAIProvider(config).stream_chat([ConversationMessage("user", "hi")]))

        self.assertEqual(chunks[0].kind, "usage")
        self.assertEqual(chunks[0].usage["prompt_tokens"], 11)

    def test_serializes_summary_and_boundary_messages_before_tool_history(self) -> None:
        config = LLMConfig("openai", "gpt-test", "https://api.openai.com/v1", "key")
        call = ToolCall(id="call_1", name="Read", arguments={"path": "README.md"}, raw_arguments='{"path":"README.md"}')
        messages = [
            ConversationMessage("user", '<huicode_context type="conversation_summary">summary</huicode_context>'),
            ConversationMessage("user", '<huicode_context type="compression_boundary">boundary</huicode_context>'),
            ConversationMessage("assistant", "", tool_calls=[call]),
            ConversationMessage("tool", "", tool_call_id="call_1", tool_name="Read", tool_result=ToolResult.success({"content": "hi"}, "ok")),
        ]

        with patch("huicode.providers.openai.post_sse", return_value=iter([SSEEvent(None, "[DONE]")])) as mock_post:
            list(OpenAIProvider(config).stream_chat(messages, tools=[], allow_tool_calls=False))

        payload = mock_post.call_args.kwargs["payload"]
        self.assertIn("conversation_summary", payload["messages"][0]["content"])
        self.assertIn("compression_boundary", payload["messages"][1]["content"])
        self.assertEqual(payload["messages"][2]["tool_calls"][0]["id"], "call_1")
        self.assertEqual(payload["messages"][3]["role"], "tool")


if __name__ == "__main__":
    unittest.main()
