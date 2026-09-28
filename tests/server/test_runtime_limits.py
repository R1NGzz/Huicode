"""T9 取消与资源预算。

分三层：令牌本身的传播语义、预算账本的边界、以及 `run_under_budget` 的**终态**。
最后一层才是真正决定"Run 会不会永远停在运行中"的地方，所以它的每个用例都断言
`RunResult.status` 与 `error_code`，而不只是"抛没抛异常"。
"""

import asyncio
import threading
import unittest
from pathlib import Path
from uuid import uuid4

from huicode.server.config import RuntimeLimits
from huicode.server.events.types import KNOWN_EVENT_TYPES, TERMINAL_EVENT_TYPES
from huicode.server.runtime.cancellation import CancelToken, RunCancelled
from huicode.server.runtime.errors import (
    ALL_ERROR_CODES,
    ITERATION_BUDGET_EXCEEDED,
    LIMIT_ERROR_CODES,
    OUTPUT_BUDGET_EXCEEDED,
    RUN_CANCELLED,
    RUN_ERROR,
    RUN_TIMEOUT,
    TOOL_CALL_BUDGET_EXCEEDED,
)
from huicode.server.runtime.executor import (
    AgentRunRequest,
    RunResult,
    run_under_budget,
)
from huicode.server.runtime.limits import (
    BudgetExceeded,
    BudgetTracker,
    ResourceBudget,
    truncate_bytes,
)


def _budget(**overrides) -> ResourceBudget:
    """构造预算。缩短运行时限时按比例收窄工具与 Shell——
    `ResourceBudget` 会强制 shell ≤ tool ≤ run，这里不绕过它。"""
    values = dict(
        max_run_seconds=1800,
        max_tool_seconds=120,
        max_shell_seconds=60,
        max_iterations=50,
        max_tool_calls=100,
        max_output_bytes=1048576,
    )
    values.update(overrides)
    run_seconds = values["max_run_seconds"]
    values["max_tool_seconds"] = min(values["max_tool_seconds"], run_seconds)
    values["max_shell_seconds"] = min(values["max_shell_seconds"], values["max_tool_seconds"])
    return ResourceBudget(**values)


class _FakeClock:
    """可推进的单调时钟。让"等了 1800 秒"变成一次赋值。"""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CancellationTokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_token_is_not_cancelled(self):
        token = CancelToken()
        self.assertFalse(token.is_cancelled())
        self.assertIsNone(token.reason)

    async def test_cancel_is_idempotent_and_first_reason_wins(self):
        token = CancelToken()
        self.assertTrue(token.cancel("user"))
        self.assertFalse(token.cancel("timeout"), "第二次取消不该报告为生效")
        self.assertEqual(token.reason, "user", "后到的原因不能覆盖先到的")

    async def test_raise_if_cancelled_carries_the_code(self):
        token = CancelToken()
        token.cancel("user")
        with self.assertRaises(RunCancelled) as ctx:
            token.raise_if_cancelled()
        self.assertEqual(ctx.exception.code, RUN_CANCELLED)

    async def test_timeout_is_not_reported_as_a_user_cancellation(self):
        """超时与用户取消在运维上含义相反，错误码必须分开。"""
        token = CancelToken()
        token.cancel("timeout")
        with self.assertRaises(RunCancelled) as ctx:
            token.raise_if_cancelled()
        self.assertEqual(ctx.exception.code, RUN_TIMEOUT)
        self.assertNotEqual(ctx.exception.code, RUN_CANCELLED)

    async def test_unknown_reason_falls_back_instead_of_being_stored(self):
        token = CancelToken()
        token.cancel("because-i-said-so")
        self.assertEqual(token.reason, "unknown")

    async def test_wait_returns_after_cancel(self):
        token = CancelToken()
        waiter = asyncio.ensure_future(token.wait())
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        token.cancel("user")
        await asyncio.wait_for(waiter, 1)

    async def test_wait_returns_immediately_when_already_cancelled(self):
        token = CancelToken()
        token.cancel("shutdown")
        await asyncio.wait_for(token.wait(), 1)

    async def test_cancel_from_another_thread_wakes_the_loop(self):
        """取消可能来自请求线程或看门狗，唤醒必须回到正确的循环上。"""
        token = CancelToken()
        waiter = asyncio.ensure_future(token.wait())
        await asyncio.sleep(0)
        threading.Thread(target=token.cancel, args=("shutdown",)).start()
        await asyncio.wait_for(waiter, 2)

    async def test_child_cancellation_does_not_reach_the_parent(self):
        """单个工具被取消不该把整个 Run 干掉。"""
        parent = CancelToken()
        child = parent.derive()
        child.cancel("timeout")
        self.assertTrue(child.is_cancelled())
        self.assertFalse(parent.is_cancelled())

    async def test_parent_cancellation_reaches_the_child(self):
        parent = CancelToken()
        child = parent.derive()
        parent.cancel("user")
        self.assertTrue(child.is_cancelled())
        self.assertEqual(child.reason, "user")

    async def test_child_derived_from_a_cancelled_parent_starts_cancelled(self):
        """否则 Run 已经停了，新派生的工具令牌还会照常执行。"""
        parent = CancelToken()
        parent.cancel("shutdown")
        child = parent.derive()
        self.assertTrue(child.is_cancelled())
        self.assertEqual(child.reason, "shutdown")


