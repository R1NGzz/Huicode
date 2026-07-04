from __future__ import annotations

from copy import deepcopy
from typing import Any

from huicode.prompts.base import CacheUsage


def normalize_cache_usage(usage: dict[str, Any] | None) -> dict[str, Any]:
    if not usage:
        return {"cache": {}}

    normalized = deepcopy(usage)
    existing_cache = normalized.get("cache") if isinstance(normalized.get("cache"), dict) else {}
    cache = CacheUsage(
        creation_input_tokens=_int_value(usage.get("cache_creation_input_tokens")),
        read_input_tokens=_int_value(usage.get("cache_read_input_tokens")),
        cached_tokens=_openai_cached_tokens(usage),
    )
    normalized_cache = dict(existing_cache)
    normalized_cache.update(cache.to_dict())
    normalized["cache"] = normalized_cache
    return normalized


def _openai_cached_tokens(usage: dict[str, Any]) -> int:
    details = usage.get("prompt_tokens_details")
    if not isinstance(details, dict):
        return 0
    return _int_value(details.get("cached_tokens"))


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    return 0
