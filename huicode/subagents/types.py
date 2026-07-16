from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

from huicode.agent_events import AgentMode
from huicode.permissions import PermissionContext
from huicode.prompts import PromptBundle
from huicode.providers.base import ConversationMessage


AgentSource = Literal["plugin", "builtin", "user", "project"]
AgentKind = Literal["defined", "fork"]
AgentIsolation = Literal["shared", "worktree"]
TaskStatus = Literal[
    "queued",
    "running_foreground",
    "running_background",
    "completed",
    "failed",
    "cancelled",
]


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    allowed_tools: tuple[str, ...]
    denied_tools: tuple[str, ...]
    model: Literal["inherit", "haiku", "sonnet", "opus"]
    max_iterations: int
    permission_mode: Literal["strict", "default", "permissive"]
    instructions: str
    source: AgentSource
    source_path: Path
    isolation: AgentIsolation = "shared"


@dataclass(frozen=True)
class AgentWarning:
    path: Path
    code: str
    message: str

    def display(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True)
class AgentCatalogSnapshot:
    definitions: Mapping[str, AgentDefinition] = field(
        default_factory=lambda: MappingProxyType({})
    )
    overridden_count: int = 0
    skipped_count: int = 0
    warnings: tuple[AgentWarning, ...] = ()
    source_counts: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def create(
        cls,
        definitions: dict[str, AgentDefinition],
        *,
        overridden_count: int = 0,
        skipped_count: int = 0,
        warnings: tuple[AgentWarning, ...] = (),
    ) -> "AgentCatalogSnapshot":
        counts: dict[str, int] = {}
        for definition in definitions.values():
            counts[definition.source] = counts.get(definition.source, 0) + 1
        return cls(
            definitions=MappingProxyType(dict(definitions)),
            overridden_count=overridden_count,
            skipped_count=skipped_count,
            warnings=warnings,
            source_counts=MappingProxyType(counts),
        )


@dataclass(frozen=True)
class PermissionSnapshot:
    context: PermissionContext


@dataclass(frozen=True)
class ParentAgentSnapshot:
    messages: tuple[ConversationMessage, ...]
    prompt: PromptBundle
    visible_tools: tuple[str, ...]
    mode: AgentMode
    permissions: PermissionSnapshot
    project_instructions: str = ""


@dataclass(frozen=True)
class SubagentLaunchRequest:
    type: AgentKind
    task: str
    role: str | None
    background: bool
    parent: ParentAgentSnapshot
    origin: Literal["tool", "hook"] = "tool"


@dataclass(frozen=True)
class SubagentResult:
    task_id: str
    status: TaskStatus
    summary: str
    stop_reason: str = ""
    iterations: int = 0
    usage: dict[str, object] = field(default_factory=dict)
    error: str = ""
    duration_seconds: float = 0.0
    worktree_path: str = ""
    worktree_branch: str = ""
    worktree_state: str = ""
    worktree_reason: str = ""


@dataclass
class SubagentTask:
    id: str
    type: AgentKind
    role: str | None
    task: str
    status: TaskStatus = "queued"
    background: bool = False
    created_at: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None
    iterations: int = 0
    stop_reason: str = ""
    usage: dict[str, object] = field(default_factory=dict)
    summary: str = ""
    error: str = ""
    worktree_path: str = ""
    worktree_branch: str = ""
    worktree_state: str = ""
    worktree_reason: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    background_event: threading.Event = field(default_factory=threading.Event, repr=False)
    done_event: threading.Event = field(default_factory=threading.Event, repr=False)


@dataclass(frozen=True)
class SubagentTaskView:
    id: str
    type: AgentKind
    role: str | None
    task: str
    status: TaskStatus
    background: bool
    created_at: float
    started_at: float | None
    completed_at: float | None
    iterations: int
    stop_reason: str
    usage: dict[str, object]
    summary: str
    error: str
    worktree_path: str = ""
    worktree_branch: str = ""
    worktree_state: str = ""
    worktree_reason: str = ""


@dataclass(frozen=True)
class SubagentNotification:
    task_id: str
    type: AgentKind
    role: str | None
    status: TaskStatus
    duration_seconds: float
    summary: str
    worktree_path: str = ""
    worktree_branch: str = ""
    worktree_state: str = ""


@dataclass(frozen=True)
class ResultLease:
    id: str
    results: tuple[SubagentResult, ...]


@dataclass(frozen=True)
class ForegroundWaitResult:
    reason: Literal["completed", "timeout", "manual"]
    task: SubagentTaskView
