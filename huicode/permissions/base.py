from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from huicode.providers.base import ToolCall


PermissionMode = Literal["strict", "default", "permissive"]
RuleAction = Literal["allow", "deny"]
ConfirmationAction = Literal["deny", "once", "session", "always"]


class PermissionConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PermissionRule:
    tool: str
    pattern: str
    action: RuleAction
    source: str = "unknown"
    raw: str = ""


@dataclass(frozen=True)
class PermissionConfig:
    mode: PermissionMode = "default"
    rules: tuple[PermissionRule, ...] = ()


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str
    source: str
    requires_confirmation: bool = False
    matched_rule: str | None = None
    risk: str = "low"


@dataclass(frozen=True)
class PermissionRequest:
    call: ToolCall
    target: str
    risk: str
    reason: str


@dataclass(frozen=True)
class PermissionConfirmation:
    action: ConfirmationAction


class PermissionConfirmer(Protocol):
    def confirm(self, request: PermissionRequest) -> PermissionConfirmation:
        ...


@dataclass
class PermissionContext:
    workspace: Path
    mode: PermissionMode = "default"
    rules: list[PermissionRule] = field(default_factory=list)
    session_rules: list[PermissionRule] = field(default_factory=list)
    confirmer: PermissionConfirmer | None = None
    persistent_path: Path | None = None

