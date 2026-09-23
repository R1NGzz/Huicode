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


def history_is_protocol_safe(messages: list[ConversationMessage]) -> bool:
    """校验历史里每个工具结果都紧跟声明了它的 assistant 调用。

    只覆盖压缩可能破坏的部分：孤立的 tool 消息（前面没有 assistant 调用），以及
    tool_call_id 与调用声明不匹配。assistant 声明了调用却拿不到结果的悬空调用交给
    既有的恢复逻辑处理，不在这里拦截，避免压缩被无关的历史问题挡住。
    """
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == "tool":
            return False
        if message.role == "assistant" and message.tool_calls:
            declared = {call.id for call in message.tool_calls}
            cursor = index + 1
            while cursor < len(messages) and messages[cursor].role == "tool":
                if messages[cursor].tool_call_id not in declared:
                    return False
                cursor += 1
            index = cursor
            continue
        index += 1
    return True

