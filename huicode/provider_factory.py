from __future__ import annotations

from huicode.config import LLMConfig
from huicode.providers.anthropic import AnthropicProvider
from huicode.providers.base import Provider
from huicode.providers.openai import OpenAIProvider


def create_provider(config: LLMConfig) -> Provider:
    if config.protocol == "openai":
        return OpenAIProvider(config)
    if config.protocol == "anthropic":
        return AnthropicProvider(config)
    raise ValueError(f"不支持的 protocol: {config.protocol}")