class ResourceBudgetTests(unittest.TestCase):
    def test_from_limits_copies_every_field(self):
        budget = ResourceBudget.from_limits(RuntimeLimits())
        self.assertEqual(budget, _budget())

    def test_from_limits_does_not_silently_drop_a_new_field(self):
        """字段同名是刻意的：加了新配置项而忘了搬运时，这条会失败。"""
        self.assertEqual(
            set(ResourceBudget.__dataclass_fields__),
            set(RuntimeLimits.__dataclass_fields__),
            "T12 的 max_child_processes 落地时要同时更新这里的两处",
        )

    def test_zero_or_negative_limits_are_rejected(self):
        for name in ResourceBudget.__dataclass_fields__:
            with self.subTest(field=name):
                with self.assertRaises(ValueError):
                    _budget(**{name: 0})

    def test_ordering_is_enforced_here_too(self):
        """直接构造（不经过测试助手的收窄）时也要挡住不合理的组合。"""
        with self.assertRaises(ValueError):
            ResourceBudget(
                max_run_seconds=1800, max_tool_seconds=120, max_shell_seconds=200,
                max_iterations=50, max_tool_calls=100, max_output_bytes=1048576,
            )


class BudgetTrackerTests(unittest.TestCase):
    def setUp(self):
        self.clock = _FakeClock()
        self.tracker = BudgetTracker(_budget(max_run_seconds=100), clock=self.clock)
        self.tracker.start()

    def test_iteration_budget_counts_from_one(self):
        self.assertEqual(self.tracker.before_iteration(), 1)
        self.assertEqual(self.tracker.before_iteration(), 2)

    def test_iteration_budget_exhaustion_names_the_limit(self):
        tracker = BudgetTracker(_budget(max_iterations=2), clock=self.clock)
        tracker.start()
        tracker.before_iteration()
        tracker.before_iteration()
        with self.assertRaises(BudgetExceeded) as ctx:
            tracker.before_iteration()
        self.assertEqual(ctx.exception.code, ITERATION_BUDGET_EXCEEDED)
        self.assertEqual(ctx.exception.details["limit"], 2)

    def test_run_deadline_fires_at_the_limit_not_before(self):
        tracker = BudgetTracker(_budget(max_run_seconds=100), clock=self.clock)
        tracker.start()
        self.clock.advance(99.5)
        tracker.check_run_deadline()
        self.clock.advance(0.5)
        with self.assertRaises(BudgetExceeded) as ctx:
            tracker.check_run_deadline()
        self.assertEqual(ctx.exception.code, RUN_TIMEOUT)

    def test_model_request_checkpoint_shares_the_run_deadline(self):
        tracker = BudgetTracker(_budget(max_run_seconds=100), clock=self.clock)
        tracker.start()
        self.clock.advance(100)
        with self.assertRaises(BudgetExceeded) as ctx:
            tracker.before_model_request()
        self.assertEqual(ctx.exception.code, RUN_TIMEOUT)

    def test_remaining_run_seconds_never_goes_negative(self):
        """负的剩余时间会让 min(shell, remaining) 悄悄取到没意义的值。"""
        self.clock.advance(500)
        self.assertEqual(self.tracker.remaining_run_seconds(), 0.0)

    def test_tool_allowance_is_capped_by_the_remaining_run_time(self):
        """Run 只剩 3 秒时，给工具 120 秒没有意义。"""
        tracker = BudgetTracker(_budget(max_run_seconds=100, max_tool_seconds=30), clock=self.clock)
        tracker.start()
        self.assertEqual(tracker.before_tool_call("Read").seconds, 30)
        self.clock.advance(97)
        self.assertAlmostEqual(tracker.before_tool_call("Read").seconds, 3.0)

    def test_tool_call_budget_exhaustion(self):
        tracker = BudgetTracker(_budget(max_tool_calls=1), clock=self.clock)
        tracker.start()
        tracker.before_tool_call("Read")
        with self.assertRaises(BudgetExceeded) as ctx:
            tracker.before_tool_call("Write")
        self.assertEqual(ctx.exception.code, TOOL_CALL_BUDGET_EXCEEDED)
        self.assertEqual(ctx.exception.details["tool"], "Write")

    def test_after_tool_call_records_an_overrun_instead_of_raising(self):
        """工具已经跑完，副作用已经发生；抛异常只是丢掉结果，撤不回来。"""
        allowance = self.tracker.before_tool_call("Bash")
        self.clock.advance(allowance.seconds + 1)
        self.assertTrue(self.tracker.after_tool_call(allowance, "Bash"))
        self.assertEqual(self.tracker.snapshot().tool_overruns, ("Bash",))

    def test_after_tool_call_marks_a_punctual_tool_as_clean(self):
        allowance = self.tracker.before_tool_call("Read")
        self.clock.advance(allowance.seconds - 1)
        self.assertFalse(self.tracker.after_tool_call(allowance, "Read"))

    def test_output_budget_accumulates_in_bytes(self):
        tracker = BudgetTracker(_budget(max_output_bytes=10), clock=self.clock)
        tracker.start()
        tracker.record_output(6)
        with self.assertRaises(BudgetExceeded) as ctx:
            tracker.record_output(5)
        self.assertEqual(ctx.exception.code, OUTPUT_BUDGET_EXCEEDED)
        self.assertEqual(ctx.exception.details["used_bytes"], 11)

    def test_snapshot_reports_usage(self):
        self.tracker.before_iteration()
        self.tracker.before_tool_call("Read")
        self.tracker.record_output(7)
        self.clock.advance(2)
        usage = self.tracker.snapshot()
        self.assertEqual((usage.iterations, usage.tool_calls, usage.output_bytes), (1, 1, 7))
        self.assertAlmostEqual(usage.elapsed_seconds, 2.0)


