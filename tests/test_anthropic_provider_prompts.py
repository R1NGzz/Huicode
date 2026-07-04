import unittest
from pathlib import Path
from unittest.mock import patch

from huicode.config import LLMConfig
from huicode.prompts import PromptContext, build_prompt_bundle
from huicode.providers.anthropic import AnthropicProvider
from huicode.providers.base import ConversationMessage
from huicode.sse import SSEEvent


def make_prompt():
    return build_prompt_bundle(
        PromptContext(
            workspace=Path("C:/work/project"),
            platform="Windows",
            shell="powershell",
            now="2026-07-04T12:00:00+08:00",
            mode="plan",
            iteration=1,
            max_iterations=8,
            available_tools=("Read", "Find"),
            read_only_tool_names=("Read", "Find", "Search", "Glob"),
        )
    )


class AnthropicProviderPromptTests(unittest.TestCase):
    def test_sends_prompt_as_top_level_system_blocks(self) -> None:
        config = LLMConfig("anthropic", "claude-test", "https://api.anthropic.com/v1", "key")
        with patch(
            "huicode.providers.anthropic.post_sse",
            return_value=iter([SSEEvent("message_stop", '{"type":"message_stop"}')]),
        ) as mock_post:
            list(
                AnthropicProvider(config).stream_chat(
                    [ConversationMessage("user", "hi")],
                    prompt=make_prompt(),
                )
            )

        payload = mock_post.call_args.kwargs["payload"]
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hi"}])
        self.assertEqual(payload["system"][0]["type"], "text")
        self.assertIn("## 身份", payload["system"][0]["text"])
        self.assertIn('<huicode_context type="environment" scope="turn">', payload["system"][1]["text"])
        self.assertIn('<huicode_instruction type="plan_mode" scope="turn">', payload["system"][2]["text"])

    def test_normalizes_anthropic_cache_usage(self) -> None:
        config = LLMConfig("anthropic", "claude-test", "https://api.anthropic.com/v1", "key")
        events = [
            SSEEvent(
                "message_start",
                '{"type":"message_start","usage":{"input_tokens":9,"cache_creation_input_tokens":2,"cache_read_input_tokens":5}}',
            ),
            SSEEvent("message_stop", '{"type":"message_stop"}'),
        ]
        with patch("huicode.providers.anthropic.post_sse", return_value=iter(events)):
            chunks = list(AnthropicProvider(config).stream_chat([ConversationMessage("user", "hi")]))

        self.assertEqual(chunks[0].usage["cache"]["creation_input_tokens"], 2)
        self.assertEqual(chunks[0].usage["cache"]["read_input_tokens"], 5)


if __name__ == "__main__":
    unittest.main()
