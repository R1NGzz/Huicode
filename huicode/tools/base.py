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
    protect_test_edits: bool = False


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


# ── 工具能力词表（checklist C49）─────────────────────────────────────────
# 放在这里而不是服务端的策略模块里，是因为**工具要声明它，而工具不能反向依赖
# 服务端**。风险推断与放行判断属于策略，在 server/runtime/capabilities.py。
#
# 只有布尔 `side_effect` 是不够的：它回答不了"写文件"和"出网"的区别，而这两者在
# 策略上完全不同（一个在工作区内，一个出了这台机器）。
READ = "read"
FILE_WRITE = "file_write"
SHELL = "shell"
NETWORK = "network"
EXTERNAL_SIDE_EFFECT = "external_side_effect"

ALL_CAPABILITIES: frozenset[str] = frozenset({
    READ, FILE_WRITE, SHELL, NETWORK, EXTERNAL_SIDE_EFFECT,
})

#: Plan Mode 下允许的能力集合：只有"只能读"的工具能过。
READ_ONLY_CAPABILITIES: frozenset[str] = frozenset({READ})


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]
    side_effect: bool
    #: 能力声明。**缺失时按高风险处理**——"没写就按只读放行"会让一个新工具在
    #: 没人注意的情况下拿到写权限，两种默认值的代价不对称。
    capabilities: frozenset[str]

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        ...

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)


def safe_join_workspace(workspace: Path, path: str | Path) -> Path:
    from huicode.permissions.sandbox import resolve_workspace_path

    return resolve_workspace_path(workspace, path)
