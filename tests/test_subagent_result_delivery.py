import tempfile
import time
import unittest
from pathlib import Path

from huicode.agent import run_agent_loop
from huicode.agent_events import AgentOptions, AgentState
from huicode.config import LLMConfig, SubagentConfig
from huicode.permissions import PermissionContext
from huicode.prompts import PromptBundle
from huicode.providers.base import StreamEvent
from huicode.subagents.catalog import AgentCatalog
from huicode.subagents.manager import SubagentManager
from huicode.subagents.types import (
    ParentAgentSnapshot,
    PermissionSnapshot,
    SubagentLaunchRequest,
    SubagentResult,
)
from huicode.tools.base import ToolContext
from huicode.tools.registry import create_default_registry


class Provider:
    name = "fake"
    model = "main"

    def __init__(self, response):  # noqa: ANN001
        self.response = response
        self.calls = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
        self.calls.append({"messages": list(messages), "prompt": prompt})
        if isinstance(self.response, Exception):
            raise self.response
        yield from self.response


class ResultDeliveryTests(unittest.TestCase):
    def test_failed_request_releases_and_success_consumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            registry = create_default_registry(base)
            catalog = AgentCatalog(
                {name: () for name in ("plugin", "builtin", "user", "project")},
                registry,
                SubagentConfig(),
            )
            catalog.initialize()
            manager = SubagentManager(
                catalog,
                SubagentConfig(),
                lambda request, task: SubagentResult(task.id, "completed", "BACKGROUND RESULT", "final"),
            )
            parent = ParentAgentSnapshot(
                (), PromptBundle(), ("Read",), "chat", PermissionSnapshot(PermissionContext(base))
            )
            task = manager.submit(SubagentLaunchRequest("fork", "x", None, True, parent))
            _wait(lambda: manager.task_detail(task.id).status == "completed")
            state = AgentState()
            failure = Provider(RuntimeError("offline"))
            list(
                run_agent_loop(
                    failure, registry, ToolContext(base), state, "first",
                    LLMConfig("openai", "main", "https://example.test", "secret"),
                    AgentOptions(), subagent_manager=manager,
                )
            )
            self.assertEqual(manager.summary()["ready"], 1)
            success = Provider([StreamEvent("text", text="used")])
            list(
                run_agent_loop(
                    success, registry, ToolContext(base), state, "retry",
                    LLMConfig("openai", "main", "https://example.test", "secret"),
                    AgentOptions(), subagent_manager=manager,
                )
            )
            self.assertIn("BACKGROUND RESULT", success.calls[0]["prompt"].dynamic_text())
            self.assertEqual(manager.summary()["ready"], 0)
            self.assertFalse(any(message.content == "BACKGROUND RESULT" for message in state.messages))
            manager.close()


def _wait(predicate, timeout=2):  # noqa: ANN001
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


if __name__ == "__main__":
    unittest.main()
