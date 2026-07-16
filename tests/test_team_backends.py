import threading
import unittest

from huicode.teams.backends import BackendAvailability, BackendHandle, CoroutineBackend, MemberBackendSelector, MemberLaunchSpec
from huicode.teams.types import TeamError


class FakeBackend:
    def __init__(self, kind, available):
        self.kind = kind
        self.value = available
    def available(self): return BackendAvailability(self.value, "no")
    def launch(self, spec): return BackendHandle(self.kind, spec.member_id)
    def wake(self, handle): handle.wake_event.set()
    def stop(self, handle, timeout): handle.stop_event.set()
    def alive(self, handle): return not handle.stop_event.is_set()


class TeamBackendTests(unittest.TestCase):
    def test_priority_and_terminal_never_downgrades(self):
        selector = MemberBackendSelector(FakeBackend("tmux", False), FakeBackend("windows_terminal", True), FakeBackend("coroutine", True))
        self.assertEqual("windows_terminal", selector.select("auto").kind)
        self.assertEqual("windows_terminal", selector.select("terminal").kind)
        selector = MemberBackendSelector(FakeBackend("tmux", False), FakeBackend("windows_terminal", False), FakeBackend("coroutine", True))
        self.assertEqual("coroutine", selector.select("auto").kind)
        with self.assertRaises(TeamError):
            selector.select("terminal")

    def test_coroutine_wake_and_stop(self):
        started = threading.Event()
        def run(spec, handle):
            started.set(); handle.wake_event.wait(1); handle.stop_event.wait(1)
        backend = CoroutineBackend(run, 1)
        handle = backend.launch(MemberLaunchSpec("x", "id", "alice", "x"))
        self.assertTrue(started.wait(1))
        backend.wake(handle)
        backend.stop(handle, 1)
        self.assertFalse(backend.alive(handle))
        backend.close()


if __name__ == "__main__":
    unittest.main()