class TruncateTests(unittest.TestCase):
    def test_short_text_is_untouched(self):
        result = truncate_bytes("hello", 100)
        self.assertFalse(result.truncated)
        self.assertEqual(result.text, "hello")

    def test_result_never_exceeds_the_limit(self):
        for limit in (10, 11, 50, 99):
            with self.subTest(limit=limit):
                result = truncate_bytes("x" * 1000, limit)
                self.assertLessEqual(len(result.text.encode("utf-8")), limit)
                self.assertTrue(result.truncated)
                self.assertEqual(result.original_bytes, 1000)

    def test_multibyte_characters_are_not_split(self):
        """按字节切很容易把一个汉字切成两半，解码直接报错。"""
        text = "中文输出" * 100
        result = truncate_bytes(text, 41)
        self.assertEqual(result.text.encode("utf-8").decode("utf-8"), result.text)
        self.assertNotIn("\ufffd", result.text)
        self.assertTrue(result.text.startswith("中文输出"))

    def test_marker_is_counted_against_the_limit(self):
        result = truncate_bytes("y" * 100, 30, marker="[..]")
        self.assertTrue(result.text.endswith("[..]"))
        self.assertLessEqual(len(result.text.encode("utf-8")), 30)

    def test_a_limit_too_small_for_the_marker_yields_nothing(self):
        result = truncate_bytes("y" * 100, 3, marker="[truncated]")
        self.assertEqual(result.text, "")
        self.assertTrue(result.truncated)

    def test_zero_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            truncate_bytes("x", 0)


