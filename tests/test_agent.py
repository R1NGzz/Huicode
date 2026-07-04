import io
import tempfile
import unittest
from pathlib import Path

from huicode.agent import run_agent_turn
from huicode.config import LLMConfig
from huicode.providers.base import ConversationMessage, StreamEvent, ToolCall
from huicode.tools.base import ToolContext
from huicode.tools.registry import create_default_registry


class ScriptedProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, turns: list[list[StreamEvent]]) -> None:
        self.turns = turns
        self.calls: list[dict[str, object]] = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools or []),
                "allow_tool_calls": allow_tool_calls,
                "prompt": prompt,
            }
        )
        yield from self.turns.pop(0)


class AgentTests(unittest.TestCase):
    def test_text_only_turn(self) -> None:
        provider = ScriptedProvider([[StreamEvent(kind="text", text="你好")]])
        messages: list[ConversationMessage] = []
        output = io.StringIO()

        ok = run_agent_turn(
            provider,
            create_default_registry(Path.cwd()),
            ToolContext(workspace=Path.cwd()),
            messages,
            "打招呼",
            LLMConfig("openai", "fake", "https://example.test", "key"),
            output,
        )

        self.assertTrue(ok)
        self.assertEqual([message.role for message in messages], ["user", "assistant"])
        self.assertEqual(messages[-1].content, "你好")

    def test_one_tool_turn_backfills_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "a.txt").write_text("hello", encoding="utf-8")
            provider = ScriptedProvider(
                [
                    [StreamEvent(kind="tool_call", tool_call=ToolCall("call_1", "Read", {"path": "a.txt"}))],
                    [StreamEvent(kind="text", text="文件内容是 hello")],
                ]
            )
            messages: list[ConversationMessage] = []
            output = io.StringIO()

            ok = run_agent_turn(
                provider,
                create_default_registry(workspace),
                ToolContext(workspace=workspace),
                messages,
                "读文件",
                LLMConfig("openai", "fake", "https://example.test", "key"),
                output,
            )

        self.assertTrue(ok)
        self.assertEqual([message.role for message in messages], ["user", "assistant", "tool", "assistant"])
        self.assertEqual(messages[1].tool_calls[0].name, "Read")
        self.assertTrue(messages[2].tool_result.ok)
        self.assertIn("✓ Read(a.txt)", output.getvalue())
        self.assertIn("文件内容是 hello", messages[-1].content)

    def test_large_tool_result_is_spilled_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "large.txt").write_text("x" * 5000, encoding="utf-8")
            provider = ScriptedProvider(
                [
                    [StreamEvent(kind="tool_call", tool_call=ToolCall("call_1", "Read", {"path": "large.txt"}))],
                    [StreamEvent(kind="text", text="已读取")],
                ]
            )
            messages: list[ConversationMessage] = []
            output = io.StringIO()

            ok = run_agent_turn(
                provider,
                create_default_registry(workspace),
                ToolContext(workspace=workspace),
                messages,
                "读大文件",
                LLMConfig("openai", "fake", "https://example.test", "key"),
                output,
            )

            spilled = messages[2].tool_result.data["__spilled__"]
            spill_path = workspace / spilled["path"]

            self.assertTrue(ok)
            self.assertTrue(spill_path.is_file())
            self.assertIn("content", spill_path.read_text(encoding="utf-8"))
            self.assertIn("spilled 1 tool result(s) to disk", output.getvalue())

    def test_thinking_is_preserved_for_tool_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "a.txt").write_text("hello", encoding="utf-8")
            provider = ScriptedProvider(
                [
                    [
                        StreamEvent(kind="thinking", text="我需要读文件"),
                        StreamEvent(kind="thinking", text="", thinking_signature="sig-1"),
                        StreamEvent(kind="tool_call", tool_call=ToolCall("call_1", "Read", {"path": "a.txt"})),
                    ],
                    [StreamEvent(kind="text", text="完成")],
                ]
            )
            messages: list[ConversationMessage] = []

            run_agent_turn(
                provider,
                create_default_registry(workspace),
                ToolContext(workspace=workspace),
                messages,
                "读文件",
                LLMConfig("anthropic", "fake", "https://example.test", "key"),
                io.StringIO(),
            )

        self.assertEqual(messages[1].role, "assistant")
        self.assertEqual(messages[1].thinking, "我需要读文件")
        self.assertEqual(messages[1].thinking_signature, "sig-1")
        self.assertEqual(messages[1].tool_calls[0].name, "Read")

    def test_second_tool_call_runs_in_next_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "a.txt").write_text("hello", encoding="utf-8")
            provider = ScriptedProvider(
                [
                    [StreamEvent(kind="tool_call", tool_call=ToolCall("call_1", "Read", {"path": "a.txt"}))],
                    [StreamEvent(kind="tool_call", tool_call=ToolCall("call_2", "Read", {"path": "a.txt"}))],
                    [StreamEvent(kind="text", text="完成")],
                ]
            )
            messages: list[ConversationMessage] = []
            output = io.StringIO()

            run_agent_turn(
                provider,
                create_default_registry(workspace),
                ToolContext(workspace=workspace),
                messages,
                "读两次",
                LLMConfig("openai", "fake", "https://example.test", "key"),
                output,
            )

        self.assertEqual(
            [message.role for message in messages],
            ["user", "assistant", "tool", "assistant", "tool", "assistant"],
        )
        self.assertEqual(output.getvalue().count("✓ Read(a.txt)"), 2)
        self.assertEqual(messages[-1].content, "完成")


if __name__ == "__main__":
    unittest.main()
