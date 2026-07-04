import unittest
from unittest.mock import patch

from huicode.config import LLMConfig
from huicode.providers.base import ChatMessage
from huicode.providers.openai import OpenAIProvider
from huicode.sse import SSEEvent


class OpenAIProviderTests(unittest.TestCase):
    def test_streams_text_deltas_and_builds_request(self) -> None:
        config = LLMConfig(
            protocol="openai",
            model="gpt-test",
            base_url="https://api.openai.com/v1",
            api_key="secret-key",
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
        self.assertEqual(len(kwargs["payload"]["messages"]), 3)
        self.assertTrue(kwargs["payload"]["stream"])
        self.assertEqual(mock_post.call_args.args[0], "https://api.openai.com/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
