from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterator, Literal, Protocol


if TYPE_CHECKING:
    from huicode.prompts import PromptBundle


Role = Literal["user", "assistant", "tool"]
StreamEventKind = Literal["text", "thinking", "tool_call", "usage"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


@dataclass(frozen=True)
class ConversationMessage:
    role: Role
    content: str
    thinking: str = ""
    thinking_signature: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_result: Any | None = None


ChatMessage = ConversationMessage


@dataclass(frozen=True)
class StreamEvent:
    kind: StreamEventKind
    text: str = ""
    tool_call: ToolCall | None = None
    thinking_signature: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    name: str
    model: str

    def stream_chat(
        self,
        messages: list[ConversationMessage],
        tools: list[ToolSpec] | None = None,
        allow_tool_calls: bool = True,
        prompt: PromptBundle | None = None,
    ) -> Iterator[StreamEvent]:
        ...
