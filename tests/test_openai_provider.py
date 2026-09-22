import unittest
from unittest.mock import patch

from huicode.config import LLMConfig, OrchestrationConfig
from huicode.providers.base import ChatMessage, ToolSpec
from huicode.providers.openai import OpenAIProvider
from huicode.sse import SSEEvent


class OpenAIProviderTests(unittest.TestCase):
    def test_streams_text_deltas_and_builds_request(self) -> None:
        config = LLMConfig(
            protocol="openai",
            model="gpt-test",
            base_url="https://api.openai.com/v1",
            api_key="secret-key",
            reasoning_effort="high",
            headers={"HTTP-Referer": "https://example.test", "X-Title": "HuiCode"},
        )
        events = [
            SSEEvent(None, '{"choices":[{"delta":{"content":"你"}}]}'),
            SSEEvent(None, '{"choices":[{"delta":{"content":"好"}}]}'),
            SSEEvent(None, "[DONE]"),
        ]

        with patch("huicode.providers.openai.post_sse", return_value=iter(events)) as mock_post:
            chunks = list(
                OpenAIProvider(config).stream_chat(
                    [
                        ChatMessage(role="user", content="第一轮"),
                        ChatMessage(role="assistant", content="回答"),
                        ChatMessage(role="user", content="第二轮"),
                    ]
                )
            )

        self.assertEqual("".join(chunk.text for chunk in chunks), "你好")
        self.assertTrue(all(chunk.kind == "text" for chunk in chunks))
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-key")
        self.assertEqual(kwargs["headers"]["HTTP-Referer"], "https://example.test")
        self.assertEqual(kwargs["headers"]["X-Title"], "HuiCode")
        self.assertEqual(kwargs["payload"]["model"], "gpt-test")
        self.assertEqual(kwargs["payload"]["reasoning_effort"], "high")
        self.assertEqual(len(kwargs["payload"]["messages"]), 3)
        self.assertTrue(kwargs["payload"]["stream"])
        self.assertEqual(mock_post.call_args.args[0], "https://api.openai.com/v1/chat/completions")

    def test_enables_parallel_tool_calls_for_complex_orchestration(self) -> None:
        config = LLMConfig(
            protocol="openai",
            model="gpt-test",
            base_url="https://example.test/v1",
            api_key="secret-key",
            orchestration=OrchestrationConfig(parallel_tool_calls=True),
        )
        events = [SSEEvent(None, "[DONE]")]
        with patch("huicode.providers.openai.post_sse", return_value=iter(events)) as mock_post:
            list(
                OpenAIProvider(config).stream_chat(
                    [],
                    tools=[ToolSpec(name="Read", description="read", parameters={"type": "object"})],
                )
            )

        self.assertTrue(mock_post.call_args.kwargs["payload"]["parallel_tool_calls"])


if __name__ == "__main__":
    unittest.main()
