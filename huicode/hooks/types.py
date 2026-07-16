from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeAlias


HookEventName = Literal[
    "session_start",
    "session_end",
    "turn_start",
    "turn_end",
    "message_received",
    "message_completed",
    "tool_before",
    "tool_after",
    "context_before_compact",
    "context_after_compact",
    "agent_error",
]
HOOK_EVENT_NAMES: frozenset[str] = frozenset(
    {
        "session_start",
        "session_end",
        "turn_start",
        "turn_end",
        "message_received",
        "message_completed",
        "tool_before",
        "tool_after",
        "context_before_compact",
        "context_after_compact",
        "agent_error",
    }
)

MatchOperator = Literal["exact", "glob", "regex"]
ConditionMode = Literal["all", "any"]
PromptScope = Literal["next_request", "turn", "session"]
HookStatus = Literal["success", "denied", "failed", "timeout", "skipped", "scheduled"]


@dataclass(frozen=True)
class HookEvent:
    name: HookEventName
    occurred_at: str
    session_id: str
    workspace: Path
    mode: str = "chat"
    turn_id: str | None = None
    iteration: int = 0
    agent_scope: str = "main"
    data: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "event": self.name,
            "occurred_at": self.occurred_at,
            "session_id": self.session_id,
            "workspace": self.workspace.as_posix(),
            "mode": self.mode,
            "turn_id": self.turn_id,
            "iteration": self.iteration,
            "agent_scope": self.agent_scope,
        }
        payload.update(self.data)
        return payload


@dataclass(frozen=True)
class HookPredicate:
    field: str
    operator: MatchOperator
    value: str
    negate: bool = False


@dataclass(frozen=True)
class HookCondition:
    mode: ConditionMode
    predicates: tuple[HookPredicate, ...]


@dataclass(frozen=True)
class CommandAction:
    type: Literal["command"] = "command"
    command: str = ""
    args: tuple[str, ...] = ()
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptAction:
    type: Literal["prompt"] = "prompt"
    content: str = ""
    scope: PromptScope = "next_request"


@dataclass(frozen=True)
class HttpAction:
    type: Literal["http"] = "http"
    url: str = ""
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    expected_status: tuple[int, int] = (200, 299)


@dataclass(frozen=True)
class SubagentAction:
    type: Literal["subagent"] = "subagent"
    task: str = ""
    role: str = "general"


HookAction: TypeAlias = CommandAction | PromptAction | HttpAction | SubagentAction


@dataclass(frozen=True)
class HookRule:
    id: str
    event: HookEventName
    action: HookAction
    condition: HookCondition | None = None
    enabled: bool = True
    once: bool = False
    async_run: bool = False
    timeout_seconds: int = 30
    source: str = "unknown"
    source_path: str = ""


@dataclass(frozen=True)
class HookCatalog:
    rules: tuple[HookRule, ...] = ()
    disabled_count: int = 0
    source_counts: dict[str, int] = field(default_factory=dict)

    @property
    def effective_count(self) -> int:
        return sum(1 for rule in self.rules if rule.enabled)


@dataclass(frozen=True)
class HookActionResult:
    status: HookStatus
    message: str = ""
    deny_reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookDispatchResult:
    denied: bool = False
    denied_by: str = ""
    deny_reason: str = ""
    records: tuple[HookActionResult, ...] = ()


@dataclass(frozen=True)
class HookPromptBlock:
    rule_id: str
    scope: PromptScope
    content: str
    source_event: HookEventName

    def render(self) -> str:
        return (
            f'<huicode_instruction type="hook" rule="{self.rule_id}" '
            f'event="{self.source_event}" scope="{self.scope}">\n'
            f"{self.content.strip()}\n"
            "</huicode_instruction>"
        )


@dataclass
class HookRuntimeState:
    turn_id: str = ""
    next_request_blocks: list[HookPromptBlock] = field(default_factory=list)
    turn_blocks: list[HookPromptBlock] = field(default_factory=list)

    def clear_turn(self) -> None:
        self.turn_id = ""
        self.next_request_blocks.clear()
        self.turn_blocks.clear()


@dataclass(frozen=True)
class HookStatusSummary:
    effective: int = 0
    disabled: int = 0
    pending: int = 0
    failed: int = 0
    denied: int = 0
    write_failures: int = 0
    log_path: str = ""
    source_counts: dict[str, int] = field(default_factory=dict)
