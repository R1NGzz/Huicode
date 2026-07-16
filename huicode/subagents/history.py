from __future__ import annotations

from copy import deepcopy

from huicode.providers.base import ConversationMessage


def select_protocol_safe_history(
    messages: list[ConversationMessage] | tuple[ConversationMessage, ...],
) -> tuple[ConversationMessage, ...]:
    safe: list[ConversationMessage] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == "tool":
            index += 1
            continue
        if message.role != "assistant" or not message.tool_calls:
            safe.append(deepcopy(message))
            index += 1
            continue
        expected = {call.id for call in message.tool_calls}
        results: list[ConversationMessage] = []
        cursor = index + 1
        while cursor < len(messages) and messages[cursor].role == "tool":
            result = messages[cursor]
            if result.tool_call_id in expected:
                results.append(result)
            cursor += 1
        if {result.tool_call_id for result in results} != expected:
            break
        safe.append(deepcopy(message))
        safe.extend(deepcopy(results))
        index = cursor
    return tuple(safe)
