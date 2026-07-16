from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class WorktreeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WorktreeIdentity:
    repository_id: str
    task_id: str
    logical_name: str
    base_commit: str
    branch: str
    path: Path
    created_at: float
    terminal_status: str = ""
    retained_reason: str = ""


@dataclass(frozen=True)
class WorktreeHandle:
    identity: WorktreeIdentity
    recovered: bool = False

    @property
    def path(self) -> Path:
        return self.identity.path

    @property
    def branch(self) -> str:
        return self.identity.branch


@dataclass(frozen=True)
class WorktreeDisposition:
    state: Literal["removed", "retained", "skipped"]
    reason: str
    dirty: bool = False
    unpushed: bool = False


@dataclass(frozen=True)
class WorktreeCleanupRecord:
    path: Path
    state: Literal["removed", "retained", "skipped", "error"]
    reason: str
