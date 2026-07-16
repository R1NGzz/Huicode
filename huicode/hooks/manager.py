from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import Future, wait
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from .actions import HookActionExecutor
from .events import event_payload
from .logger import HookLogger
from .matching import match_condition
from .types import (
    HookActionResult,
    HookCatalog,
    HookDispatchResult,
    HookEvent,
    HookPromptBlock,
    HookRuntimeState,
    HookStatusSummary,
)


class HookManager:
    def __init__(
        self,
        catalog: HookCatalog,
        workspace: Path,
        *,
        action_executor: HookActionExecutor | None = None,
        logger: HookLogger | None = None,
        max_workers: int = 4,
    ) -> None:
        self.catalog = catalog
        self.workspace = workspace.resolve()
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.action_executor = action_executor or HookActionExecutor(self.workspace)
        self.logger = logger or HookLogger(self.workspace)
        self._executor = _DaemonWorkerPool(max_workers=max_workers)
        self._lock = threading.RLock()
        self._once_executed: set[str] = set()
        self._pending: dict[Future[HookActionResult], tuple[Any, HookEvent]] = {}
        self._abandoned: set[Future[HookActionResult]] = set()
        self._session_blocks: list[HookPromptBlock] = []
        self._failed = 0
        self._denied = 0
        self._started = False
        self._closed = False

    def set_subagent_submitter(self, submitter) -> None:  # noqa: ANN001
        self.action_executor.set_subagent_submitter(submitter)

    def start_session(self, event: HookEvent, state: HookRuntimeState) -> HookDispatchResult:
        with self._lock:
            if self._started:
                return HookDispatchResult()
            self._started = True
        return self.dispatch(event, state)

    def dispatch(self, event: HookEvent, state: HookRuntimeState) -> HookDispatchResult:
        payload = event_payload(event)
        records: list[HookActionResult] = []
        for rule in self.catalog.rules:
            if not rule.enabled or rule.event != event.name:
                continue
            try:
                if not match_condition(rule.condition, payload):
                    continue
                if rule.once and not self._mark_once(rule.id):
                    continue
                if rule.async_run:
                    self._schedule(rule, event, payload)
                    records.append(HookActionResult("scheduled", "Hook 已提交后台执行"))
                    continue
                result = self._execute(rule, event, payload, state)
            except Exception as exc:  # noqa: BLE001 - Hook 边界必须失败开放
                result = HookActionResult("failed", f"Hook 运行异常: {exc}")
                self._record(rule, event, result, 0)
                self._increment_status(result)
            records.append(result)
            if event.name == "tool_before" and result.status == "denied":
                return HookDispatchResult(
                    denied=True,
                    denied_by=rule.id,
                    deny_reason=result.deny_reason or result.message,
                    records=tuple(records),
                )
        return HookDispatchResult(records=tuple(records))

    def prompt_blocks(self, state: HookRuntimeState) -> tuple[str, ...]:
        with self._lock:
            blocks = [*self._session_blocks, *state.turn_blocks, *state.next_request_blocks]
        return tuple(block.render() for block in blocks if block.content.strip())

    def consume_next_request(self, state: HookRuntimeState) -> None:
        state.next_request_blocks.clear()

    def end_turn(self, state: HookRuntimeState) -> None:
        state.clear_turn()

    def clear_transient(self, state: HookRuntimeState) -> None:
        state.clear_turn()

    def summary(self) -> HookStatusSummary:
        with self._lock:
            return HookStatusSummary(
                effective=self.catalog.effective_count,
                disabled=self.catalog.disabled_count,
                pending=len(self._pending),
                failed=self._failed,
                denied=self._denied,
                write_failures=self.logger.write_failures,
                log_path=self.logger.path.as_posix(),
                source_counts=dict(self.catalog.source_counts),
            )

    def close(self, event: HookEvent | None = None, state: HookRuntimeState | None = None) -> None:
        with self._lock:
            if self._closed:
                return
        if event is not None:
            self.dispatch(event, state or HookRuntimeState())
        with self._lock:
            self._closed = True
            pending = set(self._pending)
        _, unfinished = wait(pending, timeout=2.0) if pending else (set(), set())
        for future in unfinished:
            with self._lock:
                metadata = self._pending.pop(future, None)
                self._abandoned.add(future)
            future.cancel()
            if metadata is not None:
                rule, pending_event = metadata
                self._record(
                    rule,
                    pending_event,
                    HookActionResult("skipped", "会话结束，后台 Hook 未在等待上限内完成"),
                    2000,
                )
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _execute(self, rule, event, payload, state) -> HookActionResult:  # noqa: ANN001
        started = time.monotonic()
        result = self.action_executor.execute(
            rule,
            payload,
            inject_prompt=lambda block: self._inject(block, state),
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        self._record(rule, event, result, duration_ms)
        self._increment_status(result)
        return result

    def _schedule(self, rule, event, payload) -> None:  # noqa: ANN001
        scheduled = HookActionResult("scheduled", "Hook 已提交后台执行")
        self._record(rule, event, scheduled, 0)
        started = time.monotonic()
        future = self._executor.submit(self.action_executor.execute, rule, payload, None)
        with self._lock:
            self._pending[future] = (rule, event)

        def completed(done: Future[HookActionResult]) -> None:
            with self._lock:
                if done in self._abandoned:
                    self._abandoned.discard(done)
                    return
            try:
                result = done.result()
            except Exception as exc:  # noqa: BLE001
                result = HookActionResult("failed", f"后台 Hook 异常: {exc}")
            self._record(rule, event, result, int((time.monotonic() - started) * 1000))
            self._increment_status(result)
            with self._lock:
                self._pending.pop(done, None)

        future.add_done_callback(completed)

    def _inject(self, block: HookPromptBlock, state: HookRuntimeState) -> None:
        if block.scope == "session":
            with self._lock:
                self._session_blocks.append(block)
        elif block.scope == "turn":
            state.turn_blocks.append(block)
        else:
            state.next_request_blocks.append(block)

    def _mark_once(self, rule_id: str) -> bool:
        with self._lock:
            if rule_id in self._once_executed:
                return False
            self._once_executed.add(rule_id)
            return True

    def _increment_status(self, result: HookActionResult) -> None:
        with self._lock:
            if result.status in {"failed", "timeout"}:
                self._failed += 1
            elif result.status == "denied":
                self._denied += 1

    def _record(self, rule, event: HookEvent, result: HookActionResult, duration_ms: int) -> None:  # noqa: ANN001
        self.logger.write(
            {
                "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "rule_id": rule.id,
                "event": event.name,
                "action": rule.action.type,
                "status": result.status,
                "duration_ms": duration_ms,
                "agent_scope": event.agent_scope,
                "summary": result.message,
                "deny_reason": result.deny_reason,
                "data": result.data,
            }
        )


class _DaemonWorkerPool:
    def __init__(self, max_workers: int) -> None:
        self._queue: Queue[tuple[Future, Any, tuple[Any, ...]] | None] = Queue()
        self._closed = False
        self._lock = threading.Lock()
        self._threads = [
            threading.Thread(target=self._worker, name=f"huicode-hook-{index + 1}", daemon=True)
            for index in range(max(1, max_workers))
        ]
        for thread in self._threads:
            thread.start()

    def submit(self, function, *args) -> Future:  # noqa: ANN001
        with self._lock:
            if self._closed:
                raise RuntimeError("Hook 后台执行器已关闭")
            future: Future = Future()
            self._queue.put((future, function, args))
            return future

    def shutdown(self, wait: bool = False, cancel_futures: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if cancel_futures:
            while True:
                try:
                    item = self._queue.get_nowait()
                except Empty:
                    break
                if item is not None:
                    item[0].cancel()
        for _ in self._threads:
            self._queue.put(None)
        if wait:
            for thread in self._threads:
                thread.join()

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            future, function, args = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                result = function(*args)
            except BaseException as exc:  # noqa: BLE001 - Future 必须接住任务异常
                future.set_exception(exc)
            else:
                future.set_result(result)
