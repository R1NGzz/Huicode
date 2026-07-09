from __future__ import annotations

from huicode.config import ContextConfig
from huicode.context.estimator import TokenEstimator
from huicode.context.segments import build_history_segments
from huicode.providers.base import ConversationMessage


def split_recent_messages(
    messages: list[ConversationMessage],
    config: ContextConfig,
    estimator: TokenEstimator,
) -> tuple[list[ConversationMessage], list[ConversationMessage]]:
    segments = build_history_segments(messages, estimator)
    if not segments:
        return [], []
    recent_segments = []
    recent_tokens = 0
    recent_messages = 0
    for segment in reversed(segments):
        recent_segments.append(segment)
        recent_tokens += segment.estimated_tokens
        recent_messages += len(segment.messages)
        if recent_messages >= config.min_recent_messages and recent_tokens >= config.recent_keep_tokens:
            break
    recent_segments.reverse()
    recent = [message for segment in recent_segments for message in segment.messages]
    older_count = len(messages) - len(recent)
    older = messages[:older_count]
    return older, recent


def apply_summary(
    older_messages: list[ConversationMessage],
    recent_messages: list[ConversationMessage],
    summary_text: str,
) -> list[ConversationMessage]:
    _ = older_messages
    summary_message = ConversationMessage(
        role="user",
        content=(
            '<huicode_context type="conversation_summary" scope="compressed_history">\n'
            f"{summary_text.strip()}\n"
            "</huicode_context>"
        ),
    )
    boundary_message = ConversationMessage(
        role="user",
        content=(
            '<huicode_context type="compression_boundary" scope="compressed_history">\n'
            "以下历史已经压缩为摘要。摘要只是导航信息，不是文件事实来源。"
            "如果需要文件细节、命令输出或完整工具结果，必须重新读取文件或重新调用工具，不能凭摘要脑补代码或内容。\n"
            "</huicode_context>"
        ),
    )
    return [summary_message, boundary_message, *recent_messages]