class RunUnderBudgetTests(unittest.IsolatedAsyncioTestCase):
    """终态测试：不管里面发生什么，都要有明确的 status 与 error_code。"""

    async def test_completed_run_reports_usage(self):
        async def work(token, tracker):
            tracker.before_iteration()
            tracker.before_tool_call("Read")
            tracker.record_output(12)
            return "done"

        result = await run_under_budget(work, budget=_budget())
        self.assertEqual(result.status, "completed")
        self.assertIsNone(result.error_code)
        self.assertEqual(result.output, "done")
        self.assertEqual(result.usage.tool_calls, 1)
        self.assertEqual(result.usage.output_bytes, 12)

    async def test_budget_exhaustion_becomes_a_failed_terminal_state(self):
        async def work(token, tracker):
            tracker.before_iteration()
            tracker.before_iteration()
            tracker.before_iteration()

        result = await run_under_budget(work, budget=_budget(max_iterations=2))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, ITERATION_BUDGET_EXCEEDED)

    async def test_unexpected_exception_still_reaches_a_terminal_state(self):
        """有兜底码才能保证 Run 不会永远停在运行中。"""

        async def work(token, tracker):
            raise RuntimeError("something broke")

        result = await run_under_budget(work, budget=_budget())
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, RUN_ERROR)

    async def test_exception_message_is_scrubbed(self):
        async def work(token, tracker):
            raise RuntimeError("connect failed for password=hunter2hunter2")

        result = await run_under_budget(work, budget=_budget())
        self.assertNotIn("hunter2hunter2", result.message)
        self.assertIn("[REDACTED]", result.message)

    async def test_user_cancellation_while_working(self):
        started = asyncio.Event()

        async def work(token, tracker):
            started.set()
            await token.wait()
            token.raise_if_cancelled()

        token = CancelToken()
        task = asyncio.ensure_future(run_under_budget(work, budget=_budget(), token=token))
        await asyncio.wait_for(started.wait(), 1)
        token.cancel("user")
        result = await asyncio.wait_for(task, 2)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.error_code, RUN_CANCELLED)
        self.assertNotIn("error_code", result.to_event_payload(), "用户取消不是错误")

    async def test_deadline_cancels_a_worker_that_never_finishes(self):
        """超时走的是看门狗取消令牌，而不是直接 cancel 工作协程。"""

        async def work(token, tracker):
            await token.wait()
            token.raise_if_cancelled()

        result = await asyncio.wait_for(
            run_under_budget(work, budget=_budget(max_run_seconds=1), cancellation_grace_seconds=1),
            timeout=5,
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, RUN_TIMEOUT)

    async def test_the_deadline_checkpoint_reports_the_same_code_as_the_watchdog(self):
        """两条路径（看门狗取消 / 工作者自己在检查点发现超时）必须给出同一个错误码，
        否则同一种失败在事件流里会有两种写法。"""
        clock = _FakeClock()

        async def work(token, tracker):
            clock.advance(1000)
            tracker.before_model_request()

        result = await run_under_budget(
            work, budget=_budget(max_run_seconds=100), clock=clock
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, RUN_TIMEOUT)

    async def test_worker_that_ignores_the_token_is_force_stopped(self):
        """协作式取消靠对方检查令牌；对方不检查就得有下限。"""

        async def work(token, tracker):
            await asyncio.sleep(30)
            return "never"

        token = CancelToken()
        task = asyncio.ensure_future(
            run_under_budget(work, budget=_budget(), token=token, cancellation_grace_seconds=0.05)
        )
        await asyncio.sleep(0)
        token.cancel("user")
        result = await asyncio.wait_for(task, 2)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.detail, "cancellation_wind_down_timeout")

    async def test_a_worker_that_finishes_anyway_after_cancel_is_not_reported_as_success(self):
        """两种误报代价不对称：说完成了但只做了一半，用户就不会再检查。"""

        async def work(token, tracker):
            await token.wait()
            return "partial"

        token = CancelToken()
        task = asyncio.ensure_future(run_under_budget(work, budget=_budget(), token=token))
        await asyncio.sleep(0)
        token.cancel("user")
        result = await asyncio.wait_for(task, 2)
        self.assertEqual(result.status, "cancelled")

    async def test_an_already_cancelled_parent_does_not_run_the_work(self):
        ran = False

        async def work(token, tracker):
            nonlocal ran
            ran = True

        token = CancelToken()
        token.cancel("shutdown")
        result = await run_under_budget(work, budget=_budget(), token=token)
        self.assertFalse(ran, "派生的子令牌应当已经是取消状态")
        self.assertEqual(result.status, "cancelled")

    async def test_external_task_cancellation_is_not_swallowed(self):
        """那不是 Run 的取消，是调用方在收回协程；吞掉会破坏结构化并发。"""

        async def work(token, tracker):
            await asyncio.sleep(30)

        task = asyncio.ensure_future(run_under_budget(work, budget=_budget()))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


