from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


MemoryScope = Literal["user", "project"]
MemoryCategory = Literal["preference", "correction", "project_knowledge", "reference"]


@dataclass
class MemoryRuntimeState:
    session_id: str = ""
    instructions_text: str = ""
    memory_index_text: str = ""
    warnings: list[str] = field(default_factory=list)
    last_error: str = ""
    pending_updates: int = 0
    last_update_at: str = ""

    def reset_prompt_memory(self) -> None:
        self.instructions_text = ""
        self.memory_index_text = ""
        self.warnings.clear()
        self.last_error = ""


@dataclass(frozen=True)
class InstructionLoadResult:
    text: str
    loaded_paths: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    path: Path
    title: str
    message_count: int
    updated_at: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecoveredSession:
    session_id: str
    messages: list
    warnings: tuple[str, ...] = ()
    truncated: bool = False
    skipped_bad_lines: int = 0
    time_gap_inserted: bool = False


@dataclass(frozen=True)
class MemoryNote:
    note_id: str
    scope: MemoryScope
    category: MemoryCategory
    title: str
    summary: str
    body: str
    source_session: str = ""
    created_at: str = ""
    updated_at: str = ""
    path: Path | None = None


@dataclass(frozen=True)
class MemoryIndexResult:
    path: Path
    lines: int
    bytes: int
    note_count: int
    clipped: bool = False


@dataclass(frozen=True)
class MemoryUpdateReport:
    ok: bool
    message: str
    created: int = 0
    updated: int = 0
    deleted: int = 0
    noop: bool = False


@dataclass(frozen=True)
class ResumeReport:
    ok: bool
    session_id: str
    message: str
    restored_messages: int = 0
    skipped_bad_lines: int = 0
    truncated: bool = False
    time_gap_inserted: bool = False
    compacted: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryStatus:
    enabled: bool
    session_id: str
    project_notes: int = 0
    user_notes: int = 0
    index_lines: int = 0
    index_bytes: int = 0
    pending_updates: int = 0
    last_update_at: str = ""
    last_error: str = ""
    warnings: tuple[str, ...] = ()
