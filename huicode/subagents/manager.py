from __future__ import annotations

import threading
import time
import uuid
from queue import Empty, Queue
from typing import Callable

from huicode.config import SubagentConfig
from huicode.hooks.events import sanitize_payload

from .catalog import AgentCatalog
from .terminal import ForegroundSwitchController, TerminalSwitchController
from .types import (
    ForegroundWaitResult,
    ParentAgentSnapshot,
    ResultLease,
    SubagentLaunchRequest,
    SubagentNotification,
    SubagentResult,
    SubagentTask,
    SubagentTaskView,
)
from .workers import DaemonWorkerPool


SubagentRunner = Callable[[SubagentLaunchRequest, SubagentTask], SubagentResult]


class SubagentManager:
    def __init__(
        self,
        catalog: AgentCatalog,
        config: SubagentConfig,
        runner: SubagentRunner,
        *,
        switch_controller: ForegroundSwitchController | None = None,
    ) -> None:
        self.catalog = catalog
        self.config = config
        self.runner = runner
        self.switch_controller = switch_controller or TerminalSwitchController()
        self._pool = DaemonWorkerPool(config.max_background_tasks)
        self._lock = threading.RLock()
        self._tasks: dict[str, SubagentTask] = {}
        self._notifications: Queue[SubagentNotification] = Queue()
        self._pending_results: list[SubagentResult] = []
        self._leases: dict[str, tuple[SubagentResult, ...]] = {}
        self._leased_task_ids: set[str] = set()
        self._parent: ParentAgentSnapshot | None = None
        self._closed = False

    def capture_parent(self, snapshot: ParentAgentSnapshot) -> None:
        with self._lock:
            self._parent = snapshot

    def parent_snapshot(self) -> ParentAgentSnapshot | None:
        with self._lock:
            return self._parent

    def submit(self, request: SubagentLaunchRequest) -> SubagentTaskView:
        with self._lock:
            if self._closed:
                raise RuntimeError("子 Agent 管理器已关闭")
            task_id = f"task-{uuid.uuid4().hex[:8]}"
            background = request.background or request.type == "fork"
            task = SubagentTask(
                id=task_id,
                type=request.type,
                role=request.role,
                task=request.task,
                background=background,
                created_at=time.time(),
            )
            if background:
                task.background_event.set()
            self._tasks[task_id] = task
            self._pool.submit(self._run_task, request, task)
            return self._view(task)

    def submit_defined_background(
        self,
        role: str,
        task_text: str,
        *,
        origin: str = "hook",
    ) -> SubagentTaskView:
        parent = self.parent_snapshot()
        if parent is None:
            raise RuntimeError("尚无可用的主 Agent 快照")
        if self.catalog.get(role) is None:
            raise ValueError(f"未知子 Agent 角色: {role}")
        return self.submit(
            SubagentLaunchRequest(
                type="defined",
                task=task_text,
                role=role,
                background=True,
                parent=parent,
                origin="hook" if origin == "hook" else "tool",
            )
        )

    def wait_foreground(self, task_id: str) -> ForegroundWaitResult:
        with self._lock:
            task = self._require_task(task_id)
        reason = self.switch_controller.wait(
            task_id,
            task.done_event,
            self.config.foreground_timeout_seconds,
        )
        if reason != "completed":
            self.move_to_background(task_id)
        with self._lock:
            return ForegroundWaitResult(reason, self._view(task))

    def move_to_background(self, task_id: str) -> SubagentTaskView:
        with self._lock:
            task = self._require_task(task_id)
            if task.status in {"queued", "running_foreground"}:
                task.background = True
                task.background_event.set()
                if task.status == "running_foreground":
                    task.status = "running_background"
            return self._view(task)

    def list_tasks(self) -> tuple[SubagentTaskView, ...]:
        with self._lock:
            return tuple(self._view(task) for task in self._tasks.values())

    def task_detail(self, task_id: str) -> SubagentTaskView | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return self._view(task) if task is not None else None

    def summary(self) -> dict[str, int]:
        result = {"queued": 0, "running": 0, "ready": 0, "failed": 0}
        with self._lock:
            for task in self._tasks.values():
                if task.status == "queued":
                    result["queued"] += 1
                elif task.status in {"running_foreground", "running_background"}:
                    result["running"] += 1
                elif task.status == "failed":
                    result["failed"] += 1
            result["ready"] = len(self._pending_results)
        return result

    def drain_notifications(self) -> tuple[SubagentNotification, ...]:
        items: list[SubagentNotification] = []
        while True:
            try:
                items.append(self._notifications.get_nowait())
            except Empty:
                return tuple(items)

    def acquire_result_lease(self) -> ResultLease | None:
        with self._lock:
            available = tuple(
                result
                for result in self._pending_results
                if result.task_id not in self._leased_task_ids
            )
            if not available:
                return None
            lease_id = uuid.uuid4().hex[:12]
            self._leases[lease_id] = available
            self._leased_task_ids.update(result.task_id for result in available)
            return ResultLease(lease_id, available)

    def ack_result_lease(self, lease_id: str) -> None:
        with self._lock:
            results = self._leases.pop(lease_id, ())
            ids = {result.task_id for result in results}
            self._leased_task_ids.difference_update(ids)
            self._pending_results = [
                result for result in self._pending_results if result.task_id not in ids
            ]

    def release_result_lease(self, lease_id: str) -> None:
        with self._lock:
            results = self._leases.pop(lease_id, ())
            self._leased_task_ids.difference_update(result.task_id for result in results)

    def clear(self) -> None:
        with self._lock:
            for task in self._tasks.values():
                if task.status in {"queued", "running_foreground", "running_background"}:
                    task.cancel_event.set()
                    task.status = "cancelled"
                    task.done_event.set()
            self._tasks.clear()
            self._pending_results.clear()
            self._leases.clear()
            self._leased_task_ids.clear()
            self._parent = None
        self.drain_notifications()

    def cancel(self, task_id: str) -> SubagentTaskView:
        with self._lock:
            task = self._require_task(task_id)
            if task.status in {"queued", "running_foreground", "running_background"}:
                task.cancel_event.set()
                task.status = "cancelled"
            return self._view(task)

    def close(self, timeout_seconds: float | None = None) -> None:
        timeout = self.config.shutdown_wait_seconds if timeout_seconds is None else timeout_seconds
        with self._lock:
            if self._closed:
                return
            self._closed = True
            running = list(self._tasks.values())
            for task in running:
                if task.status in {"queued", "running_foreground", "running_background"}:
                    task.cancel_event.set()
        deadline = time.monotonic() + max(0.0, timeout)
        for task in running:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            task.done_event.wait(remaining)
        with self._lock:
            for task in running:
                if task.status in {"queued", "running_foreground", "running_background"}:
                    task.status = "cancelled"
                    task.stop_reason = "abandoned"
                    task.done_event.set()
        self._pool.shutdown(cancel_futures=True)

    def _run_task(self, request: SubagentLaunchRequest, task: SubagentTask) -> None:
        with self._lock:
            if task.cancel_event.is_set():
                task.status = "cancelled"
                task.done_event.set()
                return
            task.started_at = time.time()
            task.status = "running_background" if task.background else "running_foreground"
        try:
            result = self.runner(request, task)
        except Exception as exc:  # noqa: BLE001
            result = SubagentResult(
                task_id=task.id,
                status="failed",
                summary="子 Agent 运行失败",
                stop_reason="error",
                error=str(exc),
            )
        with self._lock:
            if self._tasks.get(task.id) is not task:
                task.done_event.set()
                return
            if task.cancel_event.is_set():
                task.status = "cancelled"
            else:
                task.status = result.status
            task.completed_at = time.time()
            task.iterations = result.iterations
            task.stop_reason = result.stop_reason
            task.usage = dict(result.usage)
            task.summary = _sanitize_text(result.summary)
            task.error = _sanitize_text(result.error)
            task.done_event.set()
            if task.background:
                completed = SubagentResult(
                    task_id=task.id,
                    status=task.status,
                    summary=_clip(task.summary or task.error, 4000),
                    stop_reason=task.stop_reason,
                    iterations=task.iterations,
                    usage=_redact_usage(task.usage),
                    error=_clip(task.error, 1000),
                    duration_seconds=max(0.0, task.completed_at - (task.started_at or task.created_at)),
                )
                self._pending_results.append(completed)
                self._notifications.put(
                    SubagentNotification(
                        task_id=task.id,
                        type=task.type,
                        role=task.role,
                        status=task.status,
                        duration_seconds=completed.duration_seconds,
                        summary=_clip(task.summary or task.error, 160),
                    )
                )

    def _require_task(self, task_id: str) -> SubagentTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"未知子 Agent 任务: {task_id}")
        return task

    @staticmethod
    def _view(task: SubagentTask) -> SubagentTaskView:
        return SubagentTaskView(
            id=task.id,
            type=task.type,
            role=task.role,
            task=task.task,
            status=task.status,
            background=task.background,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            iterations=task.iterations,
            stop_reason=task.stop_reason,
            usage=dict(task.usage),
            summary=task.summary,
            error=task.error,
        )


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _redact_usage(usage: dict[str, object]) -> dict[str, object]:
    sanitized = sanitize_payload(usage)
    return sanitized if isinstance(sanitized, dict) else {}


def _sanitize_text(text: str) -> str:
    value = sanitize_payload(text)
    return value if isinstance(value, str) else str(value)
