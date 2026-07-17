import tempfile
import unittest
from pathlib import Path

from huicode.config import TeamConfig
from huicode.teams.storage import TeamStore
from huicode.teams.tasks import SharedTaskStore
from huicode.teams.types import TeamError, TeamRecord


def make_tasks(root: Path) -> SharedTaskStore:
    record = TeamRecord("team-1", "demo", "main", "repo", "C:/repo", "main", "abc", "active", "now", "now")
    store = TeamStore(root, "demo", TeamConfig())
    store.initialize(record)
    return SharedTaskStore(store)


class TeamTaskTests(unittest.TestCase):
    def test_dependencies_block_then_release(self):
        with tempfile.TemporaryDirectory() as temp:
            tasks = make_tasks(Path(temp))
            first = tasks.create("first")
            second = tasks.create("second", dependencies=(first.id,))
            self.assertEqual("blocked", second.status)
            first = tasks.update(first.id, expected_version=first.version, status="completed")
            self.assertEqual("pending", tasks.get(second.id).status)

    def test_conflict_cycle_and_delete_protection(self):
        with tempfile.TemporaryDirectory() as temp:
            tasks = make_tasks(Path(temp))
            first = tasks.create("first")
            second = tasks.create("second", dependencies=(first.id,))
            with self.assertRaisesRegex(TeamError, "依赖"):
                tasks.update(first.id, expected_version=first.version, dependencies=(second.id,))
            with self.assertRaises(TeamError):
                tasks.delete(first.id, first.version)
            changed = tasks.update(first.id, expected_version=first.version, result_summary="x")
            with self.assertRaisesRegex(TeamError, "其他成员"):
                tasks.update(first.id, expected_version=first.version, result_summary="stale")
            self.assertGreater(changed.version, first.version)

    def test_assign_persists_member_and_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            tasks = make_tasks(Path(temp))
            task = tasks.create("edit", paths=("DEMO.md",))
            assigned = tasks.assign(task.id, "alice")
            self.assertEqual("alice", assigned.assignee)
            self.assertEqual("pending", assigned.status)
            self.assertEqual(("DEMO.md",), assigned.paths)


if __name__ == "__main__":
    unittest.main()
