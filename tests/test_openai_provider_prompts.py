import unittest
from pathlib import Path
from unittest.mock import patch

from huicode.config import LLMConfig
from huicode.prompts import PromptContext, build_prompt_bundle
from huicode.providers.base import ConversationMessage
from huicode.providers.openai import OpenAIProvider
from huicode.sse import SSEEvent


def make_prompt():
    return build_prompt_bundle(
        PromptContext(
            workspace=Path("C:/work/project"),
            platform="Windows",
            shell="powershell",
            now="2026-07-04T12:00:00+08:00",
            mode="chat",
            iteration=1,
            max_iterations=8,
            available_tools=("Read",),
        )
    )


class OpenAIProviderPromptTests(unittest.TestCase):
    def test_prepends_prompt_as_system_messages(self) -> None:
        config = LLMConfig("openai", "gpt-test", "https://api.openai.com/v1", "key")
        with patch("huicode.providers.openai.post_sse", return_value=iter([SSEEvent(None, "[DONE]")])) as mock_post:
            list(
                OpenAIProvider(config).stream_chat(
                    [ConversationMessage("user", "hi")],
                    prompt=make_prompt(),
                )
            )

        messages = mock_post.call_args.kwargs["payload"]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("## 身份", messages[0]["content"])
        self.assertIn('<huicode_context type="environment" scope="turn">', messages[1]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "hi"})

    def test_normalizes_openai_cache_usage(self) -> None:
        config = LLMConfig("openai", "gpt-test", "https://api.openai.com/v1", "key")
        events = [
            SSEEvent(None, '{"choices":[],"usage":{"prompt_tokens":10,"prompt_tokens_details":{"cached_tokens":4}}}'),
            SSEEvent(None, "[DONE]"),
        ]
        with patch("huicode.providers.openai.post_sse", return_value=iter(events)):
            chunks = list(OpenAIProvider(config).stream_chat([ConversationMessage("user", "hi")]))

        self.assertEqual(chunks[0].usage["cache"]["cached_tokens"], 4)


if __name__ == "__main__":
    unittest.main()
