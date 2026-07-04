from __future__ import annotations

import json
from typing import Any, Iterator

from huicode.config import LLMConfig
from huicode.prompts import PromptBundle, normalize_cache_usage
from huicode.providers.base import ConversationMessage, StreamEvent, ToolCall, ToolSpec
from huicode.sse import post_sse


class OpenAIProvider:
    name = "openai"

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.model = config.model

    def stream_chat(
        self,
        messages: list[ConversationMessage],
        tools: list[ToolSpec] | None = None,
        allow_tool_calls: bool = True,
        prompt: PromptBundle | None = None,
    ) -> Iterator[StreamEvent]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": _serialize_prompt_messages(prompt) + [_serialize_message(message) for message in messages],
            "stream": True,
            "max_tokens": self.config.max_tokens,
        }
        if tools and allow_tool_calls:
            payload["tools"] = [_serialize_tool(tool) for tool in tools]
            payload["parallel_tool_calls"] = False
        elif not allow_tool_calls:
            payload["tool_choice"] = "none"
        if self.config.temperature is not None:
            payload["temperature"] = self.config.temperature

        tool_buffers: dict[int, dict[str, str]] = {}
        for event in post_sse(
            self._endpoint(),
            headers={
                **self.config.headers,
                "Authorization": f"Bearer {self.config.api_key}",
            },
            payload=payload,
        ):
            if event.data == "[DONE]":
                break
            data = event.json()
            if isinstance(data.get("usage"), dict):
                yield StreamEvent(kind="usage", usage=normalize_cache_usage(data["usage"]))
            for choice in data.get("choices", []):
                delta = choice.get("delta") or {}
                text = delta.get("content")
                if text:
                    yield StreamEvent(kind="text", text=text)
                for tool_delta in delta.get("tool_calls") or []:
                    index = int(tool_delta.get("index", 0))
                    buffer = tool_buffers.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if tool_delta.get("id"):
                        buffer["id"] = tool_delta["id"]
                    function = tool_delta.get("function") or {}
                    if function.get("name"):
                        buffer["name"] = function["name"]
                    if function.get("arguments"):
                        buffer["arguments"] += function["arguments"]

        for index in sorted(tool_buffers):
            buffer = tool_buffers[index]
            raw_arguments = buffer["arguments"]
            try:
                arguments = json.loads(raw_arguments or "{}")
                if not isinstance(arguments, dict):
                    arguments = {"__error__": "工具参数 JSON 必须是对象", "__raw__": raw_arguments}
            except json.JSONDecodeError as exc:
                arguments = {"__error__": f"工具参数 JSON 解析失败: {exc}", "__raw__": raw_arguments}
            yield StreamEvent(
                kind="tool_call",
                tool_call=ToolCall(
                    id=buffer["id"] or f"openai-tool-{index}",
                    name=buffer["name"],
                    arguments=arguments,
                    raw_arguments=raw_arguments,
                ),
            )

    def _endpoint(self) -> str:
        if self.config.base_url.endswith("/chat/completions"):
            return self.config.base_url
        return f"{self.config.base_url}/chat/completions"


def _serialize_message(message: ConversationMessage) -> dict[str, Any]:
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.raw_arguments or json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ],
        }
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": json.dumps(
                message.tool_result.to_model_dict() if message.tool_result else {"ok": False},
                ensure_ascii=False,
            ),
        }
    return {"role": message.role, "content": message.content}


def _serialize_prompt_messages(prompt: PromptBundle | None) -> list[dict[str, str]]:
    if prompt is None:
        return []
    return [{"role": "system", "content": text} for text in prompt.system_texts()]


def _serialize_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
