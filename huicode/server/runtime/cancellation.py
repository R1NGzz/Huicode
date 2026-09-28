"""取消令牌：把"停止"从一个布尔量变成一个可传播、可等待的状态。

**为什么不用 `asyncio.Task.cancel()`。** Task 取消只在 await 点上生效，而 Agent 的
大部分工作是**同步阻塞**的：工具 `run()` 是同步函数（`huicode/tools/*.py`），
Shell 是 `subprocess.run`。这些代码块里没有 await 点，Task.cancel() 传不进去。
所以取消必须是**协作式**的：一层层往下传一个令牌，由各执行边界（模型请求前、
工具调用前后、每轮循环）自己检查。

**传播是单向的。** 父令牌取消必然导致子令牌取消（Run 停了，它的工具不能继续跑）；
反过来不成立——单个工具超时不该把整个 Run 干掉，Run 还有别的路可走。这个不对称
是这里唯一容易写反的地方，测试里两个方向都有断言。

**第一个原因胜出。** 用户取消和运行超时可能几乎同时发生，后到的原因不该覆盖先到的——
先到的那个才是真正解释这次停止的原因。
"""

from __future__ import annotations

import asyncio
import threading
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol, runtime_checkable

from huicode.server.runtime.errors import RUN_CANCELLED, RUN_TIMEOUT, RuntimeFailure

CancellationReason = Literal["user", "timeout", "budget", "shutdown", "unknown"]

REASONS: frozenset[str] = frozenset({"user", "timeout", "budget", "shutdown", "unknown"})


class RunCancelled(RuntimeFailure):
    """令牌已取消时在检查点上抛出。

    错误码按取消原因决定：**超时不是用户取消**，两者在运维上的含义相反
    （一个是有人在操作，一个是我们的限制在生效），混成一个码就没法分别统计。
    """

    def __init__(self, reason: str, detail: str = ""):
        code = RUN_TIMEOUT if reason == "timeout" else RUN_CANCELLED
        message = _MESSAGES.get(reason, _MESSAGES["unknown"])
        super().__init__(message, details={"reason": reason})
        self.code = code
        self.reason = reason
        self.detail = detail


_MESSAGES = {
    "user": "运行已被取消",
    "timeout": "运行超过时限，已停止",
    "budget": "运行预算已耗尽，已停止",
    "shutdown": "服务正在关闭，运行已停止",
    "unknown": "运行已停止",
}


@dataclass(frozen=True)
class CancellationState:
    reason: str
    detail: str
    requested_at: datetime


@runtime_checkable
class CancellationToken(Protocol):
    """执行边界只依赖这个协议，不依赖具体实现。

    同步的 `is_cancelled` 是必须的：同步工具代码里没法 await。
    """

    def is_cancelled(self) -> bool: ...

    async def wait(self) -> None: ...

    @property
    def reason(self) -> str | None: ...


class CancelToken:
    """可取消、可等待、可派生的令牌。线程安全。

    `cancel()` 可以被任意线程调用（例如超时看门狗、HTTP 请求处理线程），
    `wait()` 只在事件循环里调用。
    """

    __slots__ = ("_children", "_lock", "_state", "_waiters", "__weakref__")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: CancellationState | None = None
        self._waiters: list[asyncio.Future[None]] = []
        # 弱引用：父令牌不该因为曾经派生过子令牌就把它们一直留在内存里。
        self._children: weakref.WeakSet[CancelToken] = weakref.WeakSet()

    # ── 查询 ────────────────────────────────────────────────────────────

    def is_cancelled(self) -> bool:
        return self._state is not None

    @property
    def reason(self) -> str | None:
        state = self._state
        return None if state is None else state.reason

    @property
    def state(self) -> CancellationState | None:
        return self._state

    # ── 取消 ────────────────────────────────────────────────────────────

    def cancel(self, reason: str = "user", detail: str = "") -> bool:
        """请求取消。返回是否是**本次**调用让它变成已取消的。

        幂等：重复调用不会改变已经记录的原因。
        """
        if reason not in REASONS:
            reason = "unknown"
        with self._lock:
            if self._state is not None:
                return False
            self._state = CancellationState(
                reason=reason, detail=detail, requested_at=datetime.now(timezone.utc)
            )
            waiters = list(self._waiters)
            children = list(self._children)

        for future in waiters:
            # 取消可能来自另一个线程，唤醒必须回到 future 自己的循环上。
            try:
                future.get_loop().call_soon_threadsafe(_resolve, future)
            except RuntimeError:
                # 循环已经关了：工作者不会再等，忽略即可。
                pass
        for child in children:
            child.cancel(reason, detail)
        return True

    def derive(self) -> "CancelToken":
        """派生一个子令牌：父取消则子取消，子取消不影响父。

        已经取消的父令牌派生出**已取消**的子令牌——否则新建的工具令牌会在
        Run 已经停止之后照常执行。
        """
        child = CancelToken()
        state = self._state
        if state is not None:
            child.cancel(state.reason, state.detail)
            return child
        with self._lock:
            # 与 cancel() 竞争时以锁内的状态为准，避免"父已取消但子还活着"。
            state = self._state
            if state is None:
                self._children.add(child)
            else:
                child.cancel(state.reason, state.detail)
        return child

    # ── 等待 ────────────────────────────────────────────────────────────

    async def wait(self) -> None:
        """等到取消为止。已取消时立即返回。"""
        with self._lock:
            if self._state is not None:
                return
            future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._waiters.append(future)
        try:
            await future
        finally:
            with self._lock:
                if future in self._waiters:
                    self._waiters.remove(future)

    def raise_if_cancelled(self) -> None:
        """执行边界上的检查点。取消时抛 `RunCancelled`。"""
        state = self._state
        if state is not None:
            raise RunCancelled(state.reason, state.detail)


def _resolve(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)
