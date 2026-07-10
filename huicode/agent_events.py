from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from huicode.context.state import ContextState
from huicode.memory.types import MemoryRuntimeState
from huicode.providers.base import ConversationMessage, ToolCall
from huicode.tools.base import ToolResult


AgentMode = Literal["chat", "plan", "do"]
AgentEventKind = Literal[
    "text",
    "thinking",
    "tool_call",
    "tool_result",
    "progress",
    "usage",
    "context",
    "memory",
    "error",
    "done",
]


@dataclass(frozen=True)
class AgentEvent:
    kind: AgentEventKind
    text: str = ""
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    iteration: int | None = None
    stop_reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectedResponse:
    text: str = ""
    thinking: str = ""
    thinking_signature: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentOptions:
    max_iterations: int = 50
    max_unknown_tools: int = 2
    max_empty_responses: int = 1
    mode: AgentMode = "chat"
    read_only_tool_names: frozenset[str] = field(
        default_factory=lambda: frozenset({"Read", "Find", "Search", "Glob"})
    )


@dataclass
class AgentState:
    messages: list[ConversationMessage] = field(default_factory=list)
    last_plan: str = ""
    context: ContextState = field(default_factory=ContextState)
    memory: MemoryRuntimeState = field(default_factory=MemoryRuntimeState)
    cancel_requested: bool = False
    unknown_tool_count: int = 0
    iterations: int = 0


@dataclass(frozen=True)
class ToolBatch:
    parallel_read_calls: list[ToolCall] = field(default_factory=list)
    serial_calls: list[ToolCall] = field(default_factory=list)
