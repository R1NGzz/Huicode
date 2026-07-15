from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal


CompressionKind = Literal["lightweight", "summary", "skip", "failure", "fuse"]


@dataclass(frozen=True)
class ContextCompressionReport:
    kind: CompressionKind
    spilled_count: int = 0
    summary_created: bool = False
    tokens_before: int = 0
    tokens_after: int = 0
    tokens_freed: int = 0
    message: str = ""
    paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "spilled_count": self.spilled_count,
            "summary_created": self.summary_created,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_freed": self.tokens_freed,
            "message": self.message,
            "paths": list(self.paths),
        }


@dataclass(frozen=True)
class ContextPreparation:
    request_tokens: int = 0
    request_chars: int = 0
    history_changed: bool = False
    reports: tuple[ContextCompressionReport, ...] = ()


@dataclass(frozen=True)
class ContextLifecycleCallbacks:
    before_compact: Callable[[dict[str, object]], None] | None = None
    after_compact: Callable[[ContextCompressionReport], None] | None = None


@dataclass(frozen=True)
class SummaryResult:
    ok: bool
    summary_text: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class SpillRecord:
    path: str
    original_chars: int
    compact_chars: int
    tokens_freed: int
    preview: str
    reason: str


@dataclass(frozen=True)
class CompactToolResult:
    report: ContextCompressionReport | None = None
    spilled: SpillRecord | None = None


@dataclass(frozen=True)
class SummaryBuildResult:
    summary_message: str
    boundary_message: str
