from __future__ import annotations

import threading
from concurrent.futures import Future
from queue import Empty, Queue
from typing import Any, Callable


class DaemonWorkerPool:
    def __init__(self, max_workers: int) -> None:
        self._queue: Queue[tuple[Future, Callable[..., Any], tuple[Any, ...]] | None] = Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._threads = [
            threading.Thread(
                target=self._worker,
                name=f"huicode-subagent-{index + 1}",
                daemon=True,
            )
            for index in range(max(1, max_workers))
        ]
        for thread in self._threads:
            thread.start()

    def submit(self, function: Callable[..., Any], *args: Any) -> Future:
        with self._lock:
            if self._closed:
                raise RuntimeError("子 Agent 后台执行器已关闭")
            future: Future = Future()
            self._queue.put((future, function, args))
            return future

    def shutdown(self, *, cancel_futures: bool = True) -> None:
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
            except BaseException as exc:  # noqa: BLE001
                future.set_exception(exc)
            else:
                future.set_result(result)
