import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

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

    def test_spawn_allows_free_role_and_creates_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = TeamManager(
                Path.cwd(),
                TeamConfig(enabled=True, default_backend="coroutine"),
                FakeWorktreeManager(root / "worktrees"),
                root=root / "teams",
            )
            manager.create("demo")
            member = manager.spawn_member("alice", "new-role")
            self.assertEqual("new-role", member.role)
            self.assertTrue(Path(member.worktree_path).is_dir())
            self.assertTrue(member.branch)
            manager.close()

    def test_spawn_refreshes_and_snapshots_defined_role(self):
        class Catalog:
            def __init__(self): self.refreshes = 0
            def initialize(self): self.refreshes += 1
            def get(self, name):
                if name != "alice": return None
                return SimpleNamespace(
                    name="alice", instructions="只修改 A", allowed_tools=("Read", "Edit"),
                    denied_tools=("Bash",), model="inherit", max_iterations=12,
                    permission_mode="strict", source_path=Path("Alice.md"),
                )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog = Catalog()
            manager = TeamManager(
                Path.cwd(), TeamConfig(enabled=True, default_backend="coroutine"),
                FakeWorktreeManager(root / "worktrees"), root=root / "teams",
                agent_catalog=catalog,
            )
            manager.create("demo")
            member = manager.spawn_member("Alice", "Alice")
            self.assertEqual(1, catalog.refreshes)
            self.assertEqual("只修改 A", member.role_profile["instructions"])
            self.assertEqual(["Read", "Edit"], member.role_profile["allowed_tools"])
            self.assertEqual(12, member.role_profile["max_iterations"])
            self.assertTrue(Path(member.worktree_path).is_dir())
            manager.close()

    def test_broken_catalog_falls_back_to_free_role(self):
        class BrokenCatalog:
            def initialize(self): raise ValueError("bad role file")
            def get(self, name): return None

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = TeamManager(
                Path.cwd(), TeamConfig(enabled=True, default_backend="coroutine"),
                FakeWorktreeManager(root / "worktrees"), root=root / "teams",
                agent_catalog=BrokenCatalog(),
            )
            manager.create("demo")
            member = manager.spawn_member("alice", "unregistered")
            self.assertTrue(Path(member.worktree_path).is_dir())
            self.assertEqual({}, member.role_profile)
            self.assertIn("role_catalog_warning", {event.kind for event in manager.drain_events()})
            manager.close()

    def test_member_self_claims_persisted_assignment_without_mail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executed = []
            def executor(member, task_id, prompt, workspace):
                executed.append((member, task_id, prompt, workspace))
                return True, "done", {}
            manager = TeamManager(
                Path.cwd(), TeamConfig(enabled=True, default_backend="coroutine", member_idle_poll_ms=20),
                FakeWorktreeManager(root / "worktrees"), root=root / "teams",
                assignment_executor=executor,
            )
            manager.create("demo")
            manager.spawn_member("alice", "general")
            task = manager.tasks.create("self claim", "do it")
            manager.tasks.assign(task.id, "alice")
            finished = self.wait_status(manager, task.id, "completed")
            self.assertEqual("alice", finished.assignee)
            self.assertEqual(1, len(executed))
            waited = manager.wait_tasks((task.id,), 1)
            self.assertTrue(waited["completed"])
            manager.close()

    def test_resume_recovers_old_assignment_and_switches_auto_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = TeamConfig(enabled=True, default_backend="coroutine", member_idle_poll_ms=20)
            worktrees = FakeWorktreeManager(root / "worktrees")
            first = TeamManager(Path.cwd(), config, worktrees, root=root / "teams")
            first.create("demo")
            member = first.spawn_member("alice", "general")
            task = first.tasks.create("resume work")
            first.close()
            first.mailbox.send("lead", ("alice",), "do it", message_type="assignment", correlation_id=task.id, task_id=task.id)
            first.store.save_members([replace(member, actual_backend="windows_terminal", requested_backend="auto")])

            executed = []
            second = TeamManager(
                Path.cwd(), config, worktrees, root=root / "teams",
                assignment_executor=lambda member, task_id, prompt, workspace: (executed.append(task_id) is None, "done", {}),
            )
            second.resume("demo")
            finished = self.wait_status(second, task.id, "completed")
            self.assertEqual("alice", finished.assignee)
            self.assertEqual([task.id], executed)
            self.assertEqual("coroutine", second.members()[0].actual_backend)
            second.close()


if __name__ == "__main__":
    unittest.main()
