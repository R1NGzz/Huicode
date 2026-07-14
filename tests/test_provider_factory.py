import unittest

from huicode.config import LLMConfig
from huicode.provider_factory import create_provider, create_provider_with_model
from huicode.providers.anthropic import AnthropicProvider
from huicode.providers.openai import OpenAIProvider


class ProviderFactoryTests(unittest.TestCase):
    def test_model_override_preserves_connection_and_thinking_settings(self) -> None:
        config = LLMConfig(
            "openai",
            "main",
            "https://example.test/v1",
            "secret",
            headers={"X-Test": "value"},
        )

        provider = create_provider_with_model(config, "alternate")

        self.assertEqual(provider.model, "alternate")
        self.assertEqual(provider.config.base_url, config.base_url)
        self.assertEqual(provider.config.api_key, config.api_key)
        self.assertEqual(provider.config.headers, config.headers)
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
