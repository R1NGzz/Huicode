import tempfile
import time
import unittest
from pathlib import Path

from huicode.config import TeamConfig
from huicode.teams.manager import TeamManager
from huicode.worktrees.types import WorktreeDisposition, WorktreeHandle, WorktreeIdentity


class FakeWorktreeManager:
    def __init__(self, root: Path):
        self.root = root
        self.handles = {}

    def prepare(self, task_id, logical_name):
        path = self.root / task_id
        path.mkdir(parents=True, exist_ok=True)
        identity = WorktreeIdentity("repo", task_id, logical_name, "base", f"branch/{task_id}", path, time.time())
        handle = WorktreeHandle(identity, recovered=task_id in self.handles)
        self.handles[task_id] = handle
        return handle

    def enter(self, handle): return handle.path
    def exit(self, handle): return None
    def remove(self, handle): return WorktreeDisposition("removed", "ok")


class TeamManagerTests(unittest.TestCase):
    def wait_status(self, manager, task_id, status, timeout=3):
        deadline = time.time() + timeout
        while time.time() < deadline:
            task = manager.tasks.get(task_id)
            if task.status == status:
                return task
            time.sleep(0.03)
        self.fail(f"task did not reach {status}: {manager.tasks.get(task_id)}")

    def test_member_assignment_approval_and_idle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = TeamConfig(enabled=True, default_backend="coroutine", member_idle_poll_ms=20)
            executed = []
            def executor(member, task_id, prompt, workspace):
                executed.append((member, task_id, prompt, workspace))
                return True, "done", {"output_tokens": 3}
            manager = TeamManager(Path.cwd(), config, FakeWorktreeManager(root / "worktrees"), root=root / "teams", assignment_executor=executor)
            manager.create("demo")
            member = manager.spawn_member("alice", "general", approval_required=True)
            task = manager.tasks.create("change file")
            manager.assign(task.id, "alice", "do it")
            deadline = time.time() + 2
            while time.time() < deadline and (
                not manager.store.load_approvals() or manager.members()[0].status != "waiting_approval"
            ):
                time.sleep(0.03)
            approvals = manager.store.load_approvals()
            self.assertEqual(1, len(approvals))
            self.assertFalse(executed)
            manager.approvals.decide(approvals[0].request_id, "allow")
            manager._wake_member("alice")
            finished = self.wait_status(manager, task.id, "completed")
            self.assertEqual("done", finished.result_summary)
            self.assertEqual(member.worktree_path, str(executed[0][3]))
            deadline = time.time() + 2
            while time.time() < deadline and manager.members()[0].status != "idle":
                time.sleep(0.03)
            self.assertEqual("idle", manager.members()[0].status)
            kinds = {event.kind for event in manager.drain_events()}
            self.assertIn("member_waiting_approval", kinds)
            self.assertIn("member_idle", kinds)
            manager.close()


if __name__ == "__main__":
    unittest.main()
