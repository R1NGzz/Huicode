from __future__ import annotations

import tempfile
import unittest
import time
import subprocess
from pathlib import Path

from huicode.subagents.parser import AgentValidationError, parse_agent_file
from huicode.config import LLMConfig, SubagentConfig
from huicode.config import WorktreeConfig
from huicode.permissions import PermissionContext
from huicode.prompts import PromptBundle
from huicode.providers.base import ConversationMessage, StreamEvent, ToolCall
from huicode.subagents.catalog import AgentCatalog
from huicode.subagents.runner import IsolatedSubagentRunner
from huicode.subagents.types import (
    ParentAgentSnapshot,
    PermissionSnapshot,
    SubagentLaunchRequest,
    SubagentTask,
)
from huicode.tools.base import ToolContext
from huicode.tools.registry import create_default_registry
from huicode.worktrees.types import WorktreeDisposition, WorktreeHandle, WorktreeIdentity
from huicode.worktrees.manager import WorktreeManager


class SubagentWorktreeTests(unittest.TestCase):
    def write_role(self, root: Path, isolation: str) -> Path:
        path = root / "role.md"
        path.write_text(
            "\n".join(
                [
                    "---",
                    "name: role",
                    "description: role",
                    "allowed_tools: [Read]",
                    "denied_tools: []",
                    "model: inherit",
                    "max_iterations: 5",
                    "permission_mode: default",
                    f"isolation: {isolation}",
                    "---",
                    "Do the task.",
                ]
            ),
            encoding="utf-8",
        )
        return path

    def test_role_parses_worktree_and_rejects_unknown_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            definition = parse_agent_file(self.write_role(root, "worktree"), "project")
            self.assertEqual(definition.isolation, "worktree")
            with self.assertRaises(AgentValidationError):
                parse_agent_file(self.write_role(root, "container"), "project")

    def test_runner_reads_from_worktree_and_returns_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "isolated"
            target.mkdir()
            (target / "value.txt").write_text("isolated-value", encoding="utf-8")
            registry = create_default_registry(root)
            roles = root / "roles"
            roles.mkdir()
            self.write_role(roles, "worktree")
            catalog = AgentCatalog(
                {"plugin": (), "builtin": (), "user": (), "project": (roles,)},
                registry,
                SubagentConfig(),
            )
            catalog.initialize()
            provider = RecordingProvider(
                [
                    [StreamEvent("tool_call", tool_call=ToolCall("call-1", "Read", {"path": "value.txt"}))],
                    [StreamEvent("text", text="done")],
                ]
            )
            manager = FakeWorktreeManager(target)
            runner = IsolatedSubagentRunner(
                provider=provider,
                registry=registry,
                context=ToolContext(root),
                config=LLMConfig("openai", "main", "https://example.test", "secret"),
                catalog=catalog,
                worktree_manager=manager,  # type: ignore[arg-type]
            )
            parent = ParentAgentSnapshot(
                (), PromptBundle(), ("Read",), "chat", PermissionSnapshot(PermissionContext(root))
            )
            task = SubagentTask("task-1234abcd", "defined", "role", "read")
            result = runner(SubagentLaunchRequest("defined", "read", "role", False, parent), task)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.worktree_state, "retained")
        self.assertEqual(result.worktree_path, str(target))
        self.assertEqual(manager.finalized, "completed")
        tool_message = provider.calls[1]["messages"][2]
        self.assertIn("isolated-value", tool_message.tool_result.data["content"])
        self.assertIn(str(target), provider.calls[0]["prompt"].dynamic_text())

    def test_real_git_worktree_write_does_not_modify_main_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _git(root, "init")
            _git(root, "config", "user.name", "HuiCode Tests")
            _git(root, "config", "user.email", "huicode@example.invalid")
            (root / ".gitignore").write_text(".huicode/\n", encoding="utf-8")
            (root / "base.txt").write_text("main", encoding="utf-8")
            _git(root, "add", ".")
            _git(root, "commit", "-m", "base")
            registry = create_default_registry(root)
            roles = root / ".huicode" / "agents"
            roles.mkdir(parents=True)
            role = self.write_role(roles, "worktree")
            role.write_text(role.read_text(encoding="utf-8").replace("allowed_tools: [Read]", "allowed_tools: [Write]").replace("permission_mode: default", "permission_mode: permissive"), encoding="utf-8")
            catalog = AgentCatalog(
                {"plugin": (), "builtin": (), "user": (), "project": (roles,)},
                registry,
                SubagentConfig(),
            )
            catalog.initialize()
            provider = RecordingProvider(
                [
                    [StreamEvent("tool_call", tool_call=ToolCall("call-1", "Write", {"path": "result.txt", "content": "isolated"}))],
                    [StreamEvent("text", text="done")],
                ]
            )
            manager = WorktreeManager(root, WorktreeConfig(copy_files=()))
            runner = IsolatedSubagentRunner(
                provider=provider,
                registry=registry,
                context=ToolContext(root),
                config=LLMConfig("openai", "main", "https://example.test", "secret"),
                catalog=catalog,
                worktree_manager=manager,
            )
            parent = ParentAgentSnapshot(
                (),
                PromptBundle(),
                ("Write",),
                "chat",
                PermissionSnapshot(PermissionContext(root, mode="permissive")),
            )
            task = SubagentTask("task-1234abcd", "defined", "role", "write")
            result = runner(SubagentLaunchRequest("defined", "write", "role", False, parent), task)
            isolated_path = Path(result.worktree_path)
            self.assertFalse((root / "result.txt").exists())
            self.assertEqual((isolated_path / "result.txt").read_text(encoding="utf-8"), "isolated")
            self.assertEqual(result.worktree_state, "retained")
            self.assertIn("未提交", result.worktree_reason)
            manager._backend().rollback_create(isolated_path, result.worktree_branch)


class RecordingProvider:
    name = "fake"
    model = "main"

    def __init__(self, responses):  # noqa: ANN001
        self.responses = list(responses)
        self.calls = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
        self.calls.append({"messages": list(messages), "tools": list(tools or []), "prompt": prompt})
        yield from self.responses.pop(0)


class FakeWorktreeManager:
    def __init__(self, path: Path) -> None:
        identity = WorktreeIdentity(
            "repo", "task-1234abcd", "role", "a" * 40, "branch", path, time.time()
        )
        self.handle = WorktreeHandle(identity)
        self.finalized = ""

    def prepare(self, task_id: str, logical_name: str) -> WorktreeHandle:
        self.assertions = (task_id, logical_name)
        return self.handle

    def enter(self, handle: WorktreeHandle) -> Path:
        return handle.path

    def exit(self, handle: WorktreeHandle) -> None:
        return None

    def finalize(self, handle: WorktreeHandle, status: str) -> WorktreeDisposition:
        self.finalized = status
        return WorktreeDisposition("retained", "test")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
