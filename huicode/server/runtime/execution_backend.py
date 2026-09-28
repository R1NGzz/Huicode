"""服务端视角的执行边界（checklist C52）。

执行机制本身在 `huicode/tools/execution.py`——它被 CLI 与 Web 共用，放在服务端包里
会让工具反过来依赖服务端。**这一层只加两样服务端才有的东西**：

1. **工作目录经 `WorkspacePathResolver` 解析。** CLI 直接拿工作区根目录跑；服务端
   的 cwd 可能来自调用方，所以 `..`、绝对路径、盘符、链接逃逸都要在这里挡下（C47）。
   解析放在这一层而不是核心，是因为"什么算越界"取决于工作区怎么定义，而那是服务端
   的概念。
2. **超时与输出上限被 `ResourceBudget` 收口。** 调用方可以要 600 秒，但预算说
   `max_shell_seconds=60`，那就只能跑 60 秒。**收口是取交集而不是取调用方的值**——
   这正是 C54"前端不可绕过资源预算"要的。

```text
ExecutionRequest（cwd 是相对路径）
        │  resolve_within(workspace, cwd)   ← 越界在这里被拒
        │  min(请求超时, 预算上限)          ← 调用方要不到更多
        ▼
CommandRunner.run(CommandRequest)          ← huicode/tools/execution.py
```
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from huicode.server.runtime.errors import SHELL_PATH_VIOLATION
from huicode.server.runtime.limits import ResourceBudget
from huicode.server.runtime.workspace_resolver import PathViolation, WorkspacePathResolver
from huicode.tools.execution import CommandRequest, CommandRunner, ExecutionResult

__all__ = [
    "ExecutionBackend",
    "ExecutionRequest",
    "ExecutionResult",
    "LocalExecutionBackend",
]

#: 工作区根目录的几种写法。`resolve_within` 会拒绝空路径和 `.`，而"就在根目录跑"
#: 恰恰是最常见的用法——归一在这里做，而不是让每个调用方去猜能传什么。
_ROOT_CWD = ("", ".", "./", ".\\")


@dataclass(frozen=True)
class ExecutionRequest:
    """一次命令执行。`cwd` 是**相对工作区**的路径，工作区由服务端给。"""

    execution_id: str
    command: str
    workspace: Path
    cwd: str = "."
    timeout_seconds: float = 60.0
    max_output_bytes: int = 1_048_576
    env: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class ExecutionBackend(Protocol):
    """执行边界。当前只有本地实现；容器或远程后端接在同一个接口后面。

    **预留的扩展点在这里，不在核心模块**：换后端要变的只有"命令跑在哪里"，
    而工作目录解析、预算收口、结果形状都不应该跟着变。
    """

    async def execute(self, request: ExecutionRequest, budget: ResourceBudget) -> ExecutionResult: ...

    async def cancel(self, execution_id: str) -> None: ...


class LocalExecutionBackend:
    """把命令跑在本机的服务端后端。"""

    def __init__(
        self,
        *,
        resolver: WorkspacePathResolver | None = None,
        runner: CommandRunner | None = None,
    ):
        self._resolver = resolver
        # runner 要在多次执行之间复用：它持有"正在跑的进程"表，cancel 靠它找人。
        self._runner = runner or CommandRunner()

    @property
    def runner(self) -> CommandRunner:
        return self._runner

    async def execute(self, request: ExecutionRequest, budget: ResourceBudget) -> ExecutionResult:
        """执行命令。解析与收口在事件循环之外做完，阻塞的等待丢到线程里。"""
        try:
            cwd = await asyncio.to_thread(self.resolve_cwd, request)
        except PathViolation as exc:
            return ExecutionResult(
                execution_id=request.execution_id,
                error_code=SHELL_PATH_VIOLATION,
                stderr=str(exc),
                command=request.command,
            )

        command = CommandRequest(
            execution_id=request.execution_id,
            command=request.command,
            cwd=cwd,
            timeout_seconds=request.timeout_seconds,
            max_output_bytes=request.max_output_bytes,
            env=request.env,
        )
        return await asyncio.to_thread(
            self._runner.run,
            command,
            timeout_cap=float(budget.max_shell_seconds),
            output_cap=budget.max_output_bytes,
        )

    async def cancel(self, execution_id: str) -> None:
        await asyncio.to_thread(self._runner.cancel, execution_id)

    def resolve_cwd(self, request: ExecutionRequest) -> Path:
        """把相对 cwd 解析成工作区内的绝对目录。越界抛 `PathViolation`。"""
        root = Path(request.workspace).resolve(strict=True)
        if request.cwd in _ROOT_CWD:
            return root
        resolver = self._resolver or WorkspacePathResolver(root)
        cwd = resolver.resolve_within(root, request.cwd)
        if not cwd.is_dir():
            raise PathViolation("工作目录不存在或不是目录")
        return cwd
