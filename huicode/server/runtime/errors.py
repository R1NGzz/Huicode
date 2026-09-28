"""运行时失败的**统一错误码**。

取消、超时和预算耗尽都会让一次 Run 非正常结束，但它们的成因完全不同，事后排查
和用户提示也完全不同：

- 用户点了取消 → 不是故障，不该报警；
- 我们自己的时限到了 → 是**我们知道**的失败，比"未知异常"好处理；
- 工具自己超时 → 与整个 Run 超时不是一回事，Run 还可以继续。

如果把这三类都塞进一个 `failed` 里，运维侧就只能看到"失败率上升"而分不出
"有人在取消"和"服务在超时"。所以这里把错误码集中定义一次，`limits.py` 和
`cancellation.py` 都从这里取——**错误码分散在各模块里迟早会出现同一种失败两种写法**。

这些码最终进 `run_failed` / `run_cancelled` 事件的 `error_code` 字段。注意
``RUN_CANCELLED`` 与事件类型同名是**有意**的：用户取消时终态事件是 `run_cancelled`，
它不携带"错误"，这个码只用于日志与审计对齐。
"""

from __future__ import annotations

from typing import Any

# ── 取消 ────────────────────────────────────────────────────────────────
RUN_CANCELLED = "run_cancelled"

# ── 超时 ────────────────────────────────────────────────────────────────
RUN_TIMEOUT = "run_timeout"
TOOL_TIMEOUT = "tool_timeout"
SHELL_TIMEOUT = "shell_timeout"

# ── 预算耗尽 ────────────────────────────────────────────────────────────
ITERATION_BUDGET_EXCEEDED = "iteration_budget_exceeded"
TOOL_CALL_BUDGET_EXCEEDED = "tool_call_budget_exceeded"
OUTPUT_BUDGET_EXCEEDED = "output_budget_exceeded"

# ── 兜底 ────────────────────────────────────────────────────────────────
#: 非上述分类的异常。有兜底码才能保证 Run **一定**有终态，
#: 不会因为一个意料外的异常就永远停在 running。
RUN_ERROR = "run_error"

ALL_ERROR_CODES: frozenset[str] = frozenset({
    RUN_CANCELLED,
    RUN_TIMEOUT,
    TOOL_TIMEOUT,
    SHELL_TIMEOUT,
    ITERATION_BUDGET_EXCEEDED,
    TOOL_CALL_BUDGET_EXCEEDED,
    OUTPUT_BUDGET_EXCEEDED,
    RUN_ERROR,
})

#: 这些码表示"Run 被限定条件的边界挡下"，而不是"代码出错了"。
#: 区分出来是为了让告警只盯真正的异常。
LIMIT_ERROR_CODES: frozenset[str] = frozenset({
    RUN_TIMEOUT,
    TOOL_TIMEOUT,
    SHELL_TIMEOUT,
    ITERATION_BUDGET_EXCEEDED,
    TOOL_CALL_BUDGET_EXCEEDED,
    OUTPUT_BUDGET_EXCEEDED,
})


class RuntimeFailure(Exception):
    """运行时受控失败。带机器可读的 ``code``，消息面向人。

    消息**不带载荷原文**：它会进事件、审计和日志（C58）。
    """

    code: str = RUN_ERROR

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
