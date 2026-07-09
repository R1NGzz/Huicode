from __future__ import annotations

import json
from dataclasses import dataclass
from math import ceil

from huicode.context.state import ContextState
from huicode.prompts import PromptBundle
from huicode.providers.base import ConversationMessage, ToolSpec


@dataclass(frozen=True)
class TokenEstimate:
    tokens: int
    chars: int
    source: str = "chars"


class TokenEstimator:
    def estimate_text(self, text: str) -> int:
        return _chars_to_tokens(len(text))

    def estimate_message(self, message: ConversationMessage) -> TokenEstimate:
        pieces = [message.role, message.content, message.thinking, message.thinking_signature]
        for call in message.tool_calls:
            pieces.extend([call.id, call.name, call.raw_arguments or json.dumps(call.arguments, ensure_ascii=False)])
        if message.tool_name:
            pieces.append(message.tool_name)
        if message.tool_call_id:
            pieces.append(message.tool_call_id)
        if message.tool_result is not None:
            pieces.append(json.dumps(message.tool_result.to_model_dict(), ensure_ascii=False))
        chars = sum(len(piece) for piece in pieces if piece)
        return TokenEstimate(tokens=_chars_to_tokens(chars), chars=chars)

    def estimate_messages(self, messages: list[ConversationMessage]) -> TokenEstimate:
        chars = sum(self.estimate_message(message).chars for message in messages)
        return TokenEstimate(tokens=_chars_to_tokens(chars), chars=chars)

    def estimate_request(
        self,
        messages: list[ConversationMessage],
        prompt: PromptBundle | None,
        tools: list[ToolSpec] | None,
        state: ContextState | None = None,
    ) -> TokenEstimate:
        chars = self.estimate_messages(messages).chars
        if prompt is not None:
            chars += sum(len(text) for text in prompt.system_texts())
        if tools:
            chars += sum(
                len(tool.name) + len(tool.description) + len(json.dumps(tool.parameters, ensure_ascii=False))
                for tool in tools
            )
        if state is None or state.last_input_tokens is None or state.last_estimated_chars is None:
            return TokenEstimate(tokens=_chars_to_tokens(chars), chars=chars, source="chars")
        delta_chars = max(0, chars - state.last_estimated_chars)
        estimated_tokens = state.last_input_tokens + _chars_to_tokens(delta_chars)
        return TokenEstimate(tokens=estimated_tokens, chars=chars, source="usage_anchor")

    def record_usage(
        self,
        state: ContextState,
        usage: dict[str, object],
        request_estimate: TokenEstimate,
    ) -> None:
        raw_tokens = usage.get("input_tokens")
        if raw_tokens is None:
            raw_tokens = usage.get("prompt_tokens")
        if isinstance(raw_tokens, (int, float)) and int(raw_tokens) > 0:
            state.last_input_tokens = int(raw_tokens)
        state.last_estimated_request_tokens = request_estimate.tokens
        state.last_estimated_chars = request_estimate.chars


def _chars_to_tokens(chars: int) -> int:
    if chars <= 0:
        return 0
    return ceil(chars / 4)