class ResultContractTests(unittest.TestCase):
    def test_every_terminal_status_maps_to_a_known_event_type(self):
        for status in ("completed", "cancelled", "failed"):
            result = RunResult(status=status, usage=BudgetTracker(_budget()).snapshot())
            with self.subTest(status=status):
                self.assertIn(result.terminal_event_type, KNOWN_EVENT_TYPES)
                self.assertIn(result.terminal_event_type, TERMINAL_EVENT_TYPES)

    def test_every_error_code_is_registered(self):
        for code in (
            ITERATION_BUDGET_EXCEEDED,
            OUTPUT_BUDGET_EXCEEDED,
            TOOL_CALL_BUDGET_EXCEEDED,
            RUN_CANCELLED,
            RUN_TIMEOUT,
            RUN_ERROR,
            "tool_timeout",
            "shell_timeout",
        ):
            with self.subTest(code=code):
                self.assertIn(code, ALL_ERROR_CODES)

    def test_limit_codes_are_a_subset_and_do_not_swallow_the_real_errors(self):
        """"被边界挡下"和"代码出错了"要能分开，否则告警只能盯着全部失败。"""
        self.assertTrue(LIMIT_ERROR_CODES < ALL_ERROR_CODES)
        self.assertNotIn(RUN_ERROR, LIMIT_ERROR_CODES)
        self.assertNotIn(RUN_CANCELLED, LIMIT_ERROR_CODES)

    def test_request_carries_its_own_budget_and_workspace(self):
        """预算与工作目录来自服务端，不从请求参数读（C49）。"""
        request = AgentRunRequest(
            session_id=uuid4(),
            workspace=Path("C:/tmp/demo"),
            user_text="hello",
            budget=_budget(),
        )
        self.assertEqual(request.budget.max_iterations, 50)
        self.assertEqual(request.workspace, Path("C:/tmp/demo"))


if __name__ == "__main__":
    unittest.main()
