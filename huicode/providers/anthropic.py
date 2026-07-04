from __future__ import annotations

import json
from typing import Any, Iterator

from huicode.config import LLMConfig
from huicode.prompts import PromptBundle, normalize_cache_usage
from huicode.providers.base import ConversationMessage, StreamEvent, ToolCall, ToolSpec
from huicode.sse import post_sse


class AnthropicProvider:
    name = "anthropic"

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
            "messages": _serialize_messages(messages),
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }
        system = _serialize_prompt_system(prompt)
        if system:
            payload["system"] = system
        if tools and allow_tool_calls:
            payload["tools"] = [_serialize_tool(tool) for tool in tools]
        if self.config.temperature is not None:
            payload["temperature"] = self.config.temperature
        if self.config.thinking.enabled:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.config.thinking.budget_tokens,
            }

        tool_buffers: dict[int, dict[str, str]] = {}
        thinking_blocks: dict[int, dict[str, str]] = {}
        for event in post_sse(
            self._endpoint(),
            headers={
                **self.config.headers,
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
            },
            payload=payload,
        ):
            if event.event == "error":
                raise RuntimeError(event.data)
            data = event.json()
            if isinstance(data.get("usage"), dict):
                yield StreamEvent(kind="usage", usage=normalize_cache_usage(data["usage"]))
            if data.get("type") == "message_stop":
                break
            if data.get("type") == "content_block_start":
                content_block = data.get("content_block") or {}
                if content_block.get("type") == "tool_use":
                    index = int(data.get("index", 0))
                    tool_buffers[index] = {
                        "id": content_block.get("id", f"anthropic-tool-{index}"),
                        "name": content_block.get("name", ""),
                        "arguments": "",
                    }
                elif content_block.get("type") == "thinking":
                    index = int(data.get("index", 0))
                    thinking_blocks[index] = {
                        "thinking": content_block.get("thinking", ""),
                        "signature": content_block.get("signature", ""),
                    }
                    yield StreamEvent(kind="thinking", text="")
                continue
            if data.get("type") != "content_block_delta":
                continue

            delta = data.get("delta") or {}
            delta_type = delta.get("type")
            if delta_type == "text_delta" and delta.get("text"):
                yield StreamEvent(kind="text", text=delta["text"])
            elif delta_type == "thinking_delta" and delta.get("thinking"):
                index = int(data.get("index", 0))
                block = thinking_blocks.setdefault(index, {"thinking": "", "signature": ""})
                block["thinking"] += delta["thinking"]
                yield StreamEvent(kind="thinking", text=delta["thinking"])
            elif delta_type == "signature_delta" and delta.get("signature"):
                index = int(data.get("index", 0))
                block = thinking_blocks.setdefault(index, {"thinking": "", "signature": ""})
                block["signature"] += delta["signature"]
                yield StreamEvent(kind="thinking", text="", thinking_signature=delta["signature"])
            elif delta_type == "input_json_delta":
                index = int(data.get("index", 0))
                buffer = tool_buffers.setdefault(index, {"id": f"anthropic-tool-{index}", "name": "", "arguments": ""})
                buffer["arguments"] += delta.get("partial_json", "")

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
                    id=buffer["id"],
                    name=buffer["name"],
                    arguments=arguments,
                    raw_arguments=raw_arguments,
                ),
            )

    def _endpoint(self) -> str:
        if self.config.base_url.endswith("/messages"):
            return self.config.base_url
        return f"{self.config.base_url}/messages"


def _serialize_messages(messages: list[ConversationMessage]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == "assistant" and message.tool_calls:
            content: list[dict[str, Any]] = []
            if message.thinking or message.thinking_signature:
                thinking_block = {"type": "thinking", "thinking": message.thinking}
                if message.thinking_signature:
                    thinking_block["signature"] = message.thinking_signature
                content.append(thinking_block)
            if message.content:
                content.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                content.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments})
            serialized.append({"role": "assistant", "content": content})
            index += 1
        elif message.role == "assistant" and (message.thinking or message.thinking_signature):
            thinking_block = {"type": "thinking", "thinking": message.thinking}
            if message.thinking_signature:
                thinking_block["signature"] = message.thinking_signature
            content = [thinking_block]
            if message.content:
                content.append({"type": "text", "text": message.content})
            serialized.append({"role": "assistant", "content": content})
            index += 1
        elif message.role == "tool":
            content: list[dict[str, Any]] = []
            while index < len(messages) and messages[index].role == "tool":
                content.append(_serialize_tool_result(messages[index]))
                index += 1
            serialized.append(
                {
                    "role": "user",
                    "content": content,
                }
            )
        else:
            serialized.append({"role": message.role, "content": message.content})
            index += 1
    return serialized


def _serialize_tool_result(message: ConversationMessage) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": message.tool_call_id,
        "content": json.dumps(
            message.tool_result.to_model_dict() if message.tool_result else {"ok": False},
            ensure_ascii=False,
        ),
    }


def _serialize_prompt_system(prompt: PromptBundle | None) -> list[dict[str, str]]:
    if prompt is None:
        return []
    return [{"type": "text", "text": text} for text in prompt.system_texts()]


def _serialize_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters,
    }
