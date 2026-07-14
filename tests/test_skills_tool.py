import tempfile
import unittest
from pathlib import Path

from huicode.agent import run_agent_loop
from huicode.agent_events import AgentOptions, AgentState
from huicode.config import LLMConfig
from huicode.providers.base import StreamEvent, ToolCall
from huicode.skills.catalog import SkillCatalogBuilder
from huicode.skills.manager import SkillManager
from huicode.skills.tool import SkillTool
from huicode.tools.base import ToolContext
from huicode.permissions import PermissionContext
from huicode.tools.registry import create_default_registry


class ScriptedProvider:
    name = "fake"
    model = "main-model"

    def __init__(self, events):  # noqa: ANN001
        self.events = list(events)
        self.calls = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
        self.calls.append({"messages": list(messages), "tools": list(tools or []), "prompt": prompt})
        yield from self.events.pop(0)


def build_manager(base: Path, *, model: str | None = None) -> SkillManager:
    roots = {name: base / name for name in ("builtin", "user", "project")}
    roots["project"].mkdir()
    model_line = f"model: {model}\n" if model else ""
    (roots["project"] / "focus.md").write_text(
        f"""---
name: focus
description: Focus on a task
allowed_tools:
  - Read
mode: shared
{model_line}---
FOCUS SOP: {{{{args}}}}
""",
        encoding="utf-8",
    )
    manager = SkillManager(SkillCatalogBuilder(roots, create_default_registry(base)))
    manager.initialize()
    return manager


class SkillToolTests(unittest.TestCase):
    def test_skill_loader_bypasses_plan_and_strict_but_child_tools_do_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            state = AgentState()
            manager = build_manager(base)
            registry = create_default_registry(base)
            registry.register(SkillTool(manager, state.skills), system=True)
            provider = ScriptedProvider(
                [
                    [StreamEvent(kind="tool_call", tool_call=ToolCall("1", "Skill", {"name": "focus"}))],
                    [
                        StreamEvent(
                            kind="tool_call",
                            tool_call=ToolCall("2", "Read", {"path": "README.md"}),
                        )
                    ],
                    [StreamEvent(kind="text", text="done")],
                ]
            )
            permissions = PermissionContext(workspace=base, mode="strict")

            list(
                run_agent_loop(
                    provider,
                    registry,
                    ToolContext(base, permissions=permissions),
                    state,
                    "work",
                    LLMConfig("openai", "main-model", "https://example.test", "secret"),
                    AgentOptions(mode="plan"),
                    skill_manager=manager,
                )
            )

        self.assertIn("focus", state.skills.active)
        read_result = next(
            message.tool_result
            for message in state.messages
            if message.role == "tool" and message.tool_call_id == "2"
        )
        self.assertFalse(read_result.ok)
        self.assertEqual(read_result.error.code, "permission_denied")
    def test_shared_activation_rebuilds_prompt_and_restricts_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            state = AgentState()
            manager = build_manager(base)
            registry = create_default_registry(base)
            registry.register(SkillTool(manager, state.skills), system=True)
            provider = ScriptedProvider(
                [
                    [
                        StreamEvent(
                            kind="tool_call",
                            tool_call=ToolCall(
                                id="skill-1",
                                name="Skill",
                                arguments={"name": "focus", "arguments": "Focus On API"},
                            ),
                        )
                    ],
                    [StreamEvent(kind="text", text="done")],
                ]
            )

            events = list(
                run_agent_loop(
                    provider,
                    registry,
                    ToolContext(base),
                    state,
                    "work",
                    LLMConfig("openai", "main-model", "https://example.test", "secret"),
                    AgentOptions(),
                    skill_manager=manager,
                )
            )

        self.assertEqual(events[-1].stop_reason, "final")
        self.assertEqual(len(provider.calls), 2)
        self.assertNotIn("FOCUS SOP", provider.calls[0]["prompt"].dynamic_text())
        self.assertIn("FOCUS SOP: Focus On API", provider.calls[1]["prompt"].dynamic_text())
        self.assertEqual({tool.name for tool in provider.calls[1]["tools"]}, {"Read", "Skill"})
        self.assertEqual(len(state.skills.active), 1)

    def test_model_override_applies_after_activation_and_is_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            state = AgentState()
            manager = build_manager(base, model="skill-model")
            registry = create_default_registry(base)
            registry.register(SkillTool(manager, state.skills), system=True)
            main = ScriptedProvider(
                [[StreamEvent(kind="tool_call", tool_call=ToolCall("1", "Skill", {"name": "focus"}))]]
            )
            override = ScriptedProvider([[StreamEvent(kind="text", text="done")]])
            override.model = "skill-model"

            list(
                run_agent_loop(
                    main,
                    registry,
                    ToolContext(base),
                    state,
                    "work",
                    LLMConfig("openai", "main-model", "https://example.test", "secret"),
                    AgentOptions(),
                    skill_manager=manager,
                    provider_override_factory=lambda model: override,
                )
            )

        self.assertEqual(len(main.calls), 1)
        self.assertEqual(len(override.calls), 1)
        self.assertIsNone(state.skills.turn_model_override)


if __name__ == "__main__":
    unittest.main()
