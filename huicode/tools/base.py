from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from huicode.providers.base import ToolSpec


@dataclass(frozen=True)
class ToolContext:
    workspace: Path
    timeout_seconds: int = 10
    max_output_chars: int = 6000


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
    root = workspace.resolve()
    target = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"路径超出工作目录: {path}")
    return target
