import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huicode.agent import run_agent_loop
from huicode.agent_events import AgentOptions, AgentState
from huicode.config import LLMConfig, MemoryConfig
from huicode.memory.manager import MemoryManager
from huicode.providers.base import StreamEvent
from huicode.tools.base import ToolContext
from huicode.tools.registry import create_default_registry


class MemoryAwareProvider:
    name = "fake"
    model = "fake"

    def __init__(self) -> None:
        self.calls = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
        self.calls.append({"messages": list(messages), "allow_tool_calls": allow_tool_calls, "prompt": prompt})
        if not allow_tool_calls:
            yield StreamEvent(
                kind="text",
                text=(
                    '{"operations":[{"action":"create","scope":"project",'
                    '"category":"project_knowledge","title":"Fact",'
                    '"summary":"Remembered fact","body":"Remembered fact body"}]}'
                ),
            )
            return
        yield StreamEvent(kind="text", text="final answer")


class AgentMemoryTests(unittest.TestCase):
    def test_records_messages_and_injects_memory_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "work"
            home = root / "home"
            workspace.mkdir()
            (workspace / ".huicode").mkdir()
            (workspace / ".huicode" / "instructions.md").write_text("项目必须使用中文回答", encoding="utf-8")
            (workspace / ".huicode" / "memory").mkdir()
            (workspace / ".huicode" / "memory" / "index.md").write_text("## Project Knowledge\n- remembered", encoding="utf-8")
            provider = MemoryAwareProvider()
            config = LLMConfig(
                "openai",
                "fake",
                "https://example.test",
                "key",
                memory=MemoryConfig(enabled=True, auto_update=False),
            )
            state = AgentState()
            with patch.dict("os.environ", {"HUICODE_HOME": str(home)}):
                manager = MemoryManager(workspace, config.memory, config, provider, synchronous_updates=True)
                manager.start(state)
                events = list(
                    run_agent_loop(
                        provider=provider,
                        registry=create_default_registry(workspace),
                        context=ToolContext(workspace=workspace),
                        state=state,
                        user_text="hello",
                        config=config,
                        options=AgentOptions(),
                        memory=manager,
                    )
                )
                manager.close()
                session_path = next((workspace / ".huicode" / "sessions").glob("*.jsonl"))
                records = [json.loads(line) for line in session_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(events[-1].stop_reason, "final")
        self.assertEqual([record["message"]["role"] for record in records], ["user", "assistant"])
        prompt = provider.calls[0]["prompt"]
        self.assertIn("项目必须使用中文回答", prompt.stable_text())
        self.assertIn("memory_index", prompt.module_names())
        self.assertIn("remembered", prompt.supplemental_text())

    def test_auto_update_runs_on_final(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "work"
            home = Path(directory) / "home"
            workspace.mkdir()
            provider = MemoryAwareProvider()
            config = LLMConfig(
                "openai",
                "fake",
                "https://example.test",
                "key",
                memory=MemoryConfig(enabled=True, auto_update=True),
            )
            state = AgentState()
            with patch.dict("os.environ", {"HUICODE_HOME": str(home)}):
                manager = MemoryManager(workspace, config.memory, config, provider, synchronous_updates=True)
                manager.start(state)
                events = list(
                    run_agent_loop(
                        provider=provider,
                        registry=create_default_registry(workspace),
                        context=ToolContext(workspace=workspace),
                        state=state,
                        user_text="remember this",
                        config=config,
                        options=AgentOptions(),
                        memory=manager,
                    )
                )
                notes = list((workspace / ".huicode" / "memory" / "notes").glob("*.md"))
                manager.close()

        self.assertIn("memory", [event.kind for event in events])
        self.assertEqual(len(notes), 1)
        self.assertEqual(len(provider.calls), 2)
        self.assertFalse(provider.calls[1]["allow_tool_calls"])


if __name__ == "__main__":
    unittest.main()
