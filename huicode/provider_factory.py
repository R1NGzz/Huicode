from __future__ import annotations

from dataclasses import replace

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


def create_provider_with_model(config: LLMConfig, model: str) -> Provider:
    if not isinstance(model, str) or not model.strip():
        raise ValueError("覆盖 model 必须是非空字符串")
    return create_provider(replace(config, model=model.strip()))
