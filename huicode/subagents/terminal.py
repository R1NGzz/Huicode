from __future__ import annotations

import os
import sys
import threading
import time
from typing import Literal, Protocol


WaitReason = Literal["completed", "timeout", "manual"]


class ForegroundSwitchController(Protocol):
    def wait(
        self,
        task_id: str,
        done: threading.Event,
        timeout_seconds: float,
    ) -> WaitReason: ...


class EventSwitchController:
    """可测试的前台等待器，CLI 通过 request_switch 触发 Ctrl+B 语义。"""

    def __init__(self, *, interactive: bool = False) -> None:
        self.interactive = interactive
        self._manual = threading.Event()

    def request_switch(self) -> None:
        self._manual.set()

    def wait(self, task_id: str, done: threading.Event, timeout_seconds: float) -> WaitReason:
        del task_id
        started = time.monotonic()
        while True:
            if done.wait(0.05):
                return "completed"
            if self._manual.is_set():
                self._manual.clear()
                return "manual"
            if time.monotonic() - started >= timeout_seconds:
                return "timeout"


class TerminalSwitchController(EventSwitchController):
    def __init__(self) -> None:
        super().__init__(interactive=sys.stdin.isatty())

    def wait(self, task_id: str, done: threading.Event, timeout_seconds: float) -> WaitReason:
        if not self.interactive:
            return super().wait(task_id, done, timeout_seconds)
        listener_stop = threading.Event()
        threading.Thread(target=self._listen, args=(done, listener_stop), daemon=True).start()
        try:
            return super().wait(task_id, done, timeout_seconds)
        finally:
            listener_stop.set()

    def _listen(self, done: threading.Event, listener_stop: threading.Event) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                while not done.is_set() and not listener_stop.is_set():
                    if msvcrt.kbhit() and msvcrt.getwch() == "\x02":
                        self.request_switch()
                        return
                    time.sleep(0.03)
                return
            import select
            import termios
            import tty

            fd = sys.stdin.fileno()
            original = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                while not done.is_set() and not listener_stop.is_set():
                    ready, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if ready and sys.stdin.read(1) == "\x02":
                        self.request_switch()
                        return
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, original)
        except Exception:  # 终端能力不可用时退化为超时路径
            return
