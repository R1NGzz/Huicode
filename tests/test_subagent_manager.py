import tempfile
import threading
import time
import unittest
from pathlib import Path

from huicode.config import SubagentConfig
from huicode.subagents.catalog import AgentCatalog
from huicode.subagents.manager import SubagentManager
from huicode.subagents.types import SubagentLaunchRequest, SubagentResult
from huicode.tools.registry import create_default_registry


class SubagentManagerTests(unittest.TestCase):
    def test_background_result_lease_release_and_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            catalog = AgentCatalog(
                {name: () for name in ("plugin", "builtin", "user", "project")},
                create_default_registry(base),
                SubagentConfig(),
            )
            catalog.initialize()
            manager = SubagentManager(
                catalog,
                SubagentConfig(),
                lambda request, task: SubagentResult(task.id, "completed", "done", "final", 2, {"output_tokens": 3}),
            )
            task = manager.submit(SubagentLaunchRequest("fork", "work", None, True, _parent(base)))
            self.assertTrue(_wait(lambda: manager.task_detail(task.id).status == "completed"))
            lease = manager.acquire_result_lease()
            self.assertEqual(lease.results[0].summary, "done")
            manager.release_result_lease(lease.id)
            retry = manager.acquire_result_lease()
            self.assertIsNotNone(retry)
            manager.ack_result_lease(retry.id)
            self.assertIsNone(manager.acquire_result_lease())
            manager.close()

    def test_clear_does_not_allow_late_result_to_return(self) -> None:
        gate = threading.Event()

        def blocked(request, task):  # noqa: ANN001
            gate.wait(1)
            return SubagentResult(task.id, "cancelled", "cancelled", "cancelled")

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            catalog = AgentCatalog(
                {name: () for name in ("plugin", "builtin", "user", "project")},
                create_default_registry(base),
                SubagentConfig(),
            )
            catalog.initialize()
            manager = SubagentManager(catalog, SubagentConfig(), blocked)
            manager.submit(SubagentLaunchRequest("fork", "work", None, True, _parent(base)))
            manager.clear()
            gate.set()
            time.sleep(0.1)
            self.assertIsNone(manager.acquire_result_lease())
            manager.close()

    def test_background_outputs_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            catalog = AgentCatalog(
                {name: () for name in ("plugin", "builtin", "user", "project")},
                create_default_registry(base),
                SubagentConfig(),
            )
            catalog.initialize()
            manager = SubagentManager(
                catalog,
                SubagentConfig(),
                lambda request, task: SubagentResult(
                    task.id,
                    "completed",
                    "Authorization: Bearer secret-value",
                    "final",
                    usage={"api_key": "secret", "nested": {"cookie": "secret"}},
                ),
            )
            task = manager.submit(SubagentLaunchRequest("fork", "work", None, True, _parent(base)))
            self.assertTrue(_wait(lambda: manager.task_detail(task.id).status == "completed"))
            detail = manager.task_detail(task.id)
            lease = manager.acquire_result_lease()
            self.assertNotIn("secret-value", detail.summary)
            self.assertNotIn("secret", str(lease.results[0].usage))
            manager.close()

    def test_background_notification_keeps_useful_completed_result(self) -> None:
        summary = "result-" * 80
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            catalog = AgentCatalog(
                {name: () for name in ("plugin", "builtin", "user", "project")},
                create_default_registry(base),
                SubagentConfig(),
            )
            catalog.initialize()
            manager = SubagentManager(
                catalog,
                SubagentConfig(),
                lambda request, task: SubagentResult(task.id, "completed", summary, "final"),
            )
            task = manager.submit(SubagentLaunchRequest("fork", "work", None, True, _parent(base)))
            self.assertTrue(_wait(lambda: manager.task_detail(task.id).status == "completed"))
            notices = manager.drain_notifications()
            self.assertEqual(summary, notices[0].summary)
            self.assertNotIn("[truncated]", notices[0].summary)
            manager.close()

    def test_worker_limit_queues_extra_task(self) -> None:
        gate = threading.Event()
        started = threading.Event()

        def blocked(request, task):  # noqa: ANN001
            started.set()
            gate.wait(1)
            return SubagentResult(task.id, "completed", "done", "final")

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            catalog = AgentCatalog(
                {name: () for name in ("plugin", "builtin", "user", "project")},
                create_default_registry(base),
                SubagentConfig(),
            )
            catalog.initialize()
            manager = SubagentManager(catalog, SubagentConfig(max_background_tasks=1), blocked)
            first = manager.submit(SubagentLaunchRequest("fork", "one", None, True, _parent(base)))
            self.assertTrue(started.wait(1))
            second = manager.submit(SubagentLaunchRequest("fork", "two", None, True, _parent(base)))
            self.assertIn(manager.task_detail(first.id).status, {"running_background", "completed"})
            self.assertEqual(manager.task_detail(second.id).status, "queued")
            gate.set()
            self.assertTrue(_wait(lambda: manager.task_detail(second.id).status == "completed"))
            manager.close()

    def test_close_is_bounded_when_runner_ignores_cancel(self) -> None:
        gate = threading.Event()

        def blocked(request, task):  # noqa: ANN001
            gate.wait(2)
            return SubagentResult(task.id, "cancelled", "stopped", "cancelled")

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            catalog = AgentCatalog(
                {name: () for name in ("plugin", "builtin", "user", "project")},
                create_default_registry(base),
                SubagentConfig(),
            )
            catalog.initialize()
            manager = SubagentManager(catalog, SubagentConfig(shutdown_wait_seconds=0.05), blocked)
            manager.submit(SubagentLaunchRequest("fork", "one", None, True, _parent(base)))
            started = time.monotonic()
            manager.close()
            elapsed = time.monotonic() - started
            gate.set()
        self.assertLess(elapsed, 0.3)


def _parent(base: Path):
    from huicode.permissions import PermissionContext
    from huicode.prompts import PromptBundle
    from huicode.subagents.types import ParentAgentSnapshot, PermissionSnapshot

    return ParentAgentSnapshot((), PromptBundle(), ("Read",), "chat", PermissionSnapshot(PermissionContext(base)))


def _wait(predicate, timeout=2):  # noqa: ANN001
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


if __name__ == "__main__":
    unittest.main()
