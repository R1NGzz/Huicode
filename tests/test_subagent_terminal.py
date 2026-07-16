import threading
import time
import unittest

from huicode.subagents.terminal import EventSwitchController


class TerminalSwitchTests(unittest.TestCase):
    def test_completion_timeout_and_manual_paths(self) -> None:
        completed = EventSwitchController()
        done = threading.Event()
        done.set()
        self.assertEqual(completed.wait("task", done, 1), "completed")

        timeout = EventSwitchController()
        self.assertEqual(timeout.wait("task", threading.Event(), 0.05), "timeout")

        manual = EventSwitchController(interactive=True)
        threading.Thread(target=lambda: (time.sleep(0.02), manual.request_switch()), daemon=True).start()
        self.assertEqual(manual.wait("task", threading.Event(), 1), "manual")


if __name__ == "__main__":
    unittest.main()
