"""Run 级别的执行外壳：把"一段工作"放进预算与取消的边界里，并保证它**一定有终态**。

一个 Run 最糟糕的状态不是失败，而是**永远停在运行中**：前端一直转圈、租约永远不释放、
用户不知道能不能重试。所以这里的核心不是"限制得多严"，而是无论内部抛什么异常、
无论取消从哪个方向来，`run_under_budget` 都会返回一个明确的 `RunResult`。

```text
run_under_budget()
   ├─ BudgetTracker.start()                记账开始
   ├─ 看门狗任务：到点 token.cancel("timeout")
   ├─ work(token, tracker)                 真正的工作（T16 才接 Agent Loop）
   └─ 五种出口 → RunResult(status, error_code, usage)
```

**取消是协作式的，所以"报完成"要谨慎。** 工作可能在取消生效的同时正常返回。此时
按 `cancelled` 报——代价是用户偶尔看到一次"其实已经做完"的取消，收益是不会出现
"用户以为任务完成了、实际只做了一半"这种会让用户不再检查的终态。两种误报的代价
不对称，选小的那个。

**外部把 asyncio 任务取消掉（`CancelledError`）不在这里吞。** 那不是 Run 的取消，
是调用方（例如请求被中断、进程在关闭）在收回这个协程。吞掉它会让 asyncio 的
结构化并发失效，所以原样抛出。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from huicode.server.runtime.cancellation import CancelToken, RunCancelled
from huicode.server.runtime.errors import RUN_CANCELLED, RUN_ERROR, RUN_TIMEOUT
from huicode.server.runtime.limits import BudgetExceeded, BudgetTracker, BudgetUsage, ResourceBudget
from huicode.server.runtime.scrubbing import get_scrubber

if TYPE_CHECKING:  # 只为类型标注，避免运行时把事件层拖进来
    from huicode.server.events.types import RuntimeEvent

RunStatus = Literal["completed", "cancelled", "failed"]

#: 取消之后等工作者自己收尾的时间。协作式取消靠对方检查令牌，
#: 对方如果卡在不可中断的调用里就永远不会检查——这段等待就是那个下限。
DEFAULT_CANCELLATION_GRACE_SECONDS = 5.0

#: 工作者没有在宽限期内自己退出，被强制停下的标记。
CANCELLATION_WIND_DOWN_TIMEOUT = "cancellation_wind_down_timeout"

TERMINAL_EVENT_TYPE: dict[str, str] = {
    "completed": "run_completed",
    "cancelled": "run_cancelled",
    "failed": "run_failed",
}


@dataclass(frozen=True)
class AgentRunRequest:
    """一次 Run 的输入。**预算与工作目录都在这里**，不从请求参数里读——
    C49 要求安全策略不能只依赖前端传入的参数。"""

    session_id: UUID
    workspace: Path
    user_text: str
    budget: ResourceBudget
    run_id: UUID | None = None


@dataclass(frozen=True)
class RunResult:
    """Run 的终态。`terminal_event_type` 是它与事件层的唯一约定。"""

    status: RunStatus
    usage: BudgetUsage
    error_code: str | None = None
    message: str = ""
    detail: str = ""
    output: Any = None

    @property
    def terminal_event_type(self) -> str:
        return TERMINAL_EVENT_TYPE[self.status]

    def to_event_payload(self) -> dict:
        """终态事件的载荷。`run_cancelled` 不带 error_code——用户取消不是错误。"""
        payload: dict = {"usage": self.usage.to_dict()}
        if self.error_code is not None and self.status != "cancelled":
            payload["error_code"] = self.error_code
        if self.message:
            payload["message"] = self.message
        if self.detail:
            payload["detail"] = self.detail
        return payload


@runtime_checkable
class AgentRunExecutor(Protocol):
    """事件层与 Worker 依赖的接口（plan.md 的 AgentRunExecutor）。

    真正的实现是 T16 的 `agent_executor.py`；T9 只提供它要用到的预算、取消与终态。
    """

    async def execute(
        self,
        request: AgentRunRequest,
        emit: "Callable[[RuntimeEvent], Awaitable[None]]",
        approval_broker: Any,
        cancel_token: CancelToken,
    ) -> RunResult: ...


async def run_under_budget(
    work: Callable[[CancelToken, BudgetTracker], Awaitable[Any]],
    *,
    budget: ResourceBudget,
    token: CancelToken | None = None,
    clock: Callable[[], float] = time.monotonic,
    cancellation_grace_seconds: float = DEFAULT_CANCELLATION_GRACE_SECONDS,
) -> RunResult:
    """在预算与取消边界内执行 `work`，返回终态。

    `work` 拿到的是**子令牌**：看门狗超时、或外部取消父令牌，都会传到它手上；
    它自己取消子令牌不会影响父令牌。
    """
    parent = token if token is not None else CancelToken()
    run_token = parent.derive()
    tracker = BudgetTracker(budget, clock=clock)
    tracker.start()

    # 父令牌已经取消时**一个字节的工作都不该开始**。派生出的子令牌虽然已经是取消
    # 状态，但把 work 交给事件循环仍然会先跑起来——它要等到第一个检查点才会发现。
    if run_token.is_cancelled():
        return _from_cancellation(run_token, tracker, "already_cancelled")

    work_task = asyncio.ensure_future(work(run_token, tracker))
    cancel_waiter = asyncio.ensure_future(run_token.wait())
    watchdog = asyncio.ensure_future(_watch_deadline(tracker, run_token))
    detail = ""
    try:
        await asyncio.wait({work_task, cancel_waiter}, return_when=asyncio.FIRST_COMPLETED)

        forced_stop = False
        if not work_task.done():
            detail, forced_stop = await _wind_down(work_task, cancellation_grace_seconds)

        if work_task.cancelled():
            if not forced_stop:
                # 工作者被**外部**直接 cancel 掉了，而不是通过令牌退出。
                # 原样抛出，别把结构化并发吃掉。我们自己强杀的那种不算。
                raise asyncio.CancelledError()
            # 强杀过的任务取 exception() 会再抛 CancelledError，直接按取消收尾。
            return _from_cancellation(run_token, tracker, detail)

        error = work_task.exception()
        if error is not None:
            return _from_exception(error, tracker, detail)
        if run_token.is_cancelled():
            return _from_cancellation(run_token, tracker, detail)
        return RunResult(
            status="completed",
            usage=tracker.snapshot(),
            output=work_task.result(),
            detail=detail,
        )
    finally:
        for task in (watchdog, cancel_waiter):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


async def _watch_deadline(tracker: BudgetTracker, token: CancelToken) -> None:
    """到点就把令牌取消，原因是 `timeout`。

    走令牌而不是直接 cancel 工作协程：直接 cancel 会在任意 await 点插进去，
    工作者来不及记录"我是在哪一步被停的"。走令牌它就有机会在检查点上收尾。
    """
    remaining = tracker.remaining_run_seconds()
    if remaining > 0:
        await asyncio.sleep(remaining)
    if not token.is_cancelled():
        token.cancel("timeout", f"运行超过 {tracker.budget.max_run_seconds} 秒上限")


async def _wind_down(work_task: "asyncio.Task[Any]", grace_seconds: float) -> tuple[str, bool]:
    """已请求取消，等工作自己退出。超时则强杀。

    返回 `(detail, 是否是强杀)`。这个标记是必需的：强杀也会让 `work_task.cancelled()`
    为真，不区分的话，我们自己造成的取消会被当成外部的 CancelledError 抛出去。
    """
    try:
        await asyncio.wait_for(asyncio.shield(work_task), grace_seconds)
    except (asyncio.TimeoutError, TimeoutError):
        work_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await work_task
        return CANCELLATION_WIND_DOWN_TIMEOUT, True
    except BaseException:  # noqa: BLE001 —— 异常已由 work_task 保存，这里只负责等待
        pass
    return "", False


def _from_exception(error: BaseException, tracker: BudgetTracker, detail: str) -> RunResult:
    if isinstance(error, BudgetExceeded):
        return RunResult(
            status="failed",
            usage=tracker.snapshot(),
            error_code=error.code,
            message=error.message,
            detail=detail,
        )
    if isinstance(error, RunCancelled):
        # 超时也走这条：令牌被看门狗取消后，工作者在检查点上抛的就是 RunCancelled。
        if error.code == RUN_TIMEOUT:
            return RunResult(
                status="failed",
                usage=tracker.snapshot(),
                error_code=RUN_TIMEOUT,
                message=error.message,
                detail=detail,
            )
        return RunResult(
            status="cancelled",
            usage=tracker.snapshot(),
            error_code=RUN_CANCELLED,
            message=error.message,
            detail=detail,
        )
    return RunResult(
        status="failed",
        usage=tracker.snapshot(),
        error_code=RUN_ERROR,
        # 异常原文里可能有密钥（连接串、回显的 Authorization），过一遍脱敏再进终态事件。
        message=get_scrubber().scrub_exception(error),
        detail=detail,
    )


def _from_cancellation(token: CancelToken, tracker: BudgetTracker, detail: str) -> RunResult:
    if token.reason == "timeout":
        return RunResult(
            status="failed",
            usage=tracker.snapshot(),
            error_code=RUN_TIMEOUT,
            message="运行超过时限，已停止",
            detail=detail,
        )
    return RunResult(
        status="cancelled",
        usage=tracker.snapshot(),
        error_code=RUN_CANCELLED,
        message="运行已被取消",
        detail=detail,
    )
