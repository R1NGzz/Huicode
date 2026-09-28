"""资源预算与检查点。

计划里的 `ResourceBudget` 有七项，这里只实现**当前有执行者**的六项。第七项
`max_child_processes` 要等 T12 有了子进程树终止能力才有意义——**先加一个没人执行的
配置项，比不加更糟**：它会让配置文件看起来已经限制了进程数，实际不限制。

检查点分布在三个位置（T16 把它们插进 Agent Loop 的调用点）：

```text
每轮循环开头      before_iteration()      迭代计数 + 运行时限
模型请求之前      before_model_request()  运行时限
工具调用之前      before_tool_call()      工具调用计数 + 运行时限 + 本次工具时限
工具调用之后      after_tool_call()       记录超时（**不抛异常**，见下）
输出产生时        record_output(n)        累计输出字节
```

**为什么工具超时只在事前拦、事后只记录。** 工具已经跑完了，它的副作用（改了文件、
发了请求）已经发生；此时再抛超时异常只是丢掉一个已经产生的结果，并不能撤销副作用。
所以事后把它记成 overrun 供观测，真正的截断交给 T12 在进程层面杀子进程树。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from huicode.server.runtime.errors import (
    ITERATION_BUDGET_EXCEEDED,
    OUTPUT_BUDGET_EXCEEDED,
    RUN_TIMEOUT,
    TOOL_CALL_BUDGET_EXCEEDED,
    RuntimeFailure,
)

DEFAULT_TRUNCATION_MARKER = "\n...[truncated]"


class BudgetExceeded(RuntimeFailure):
    """某项预算耗尽。`code` 说明是哪一项。"""

    def __init__(self, code: str, message: str, *, details: dict | None = None):
        super().__init__(message, details=details)
        self.code = code


@dataclass(frozen=True)
class ToolAllowance:
    """一次工具调用被允许使用的时间。"""

    seconds: float
    started_at: float


@dataclass(frozen=True)
class BudgetUsage:
    """运行结束时的用量快照，进 RunResult 与 usage 事件。"""

    iterations: int
    tool_calls: int
    output_bytes: int
    elapsed_seconds: float
    tool_overruns: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "output_bytes": self.output_bytes,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "tool_overruns": list(self.tool_overruns),
        }


@dataclass(frozen=True)
class ResourceBudget:
    """一次 Run 的资源上限。字段与 `RuntimeLimits` 同名，便于一一对照。"""

    max_run_seconds: int = 1800
    max_tool_seconds: int = 120
    max_shell_seconds: int = 60
    max_iterations: int = 50
    max_tool_calls: int = 100
    max_output_bytes: int = 1048576

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name}: 必须是正整数")
        # 与 load_server_settings 的校验保持一致：程序里直接构造也要挡住。
        if not self.max_shell_seconds <= self.max_tool_seconds <= self.max_run_seconds:
            raise ValueError("时限应满足 max_shell_seconds ≤ max_tool_seconds ≤ max_run_seconds")

    @classmethod
    def from_limits(cls, limits) -> "ResourceBudget":
        """从 `RuntimeLimits` 构造。两者字段同名，避免手工搬运时漏项。"""
        return cls(**{name: getattr(limits, name) for name in cls.__dataclass_fields__})


class BudgetTracker:
    """预算的账本与检查点。

    `clock` 可注入，测试用它把"等了 1800 秒"变成一次函数调用——不然时限相关的
    测试就只能靠真的 sleep，那种测试既慢又不可靠。
    """

    def __init__(
        self,
        budget: ResourceBudget,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._budget = budget
        self._clock = clock
        self._started_at: float | None = None
        self._iterations = 0
        self._tool_calls = 0
        self._output_bytes = 0
        self._tool_overruns: list[str] = []

    @property
    def budget(self) -> ResourceBudget:
        return self._budget

    # ── 生命周期 ────────────────────────────────────────────────────────

    def start(self) -> None:
        self._started_at = self._clock()

    @property
    def started_at(self) -> float | None:
        return self._started_at

    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, self._clock() - self._started_at)

    def remaining_run_seconds(self) -> float:
        """还剩多少秒。已耗尽返回 0.0，**不返回负数**——负的剩余时间会让
        `min(shell, remaining)` 这类计算悄悄取到没有意义的值。"""
        if self._started_at is None:
            return float(self._budget.max_run_seconds)
        return max(0.0, self._budget.max_run_seconds - self.elapsed_seconds())

    def run_deadline(self) -> float:
        """运行截止的绝对时刻（同一时钟）。给看门狗用。"""
        if self._started_at is None:
            raise RuntimeError("BudgetTracker.start() 尚未调用")
        return self._started_at + self._budget.max_run_seconds

    # ── 检查点 ──────────────────────────────────────────────────────────

    def check_run_deadline(self) -> None:
        if self._started_at is None:
            return
        if self.elapsed_seconds() >= self._budget.max_run_seconds:
            raise BudgetExceeded(
                RUN_TIMEOUT,
                f"运行超过 {self._budget.max_run_seconds} 秒上限",
                details={
                    "limit_seconds": self._budget.max_run_seconds,
                    "elapsed_seconds": round(self.elapsed_seconds(), 3),
                },
            )

    def before_iteration(self) -> int:
        """每轮 Agent Loop 开头。返回从 1 开始的迭代序号。"""
        self.check_run_deadline()
        self._iterations += 1
        if self._iterations > self._budget.max_iterations:
            raise BudgetExceeded(
                ITERATION_BUDGET_EXCEEDED,
                f"已达到最大迭代次数 {self._budget.max_iterations}",
                details={
                    "limit": self._budget.max_iterations,
                    "used": self._iterations,
                },
            )
        return self._iterations

    def before_model_request(self) -> None:
        """模型请求之前。单独一个方法而不是复用 check_run_deadline，
        是因为将来要加"单次请求时限"时，只有这一处需要改。"""
        self.check_run_deadline()

    def before_tool_call(self, tool_name: str) -> ToolAllowance:
        """工具调用之前。返回本次调用被允许的时间。"""
        self.check_run_deadline()
        self._tool_calls += 1
        if self._tool_calls > self._budget.max_tool_calls:
            raise BudgetExceeded(
                TOOL_CALL_BUDGET_EXCEEDED,
                f"已达到最大工具调用次数 {self._budget.max_tool_calls}",
                details={
                    "limit": self._budget.max_tool_calls,
                    "used": self._tool_calls,
                    "tool": tool_name,
                },
            )
        # 剩余运行时间是更紧的上限：Run 只剩 3 秒时，给工具 120 秒没有意义。
        seconds = min(float(self._budget.max_tool_seconds), self.remaining_run_seconds())
        return ToolAllowance(seconds=seconds, started_at=self._clock())

    def after_tool_call(self, allowance: ToolAllowance, tool_name: str) -> bool:
        """工具返回之后。超时**只记录**，不抛异常（见模块文档）。"""
        overran = (self._clock() - allowance.started_at) > allowance.seconds
        if overran:
            self._tool_overruns.append(tool_name)
        return overran

    def record_output(self, size: int) -> None:
        """累计输出体积。超限抛 `OUTPUT_BUDGET_EXCEEDED`。"""
        if size < 0:
            raise ValueError("size 不能为负")
        self._output_bytes += size
        if self._output_bytes > self._budget.max_output_bytes:
            raise BudgetExceeded(
                OUTPUT_BUDGET_EXCEEDED,
                f"输出超过 {self._budget.max_output_bytes} 字节上限",
                details={
                    "limit_bytes": self._budget.max_output_bytes,
                    "used_bytes": self._output_bytes,
                },
            )

    def snapshot(self) -> BudgetUsage:
        return BudgetUsage(
            iterations=self._iterations,
            tool_calls=self._tool_calls,
            output_bytes=self._output_bytes,
            elapsed_seconds=self.elapsed_seconds(),
            tool_overruns=tuple(self._tool_overruns),
        )


@dataclass(frozen=True)
class TruncatedText:
    """截断结果。保留原长度，才能把"被截了多少"记进事件与审计。"""

    text: str
    original_bytes: int
    truncated: bool

    def to_details(self) -> dict:
        return {
            "original_bytes": self.original_bytes,
            "truncated": self.truncated,
            "kept_bytes": len(self.text.encode("utf-8")),
        }


def truncate_bytes(text: str, limit_bytes: int, *, marker: str = DEFAULT_TRUNCATION_MARKER) -> TruncatedText:
    """按**字节**截断，且不切碎多字节字符。

    按字符截断会算错：一个中文字符 3 字节，6000 字符的中文输出是 18KB。
    按字节切又要小心 UTF-8 边界——`text.encode()[:n]` 很可能把某个字符切成两半，
    解码时报错。所以先编码、切片、再用 `errors="ignore"` 解码，让不完整的那几个
    字节自然消失。

    标记本身占的字节从额度里扣，保证**返回值不超过 limit_bytes**。
    """
    if limit_bytes <= 0:
        raise ValueError("limit_bytes 必须是正数")
    encoded = text.encode("utf-8")
    if len(encoded) <= limit_bytes:
        return TruncatedText(text=text, original_bytes=len(encoded), truncated=False)

    marker_bytes = marker.encode("utf-8")
    if len(marker_bytes) >= limit_bytes:
        # 额度小到连标记都放不下：宁可返回空串，也不返回一个"看起来完整"的超长片段。
        return TruncatedText(text="", original_bytes=len(encoded), truncated=True)

    kept = encoded[: limit_bytes - len(marker_bytes)].decode("utf-8", errors="ignore")
    return TruncatedText(text=kept + marker, original_bytes=len(encoded), truncated=True)
