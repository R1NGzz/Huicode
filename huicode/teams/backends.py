from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .types import TeamError


@dataclass(frozen=True)
class BackendAvailability:
    available: bool
    reason: str = ""


@dataclass(frozen=True)
class MemberLaunchSpec:
    team_path: str
    member_id: str
    member_name: str
    workspace: str
    config_path: str = ""


@dataclass
class BackendHandle:
    kind: str
    id: str
    data: dict[str, str] = field(default_factory=dict)
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    wake_event: threading.Event = field(default_factory=threading.Event, repr=False)
    future: Future | None = field(default=None, repr=False)


class TeamMemberBackend(Protocol):
    kind: str
    def available(self) -> BackendAvailability: ...
    def launch(self, spec: MemberLaunchSpec) -> BackendHandle: ...
    def wake(self, handle: BackendHandle) -> None: ...
    def stop(self, handle: BackendHandle, timeout: float) -> None: ...
    def alive(self, handle: BackendHandle) -> bool: ...


class CoroutineBackend:
    kind = "coroutine"

    def __init__(self, runner: Callable[[MemberLaunchSpec, BackendHandle], None], max_workers: int = 4) -> None:
        self.runner = runner
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="huicode-team")
        self.handles: dict[str, BackendHandle] = {}

    def available(self) -> BackendAvailability:
        return BackendAvailability(True)

    def launch(self, spec: MemberLaunchSpec) -> BackendHandle:
        handle = BackendHandle(self.kind, f"worker-{uuid.uuid4().hex[:10]}")
        handle.future = self.pool.submit(self.runner, spec, handle)
        self.handles[handle.id] = handle
        return handle

    def wake(self, handle: BackendHandle) -> None:
        handle.wake_event.set()

    def stop(self, handle: BackendHandle, timeout: float) -> None:
        handle.stop_event.set()
        handle.wake_event.set()
        if handle.future is not None:
            try:
                handle.future.result(timeout=max(0, timeout))
            except TimeoutError as exc:
                raise TeamError("backend_stop_timeout", "协程成员未在超时内停止") from exc
            except Exception:
                pass

    def alive(self, handle: BackendHandle) -> bool:
        return handle.future is not None and not handle.future.done()

    def close(self) -> None:
        for handle in self.handles.values():
            handle.stop_event.set()
            handle.wake_event.set()
        self.pool.shutdown(wait=False, cancel_futures=True)


class MemberBackendSelector:
    def __init__(self, tmux: TeamMemberBackend, windows_terminal: TeamMemberBackend, coroutine: TeamMemberBackend) -> None:
        self.backends = {backend.kind: backend for backend in (tmux, windows_terminal, coroutine)}

    def select(self, requested: str) -> TeamMemberBackend:
        if requested == "coroutine":
            return self.backends["coroutine"]
        terminal = [self.backends["tmux"], self.backends["windows_terminal"]]
        if requested == "terminal":
            for backend in terminal:
                if backend.available().available:
                    return backend
            reasons = "; ".join(item.available().reason for item in terminal)
            raise TeamError("terminal_unavailable", f"显式要求终端后端，但当前不可用: {reasons}")
        if requested != "auto":
            raise TeamError("invalid_backend", f"未知成员后端: {requested}")
        for backend in (*terminal, self.backends["coroutine"]):
            if backend.available().available:
                return backend
        raise TeamError("backend_unavailable", "没有可用的团队成员后端")
