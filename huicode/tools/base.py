from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from huicode.providers.base import ToolSpec

if TYPE_CHECKING:
    from huicode.permissions import PermissionContext


@dataclass(frozen=True)
class ToolContext:
    workspace: Path
    timeout_seconds: int = 10
    max_output_chars: int = 6000
    permissions: "PermissionContext | None" = None
    read_cache: "FileReadCache | None" = None


class FileReadCache:
    def __init__(self) -> None:
        self._values: dict[tuple[str, int, int], str] = {}
        self._lock = threading.Lock()

    def get(self, path: Path) -> str | None:
        stat = path.stat()
        key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        with self._lock:
            return self._values.get(key)

    def put(self, path: Path, content: str) -> None:
        stat = path.stat()
        key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        with self._lock:
            for stale in [item for item in self._values if item[0] == key[0] and item != key]:
                self._values.pop(stale, None)
            self._values[key] = content

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    summary: str = ""

    @classmethod
    def success(cls, data: dict[str, Any], summary: str) -> "ToolResult":
        return cls(ok=True, data=data, summary=summary)

    @classmethod
    def failure(
        cls,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        summary: str | None = None,
    ) -> "ToolResult":
        error = ToolError(code=code, message=message, details=details or {})
        return cls(ok=False, error=error, summary=summary or message)

    def to_model_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error.to_dict() if self.error else None,
            "summary": self.summary,
        }


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]
    side_effect: bool

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        ...

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)


def safe_join_workspace(workspace: Path, path: str | Path) -> Path:
    from huicode.permissions.sandbox import resolve_workspace_path

    return resolve_workspace_path(workspace, path)
