from __future__ import annotations

from dataclasses import dataclass

from huicode.context.estimator import TokenEstimator
from huicode.providers.base import ConversationMessage


@dataclass(frozen=True)
class HistorySegment:
    messages: list[ConversationMessage]
    estimated_tokens: int
    contains_tool_pair: bool = False


def build_history_segments(
    messages: list[ConversationMessage],
    estimator: TokenEstimator,
) -> list[HistorySegment]:
    segments: list[HistorySegment] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == "assistant" and message.tool_calls:
            group = [message]
            cursor = index + 1
            while cursor < len(messages) and messages[cursor].role == "tool":
                group.append(messages[cursor])
                cursor += 1
            segments.append(
                HistorySegment(
                    messages=group,
                    estimated_tokens=estimator.estimate_messages(group).tokens,
                    contains_tool_pair=True,
                )
            )
            index = cursor
            continue
        segments.append(
            HistorySegment(messages=[message], estimated_tokens=estimator.estimate_message(message).tokens)
        )
        index += 1
    return segments

