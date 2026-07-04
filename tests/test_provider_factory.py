import unittest

from huicode.config import LLMConfig
from huicode.provider_factory import create_provider
from huicode.providers.anthropic import AnthropicProvider
from huicode.providers.openai import OpenAIProvider


class ProviderFactoryTests(unittest.TestCase):
    def test_creates_openai_provider(self) -> None:
        provider = create_provider(
            LLMConfig(
                protocol="openai",
                model="gpt-test",
                base_url="https://api.openai.com/v1",
                api_key="key",
            )
        )

        self.assertIsInstance(provider, OpenAIProvider)

    def test_creates_anthropic_provider(self) -> None:
        provider = create_provider(
            LLMConfig(
                protocol="anthropic",
                model="claude-test",
                base_url="https://api.anthropic.com/v1",
                api_key="key",
            )
        )

        self.assertIsInstance(provider, AnthropicProvider)

    def test_rejects_unknown_protocol(self) -> None:
        config = LLMConfig(protocol="unknown", model="test", base_url="http://example.test", api_key="key")

        with self.assertRaisesRegex(ValueError, "unknown"):
            create_provider(config)


if __name__ == "__main__":
    unittest.main()
