import tempfile
import unittest
from pathlib import Path

from huicode.config import LLMConfig, SubagentConfig
from huicode.permissions import PermissionContext
from huicode.prompts import PromptBundle, PromptModule
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


class RecordingProvider:
    name = "fake"
    model = "main"

    def __init__(self, responses):  # noqa: ANN001
        self.responses = list(responses)
        self.calls = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
        self.calls.append({"messages": list(messages), "tools": list(tools or []), "prompt": prompt})
        yield from self.responses.pop(0)


class DefinedContextTests(unittest.TestCase):
    def test_defined_starts_clean_and_keeps_role_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            catalog, registry = _catalog(base)
            provider = RecordingProvider([[StreamEvent("text", text="done")]])
            runner = IsolatedSubagentRunner(
                provider=provider,
                registry=registry,
                context=ToolContext(base),
                config=LLMConfig("openai", "main", "https://example.test", "secret"),
                catalog=catalog,
            )
            parent = _parent(base, messages=(ConversationMessage("user", "private parent"),))
            task = SubagentTask("task-one", "defined", "worker", "inspect")
            result = runner(SubagentLaunchRequest("defined", "inspect", "worker", False, parent), task)
        self.assertEqual(result.status, "completed")
        self.assertEqual([message.content for message in provider.calls[0]["messages"]], ["inspect"])
        self.assertNotIn("private parent", provider.calls[0]["prompt"].system_texts())
        self.assertIn("ROLE BODY", provider.calls[0]["prompt"].dynamic_text())
        self.assertEqual({tool.name for tool in provider.calls[0]["tools"]}, {"Read", "Find"})


class ForkCacheTests(unittest.TestCase):
    def test_fork_uses_safe_history_stable_prefix_and_background_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            catalog, registry = _catalog(base)
            provider = RecordingProvider(
                [[StreamEvent("usage", usage={"cache_read_input_tokens": 8}), StreamEvent("text", text="forked")]]
            )
            runner = IsolatedSubagentRunner(
                provider=provider,
                registry=registry,
                context=ToolContext(base),
                config=LLMConfig("openai", "main", "https://example.test", "secret"),
                catalog=catalog,
            )
            pending = ToolCall("pending", "Read", {"path": "x"})
            stable = (PromptModule("stable", "EXACT PREFIX"),)
            parent = _parent(
                base,
                messages=(
                    ConversationMessage("user", "parent"),
                    ConversationMessage("assistant", "", tool_calls=[pending]),
                ),
                prompt=PromptBundle(stable_modules=stable),
                tools=("Read", "Write", "Bash"),
            )
            task = SubagentTask("task-fork", "fork", None, "fork task", background=True)
            task.background_event.set()
            result = runner(SubagentLaunchRequest("fork", "fork task", None, True, parent), task)
        self.assertEqual(result.status, "completed")
        self.assertEqual(provider.calls[0]["prompt"].stable_modules, stable)
        self.assertEqual([message.content for message in provider.calls[0]["messages"]], ["parent", "fork task"])
        self.assertEqual({tool.name for tool in provider.calls[0]["tools"]}, {"Read"})
        self.assertEqual(result.usage["cache_read_input_tokens"], 8)


def _catalog(base: Path):
    registry = create_default_registry(base)
    root = base / "agents"
    root.mkdir()
    (root / "worker.md").write_text(
        """---
name: worker
description: worker
allowed_tools: [Read, Find]
denied_tools: []
model: inherit
max_iterations: 5
permission_mode: strict
---
ROLE BODY
""",
        encoding="utf-8",
    )
    catalog = AgentCatalog(
        {"plugin": (), "builtin": (), "user": (), "project": (root,)},
        registry,
        SubagentConfig(),
    )
    catalog.initialize()
    return catalog, registry


def _parent(base: Path, *, messages=(), prompt=None, tools=("Read", "Find")):  # noqa: ANN001
    return ParentAgentSnapshot(
        tuple(messages),
        prompt or PromptBundle(),
        tuple(tools),
        "chat",
        PermissionSnapshot(PermissionContext(base)),
        project_instructions="PROJECT RULES",
    )


if __name__ == "__main__":
    unittest.main()
