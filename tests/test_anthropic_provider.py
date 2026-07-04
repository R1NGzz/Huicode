import unittest
from unittest.mock import patch

from huicode.config import LLMConfig, ThinkingConfig
from huicode.providers.anthropic import AnthropicProvider
from huicode.providers.base import ChatMessage
from huicode.sse import SSEEvent


class AnthropicProviderTests(unittest.TestCase):
    def test_streams_text_and_thinking_deltas(self) -> None:
        config = LLMConfig(
            protocol="anthropic",
            model="claude-test",
            base_url="https://api.anthropic.com/v1",
            api_key="secret-key",
            thinking=ThinkingConfig(enabled=True, budget_tokens=1024, show=True),
            headers={"X-Title": "HuiCode"},
        )
        events = [
            SSEEvent(
                "content_block_delta",
                '{"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"思考"}}',
            ),
            SSEEvent(
                "content_block_delta",
                '{"type":"content_block_delta","delta":{"type":"text_delta","text":"完成"}}',
            ),
            SSEEvent("message_stop", '{"type":"message_stop"}'),
        ]

        with patch("huicode.providers.anthropic.post_sse", return_value=iter(events)) as mock_post:
            chunks = list(
                AnthropicProvider(config).stream_chat(
                    [
                        ChatMessage(role="user", content="第一轮"),
                        ChatMessage(role="assistant", content="回答"),
                        ChatMessage(role="user", content="第二轮"),
                    ]
                )
            )

        self.assertEqual([chunk.kind for chunk in chunks], ["thinking", "text"])
        self.assertEqual([chunk.text for chunk in chunks], ["思考", "完成"])
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["x-api-key"], "secret-key")
        self.assertEqual(kwargs["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(kwargs["headers"]["X-Title"], "HuiCode")
        self.assertEqual(kwargs["payload"]["thinking"]["type"], "enabled")
        self.assertEqual(kwargs["payload"]["thinking"]["budget_tokens"], 1024)
        self.assertEqual(len(kwargs["payload"]["messages"]), 3)
        self.assertEqual(mock_post.call_args.args[0], "https://api.anthropic.com/v1/messages")


if __name__ == "__main__":
    unittest.main()
