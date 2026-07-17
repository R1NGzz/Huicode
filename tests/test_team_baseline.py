import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from huicode.config import TeamConfig, WorktreeConfig
from huicode.cli import _commit_team_member_changes
from huicode.teams.integration import IntegrationManager
from huicode.teams.manager import TeamManager
from huicode.worktrees import WorktreeManager


def git(workspace: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=workspace, shell=False, capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=True,
    )
    return completed.stdout.strip()


class TeamBaselineTests(unittest.TestCase):
    def test_untracked_task_file_becomes_shared_member_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            git(repo, "init")
            git(repo, "config", "user.name", "Test")
            git(repo, "config", "user.email", "test@example.com")
            (repo / ".gitignore").write_text(".huicode/\n", encoding="utf-8")
            (repo / "base.txt").write_text("base\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "base")
            original = git(repo, "rev-parse", "HEAD")
            (repo / "DEMO.md").write_text("# Demo\n\n## section A\n\n## section B\n", encoding="utf-8")

            manager = TeamManager(
                repo,
                TeamConfig(enabled=True, default_backend="coroutine", member_idle_poll_ms=20),
                WorktreeManager(repo, WorktreeConfig(copy_files=())),
                root=root / "teams",
                assignment_executor=lambda *args: (True, "done", {}),
            )
            manager.create("demo")
            alice = manager.spawn_member("alice", "general")
            bob = manager.spawn_member("bob", "general")
            task = manager.tasks.create("edit DEMO.md", "edit section A", paths=("DEMO.md",))
            manager.assign(task.id, "alice", "edit DEMO.md")

            self.assertEqual((repo / "DEMO.md").read_text(encoding="utf-8"), (Path(alice.worktree_path) / "DEMO.md").read_text(encoding="utf-8"))
            self.assertEqual((repo / "DEMO.md").read_text(encoding="utf-8"), (Path(bob.worktree_path) / "DEMO.md").read_text(encoding="utf-8"))
            self.assertEqual(git(Path(alice.worktree_path), "rev-parse", "HEAD"), git(Path(bob.worktree_path), "rev-parse", "HEAD"))
            self.assertEqual(original, git(repo, "rev-parse", "HEAD"))
            self.assertIn("DEMO.md", git(repo, "status", "--porcelain"))
            manager.close()

    def test_parallel_members_commit_integrate_and_publish_untracked_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            git(repo, "init")
            git(repo, "config", "user.name", "Test")
            git(repo, "config", "user.email", "test@example.com")
            (repo / ".gitignore").write_text(".huicode/\n", encoding="utf-8")
            (repo / "base.txt").write_text("base\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "base")
            (repo / "DEMO.md").write_text("# Demo\n\n## section A\n\n## section B\n", encoding="utf-8")
            (repo / "unrelated.txt").write_text("keep me\n", encoding="utf-8")

            def executor(member, task_id, prompt, workspace):
                path = workspace / "DEMO.md"
                text = path.read_text(encoding="utf-8")
                if member == "alice":
                    text = text.replace("## section A\n", "## section A\n- Alice updated\n")
                else:
                    text = text.replace("## section B\n", "## section B\n- Bob updated\n")
                path.write_text(text, encoding="utf-8")
                commit = _commit_team_member_changes(workspace, member, task_id)
                return True, f"done {commit}", {}

            manager = TeamManager(
                repo,
                TeamConfig(enabled=True, default_backend="coroutine", member_idle_poll_ms=20),
                WorktreeManager(repo, WorktreeConfig(copy_files=())),
                root=root / "teams",
                assignment_executor=executor,
            )
            manager.create("demo")
            manager.spawn_member("alice", "general")
            manager.spawn_member("bob", "general")
            first = manager.tasks.create("Alice edits DEMO.md", paths=("DEMO.md",))
            second = manager.tasks.create("Bob edits DEMO.md", paths=(r".\DEMO.md",))
            manager.assign(first.id, "alice", "edit section A")
            manager.assign(second.id, "bob", "edit section B")
            waited = manager.wait_tasks((first.id, second.id), 5)
            self.assertTrue(waited["completed"])
            deadline = time.time() + 2
            while time.time() < deadline and any(item.status != "idle" for item in manager.members()):
                time.sleep(0.02)

            integration = IntegrationManager(manager)
            record = integration.start()
            self.assertEqual("ready", record.status)
            published = integration.publish()
            self.assertEqual("published", published.status)
            final = (repo / "DEMO.md").read_text(encoding="utf-8")
            self.assertIn("Alice updated", final)
            self.assertIn("Bob updated", final)
            self.assertEqual("keep me\n", (repo / "unrelated.txt").read_text(encoding="utf-8"))
            self.assertEqual("", git(repo, "status", "--porcelain", "--untracked-files=no"))
            manager.close()


if __name__ == "__main__":
    unittest.main()
