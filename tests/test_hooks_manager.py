import json
import tempfile
import time
import unittest
from pathlib import Path

from huicode.hooks.events import make_event
from huicode.hooks.logger import HookLogger
from huicode.hooks.manager import HookManager
from huicode.hooks.types import (
    CommandAction,
    HookActionResult,
    HookCatalog,
    HookRule,
    HookRuntimeState,
    PromptAction,
)


class FakeExecutor:
    def __init__(self, results=None, delay=0):
        self.results = list(results or [HookActionResult("success", "ok")])
        self.delay = delay
        self.calls = []

    def execute(self, rule, payload, inject_prompt=None):  # noqa: ANN001
        self.calls.append(rule.id)
        if self.delay:
            time.sleep(self.delay)
        if isinstance(rule.action, PromptAction) and inject_prompt is not None:
            from huicode.hooks.types import HookPromptBlock

            inject_prompt(HookPromptBlock(rule.id, rule.action.scope, rule.action.content, rule.event))
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


class HookManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.state = HookRuntimeState()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def event(self, name="turn_start"):
        return make_event(name, session_id="s", workspace=self.workspace, data={"turn": {"input": "x"}})

    def test_once_and_first_denial_stop_dispatch(self) -> None:
        rules = (
            HookRule("first", "tool_before", CommandAction(command="x"), once=True),
            HookRule("deny", "tool_before", CommandAction(command="x")),
            HookRule("last", "tool_before", CommandAction(command="x")),
        )
        executor = FakeExecutor(
            [HookActionResult("success"), HookActionResult("denied", deny_reason="blocked")]
        )
        manager = HookManager(HookCatalog(rules), self.workspace, action_executor=executor)
        event = self.event("tool_before")
        result = manager.dispatch(event, self.state)
        manager.dispatch(event, self.state)
        manager.close()
        self.assertTrue(result.denied)
        self.assertEqual(result.denied_by, "deny")
        self.assertEqual(executor.calls, ["first", "deny", "deny"])

    def test_prompt_scopes_and_async_status(self) -> None:
        rules = (
            HookRule("session", "turn_start", PromptAction(content="session", scope="session")),
            HookRule("turn", "turn_start", PromptAction(content="turn", scope="turn")),
            HookRule("next", "turn_start", PromptAction(content="next", scope="next_request")),
            HookRule("async", "turn_start", CommandAction(command="x"), async_run=True),
        )
        executor = FakeExecutor(delay=0.05)
        manager = HookManager(HookCatalog(rules), self.workspace, action_executor=executor)
        started = time.monotonic()
        manager.dispatch(self.event(), self.state)
        elapsed = time.monotonic() - started
        blocks = "\n".join(manager.prompt_blocks(self.state))
        self.assertIn("session", blocks)
        self.assertIn("turn", blocks)
        self.assertIn("next", blocks)
        manager.consume_next_request(self.state)
        self.assertNotIn(">\nnext\n", "\n".join(manager.prompt_blocks(self.state)))
        manager.end_turn(self.state)
        remaining = "\n".join(manager.prompt_blocks(self.state))
        self.assertIn("session", remaining)
        self.assertNotIn(">\nturn\n", remaining)
        self.assertLess(elapsed, 0.18)
        time.sleep(0.1)
        self.assertEqual(manager.summary().pending, 0)
        manager.close()

    def test_logger_writes_jsonl_and_redacts(self) -> None:
        rule = HookRule("log", "turn_start", CommandAction(command="x"))
        executor = FakeExecutor([HookActionResult("failed", "bad", data={"api_key": "secret"})])
        manager = HookManager(HookCatalog((rule,)), self.workspace, action_executor=executor)
        manager.dispatch(self.event(), self.state)
        manager.close()
        lines = manager.logger.path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        self.assertEqual(record["status"], "failed")
        self.assertNotIn("secret", lines[0])

    def test_close_is_bounded_and_marks_unfinished_async_hook(self) -> None:
        rule = HookRule("slow", "turn_start", CommandAction(command="x"), async_run=True)
        manager = HookManager(HookCatalog((rule,)), self.workspace, action_executor=FakeExecutor(delay=3))
        manager.dispatch(self.event(), self.state)
        started = time.monotonic()
        manager.close()
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.5)
        records = [json.loads(line) for line in manager.logger.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([record["status"] for record in records], ["scheduled", "skipped"])
        self.assertEqual(manager.summary().pending, 0)

    def test_session_prompt_survives_transient_clear(self) -> None:
        rule = HookRule("session", "session_start", PromptAction(content="SESSION", scope="session"))
        manager = HookManager(HookCatalog((rule,)), self.workspace)
        manager.start_session(self.event("session_start"), self.state)
        manager.clear_transient(self.state)
        self.assertIn("SESSION", "\n".join(manager.prompt_blocks(self.state)))
        manager.close()

    def test_logger_write_failure_is_isolated(self) -> None:
        (self.workspace / ".huicode").write_text("not a directory", encoding="utf-8")
        logger = HookLogger(self.workspace)
        logger.write({"status": "success", "event": "turn_start"})
        self.assertEqual(logger.write_failures, 1)


if __name__ == "__main__":
    unittest.main()
