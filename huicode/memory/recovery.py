from __future__ import annotations

from huicode.providers.base import ConversationMessage


def recover_safe_messages(messages: list[ConversationMessage]) -> tuple[list[ConversationMessage], bool, str]:
    safe: list[ConversationMessage] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == "tool":
            return safe, True, "发现孤立工具结果，已截断"
        if message.role != "assistant" or not message.tool_calls:
            safe.append(message)
            index += 1
            continue

        expected_ids = [call.id for call in message.tool_calls]
        group = [message]
        cursor = index + 1
        ok = True
        for expected_id in expected_ids:
            if cursor >= len(messages):
                ok = False
                break
            tool_message = messages[cursor]
            if tool_message.role != "tool" or tool_message.tool_call_id != expected_id:
                ok = False
                break
            group.append(tool_message)
            cursor += 1
        if not ok:
            return safe, True, "发现未配对工具调用，已截断"
        safe.extend(group)
        index = cursor
    return safe, False, ""
