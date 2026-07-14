import tempfile
import unittest
from pathlib import Path

from huicode.agent_events import AgentOptions
from huicode.config import LLMConfig
from huicode.providers.base import ConversationMessage, StreamEvent, ToolCall
from huicode.skills.catalog import SkillCatalogBuilder
from huicode.skills.manager import SkillManager
from huicode.skills.runner import SkillRunner, select_protocol_safe_history
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


def isolated_manager(base: Path, history: int = 2, model: str | None = None) -> SkillManager:
    roots = {name: base / name for name in ("builtin", "user", "project")}
    roots["project"].mkdir()
    model_line = f"model: {model}\n" if model else ""
    (roots["project"] / "review.md").write_text(
        f"""---
name: review
description: Review changes
allowed_tools:
  - Read
mode: isolated
history_messages: {history}
{model_line}---
ISOLATED SOP: {{{{args}}}}
""",
        encoding="utf-8",
    )
    registry = create_default_registry(base)
    manager = SkillManager(SkillCatalogBuilder(roots, registry))
    manager.initialize()
    return manager


class SkillRunnerTests(unittest.TestCase):
    def test_history_selection_keeps_complete_tool_group(self) -> None:
        call = ToolCall("call-1", "Read", {"path": "a"})
        messages = [
            ConversationMessage("user", "old"),
            ConversationMessage("assistant", "", tool_calls=[call]),
            ConversationMessage("tool", "result", tool_call_id="call-1", tool_name="Read"),
            ConversationMessage("assistant", "answer"),
        ]

        selected = select_protocol_safe_history(messages, 2)

        self.assertEqual([item.role for item in selected], ["assistant", "tool", "assistant"])
        self.assertEqual(selected[0].tool_calls[0].id, selected[1].tool_call_id)

    def test_incomplete_and_orphan_tool_messages_are_removed(self) -> None:
        messages = [
            ConversationMessage("assistant", "", tool_calls=[ToolCall("missing", "Read", {})]),
            ConversationMessage("tool", "orphan", tool_call_id="other", tool_name="Read"),
            ConversationMessage("user", "latest"),
        ]

        selected = select_protocol_safe_history(messages, 10)

        self.assertEqual(selected, [ConversationMessage("user", "latest")])

    def test_isolated_run_uses_own_state_and_returns_only_final_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manager = isolated_manager(base, history=1)
            registry = create_default_registry(base)
            provider = RecordingProvider([[StreamEvent(kind="thinking", text="private"), StreamEvent(kind="text", text="summary")]])
            parent = [ConversationMessage("user", "parent secret")]
            runner = SkillRunner(
                provider=provider,
                registry=registry,
                context=ToolContext(base),
                config=LLMConfig("openai", "main", "https://example.test", "secret"),
                manager=manager,
                options=AgentOptions(),
            )

            result = runner.run("review", "Focus On API", parent_messages=parent)

        self.assertTrue(result.ok)
        self.assertEqual(result.summary, "summary")
        self.assertEqual(parent, [ConversationMessage("user", "parent secret")])
        dynamic = provider.calls[0]["prompt"].dynamic_text()
        self.assertIn("ISOLATED SOP: Focus On API", dynamic)
        self.assertEqual({tool.name for tool in provider.calls[0]["tools"]}, {"Read", "Skill"})

    def test_iteration_limit_and_depth_limit_are_structured_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manager = isolated_manager(base)
            registry = create_default_registry(base)
            provider = RecordingProvider(
                [[StreamEvent(kind="tool_call", tool_call=ToolCall("read-1", "Read", {"path": "missing"}))]]
            )
            runner = SkillRunner(
                provider=provider,
                registry=registry,
                context=ToolContext(base),
                config=LLMConfig("openai", "main", "https://example.test", "secret"),
                manager=manager,
                options=AgentOptions(max_iterations=1),
            )

            limited = runner.run("review", "x")
            nested = runner.run("review", "x", depth=4)

        self.assertFalse(limited.ok)
        self.assertEqual(limited.stop_reason, "max_iterations")
        self.assertFalse(nested.ok)
        self.assertEqual(nested.stop_reason, "nested_depth_exceeded")
        self.assertEqual(len(provider.calls), 1)

    def test_isolated_model_override_uses_factory_for_whole_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manager = isolated_manager(base, model="review-model")
            registry = create_default_registry(base)
            main = RecordingProvider([])
            alternate = RecordingProvider([[StreamEvent(kind="text", text="done")]])
            alternate.model = "review-model"
            requested = []
            runner = SkillRunner(
                provider=main,
                registry=registry,
                context=ToolContext(base),
                config=LLMConfig("openai", "main", "https://example.test", "secret"),
                manager=manager,
                options=AgentOptions(),
                provider_factory=lambda model: requested.append(model) or alternate,
            )

            result = runner.run("review", "x")

        self.assertTrue(result.ok)
        self.assertEqual(requested, ["review-model"])
        self.assertEqual(len(alternate.calls), 1)
        self.assertEqual(main.calls, [])


if __name__ == "__main__":
    unittest.main()
