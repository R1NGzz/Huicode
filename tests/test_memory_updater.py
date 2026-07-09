import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huicode.config import LLMConfig, MemoryConfig
from huicode.memory.notes import NoteStore
from huicode.memory.updater import MemoryUpdater
from huicode.providers.base import ConversationMessage, StreamEvent, ToolCall


class FakeMemoryProvider:
    name = "fake"
    model = "fake"

    def __init__(self, events) -> None:
        self.events = events
        self.calls = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
        self.calls.append({"messages": messages, "tools": tools, "allow_tool_calls": allow_tool_calls})
        yield from self.events


class MemoryUpdaterTests(unittest.TestCase):
    def test_creates_note_and_disables_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "work"
            home = Path(directory) / "home"
            provider = FakeMemoryProvider(
                [
                    StreamEvent(
                        kind="text",
                        text=(
                            '{"operations":[{"action":"create","scope":"project",'
                            '"category":"project_knowledge","title":"Stack",'
                            '"summary":"Uses unittest","body":"The project uses unittest."}]}'
                        ),
                    )
                ]
            )
            with patch.dict("os.environ", {"HUICODE_HOME": str(home)}):
                updater = MemoryUpdater(
                    workspace,
                    MemoryConfig(enabled=True),
                    LLMConfig("openai", "fake", "https://example.test", "key"),
                )
                report = updater.update_from_turn(
                    provider,
                    "20260709-010101-abcd",
                    "chat",
                    [ConversationMessage(role="user", content="remember unittest")],
                    "",
                )
                notes = NoteStore(workspace).list_notes("project")

        self.assertTrue(report.ok)
        self.assertEqual(report.created, 1)
        self.assertFalse(provider.calls[0]["allow_tool_calls"])
        self.assertEqual(provider.calls[0]["tools"], [])
        self.assertEqual(notes[0].category, "project_knowledge")

    def test_noop_invalid_json_and_tool_call_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "work"
            config = LLMConfig("openai", "fake", "https://example.test", "key")
            noop = MemoryUpdater(workspace, MemoryConfig(enabled=True), config).update_from_turn(
                FakeMemoryProvider([StreamEvent(kind="text", text='{"operations":[{"action":"noop"}]}')]),
                "s",
                "chat",
                [ConversationMessage(role="user", content="hi")],
                "",
            )
            invalid = MemoryUpdater(workspace, MemoryConfig(enabled=True), config).update_from_turn(
                FakeMemoryProvider([StreamEvent(kind="text", text="not json")]),
                "s",
                "chat",
                [ConversationMessage(role="user", content="hi")],
                "",
            )
            tool = MemoryUpdater(workspace, MemoryConfig(enabled=True), config).update_from_turn(
                FakeMemoryProvider([StreamEvent(kind="tool_call", tool_call=ToolCall("1", "Read", {}))]),
                "s",
                "chat",
                [ConversationMessage(role="user", content="hi")],
                "",
            )

        self.assertTrue(noop.ok)
        self.assertTrue(noop.noop)
        self.assertFalse(invalid.ok)
        self.assertFalse(tool.ok)


if __name__ == "__main__":
    unittest.main()
