from __future__ import annotations

import json
import re

from huicode.config import LLMConfig
from huicode.providers.base import ConversationMessage, Provider, StreamEvent

from .types import SummaryResult


class HistorySummarizer:
    def summarize(
        self,
        provider: Provider,
        messages_to_summarize: list[ConversationMessage],
        config: LLMConfig,
    ) -> SummaryResult:
        _ = config
        prompt = _build_summary_prompt(messages_to_summarize)
        text_parts: list[str] = []
        for event in provider.stream_chat(
            [ConversationMessage(role="user", content=prompt)],
            tools=[],
            allow_tool_calls=False,
            prompt=None,
        ):
            if event.tool_call is not None:
                return SummaryResult(ok=False, error_message="摘要阶段返回了工具调用")
            if event.kind == "text" and event.text:
                text_parts.append(event.text)
        summary = _extract_summary("".join(text_parts))
        if not summary:
            return SummaryResult(ok=False, error_message="摘要没有返回正式 summary")
        return SummaryResult(ok=True, summary_text=summary)


def _build_summary_prompt(messages: list[ConversationMessage]) -> str:
    rendered = "\n".join(_render_message(message) for message in messages)
    return (
        "你正在为 HuiCode 压缩较早对话历史。禁止调用任何工具，禁止提议再调用工具。\n"
        "请先在 <draft> 标签里写分析草稿，再在 <summary> 标签里输出正式摘要。\n"
        "正式摘要必须使用以下部分，并尽量精炼：\n"
        "## 当前任务\n"
        "## 用户目标与约束\n"
        "## 已完成动作\n"
        "## 重要发现\n"
        "## 已修改或涉及的文件\n"
        "## 关键工具结果\n"
        "## 待办事项\n"
        "## 风险与未知点\n\n"
        "需要压缩的历史如下：\n"
        f"{rendered}"
    )


def _render_message(message: ConversationMessage) -> str:
    fields = [f"role={message.role}", f"content={message.content}"]
    if message.thinking:
        fields.append(f"thinking={message.thinking}")
    if message.tool_calls:
        fields.append(
            "tool_calls="
            + json.dumps(
                [{"id": call.id, "name": call.name, "arguments": call.arguments} for call in message.tool_calls],
                ensure_ascii=False,
            )
        )
    if message.tool_result is not None:
        fields.append(f"tool_name={message.tool_name}")
        fields.append(f"tool_result={json.dumps(message.tool_result.to_model_dict(), ensure_ascii=False)}")
    return " | ".join(fields)


def _extract_summary(text: str) -> str:
    match = re.search(r"<summary>\s*(.*?)\s*</summary>", text, flags=re.S)
    if not match:
        return ""
    return match.group(1).strip()

