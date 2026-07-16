import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from huicode.config import TeamConfig
from huicode.teams.integration import IntegrationManager
from huicode.teams.storage import TeamStore
from huicode.teams.types import TeamError, TeamMemberRecord, TeamRecord
from huicode.teams.worktrees import TeamWorktree
from huicode.worktrees.types import WorktreeHandle, WorktreeIdentity


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=cwd, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode:
        raise AssertionError(completed.stderr or completed.stdout)
    return completed.stdout.strip()


class FakeIntegrationWorktrees:
    def __init__(self, repo: Path, root: Path):
        self.repo = repo
        self.root = root

    def prepare_integration(self, team_id: str, attempt_id: str) -> TeamWorktree:
        path = self.root / attempt_id
        branch = f"integration/{attempt_id}"
        git(self.repo, "worktree", "add", "-b", branch, str(path), "HEAD")
        identity = WorktreeIdentity("repo", "task-12345678", "teams/integration/demo", git(path, "rev-parse", "HEAD"), branch, path, time.time())
        return TeamWorktree(WorktreeHandle(identity))


class FakeManager:
    def __init__(self, repo: Path, root: Path, team: TeamRecord, members):
        self.workspace = repo
        self.config = TeamConfig(enabled=True)
        self.team = team
        self._members = members
        self.worktrees = FakeIntegrationWorktrees(repo, root / "integration")
        self.store = TeamStore(root / "teams", "demo", self.config)
        self.store.initialize(team)
    def _require_team(self): return self.team
    def _require_store(self): return self.store
    def members(self): return self._members


class TeamIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        git(self.repo, "init")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / "base.txt").write_text("base", encoding="utf-8")
        git(self.repo, "add", "."); git(self.repo, "commit", "-m", "base")
        self.target = git(self.repo, "branch", "--show-current")
        self.base = git(self.repo, "rev-parse", "HEAD")
        members = []
        for index, name in enumerate(("alice", "bob"), 1):
            branch = f"member-{name}"
            path = root / name
            git(self.repo, "worktree", "add", "-b", branch, str(path), self.base)
            (path / f"{name}.txt").write_text(name, encoding="utf-8")
            git(path, "add", "."); git(path, "commit", "-m", name)
            members.append(TeamMemberRecord(f"member-{index}", name, "general", "coroutine", "coroutine", False, "idle", f"task-0000000{index}", str(path), branch, str(root / f"{name}.jsonl")))
        team = TeamRecord("team-1", "demo", "main", "repo", str(self.repo), self.target, self.base, "active", "now", "now")
        self.manager = FakeManager(self.repo, root / "state", team, tuple(members))

    def tearDown(self):
        self.temp.cleanup()

    def test_merge_verify_and_publish(self):
        integration = IntegrationManager(self.manager)
        ready = integration.start()
        self.assertEqual("ready", ready.status)
        self.assertFalse((self.repo / "alice.txt").exists())
        published = integration.publish()
        self.assertEqual("published", published.status)
        self.assertEqual("alice", (self.repo / "alice.txt").read_text(encoding="utf-8"))
        self.assertEqual("bob", (self.repo / "bob.txt").read_text(encoding="utf-8"))

    def test_target_drift_is_rejected(self):
        integration = IntegrationManager(self.manager)
        self.assertEqual("ready", integration.start().status)
        (self.repo / "late.txt").write_text("late", encoding="utf-8")
        git(self.repo, "add", "."); git(self.repo, "commit", "-m", "late")
        with self.assertRaisesRegex(TeamError, "目标分支已变化"):
            integration.publish()


if __name__ == "__main__":
    unittest.main()
