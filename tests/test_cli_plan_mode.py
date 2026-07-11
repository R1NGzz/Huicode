import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from huicode.cli import _run_chat
from huicode.config import LLMConfig
from huicode.providers.base import ConversationMessage, StreamEvent, ToolSpec


class InspectableProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def stream_chat(self, messages: list[ConversationMessage], tools=None, allow_tool_calls=True, prompt=None):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools or []),
                "allow_tool_calls": allow_tool_calls,
                "prompt": prompt,
            }
        )
        if len(self.calls) == 1:
            yield StreamEvent(kind="text", text="先读入口文件，再确认参数流向。")
        else:
            yield StreamEvent(kind="text", text="开始执行。")


class CLIPlanModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_cwd = Path.cwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)
        self.config = LLMConfig("openai", "fake-model", "https://example.test/v1", "secret-api-key")

    def tearDown(self) -> None:
        os.chdir(self._old_cwd)
        self._tmpdir.cleanup()

    def test_plan_command_filters_to_read_only_tools(self) -> None:
        provider = InspectableProvider()
        output = io.StringIO()
        with patch("builtins.input", side_effect=["/plan", "帮我分析入口文件", "/exit"]), redirect_stdout(output):
            exit_code = _run_chat(provider, self.config)

        self.assertEqual(exit_code, 0)
        tool_names = {tool.name for tool in provider.calls[0]["tools"]}
        self.assertEqual(tool_names, {"Read", "Find", "Search"})

    def test_do_returns_to_default_without_injecting_recent_plan(self) -> None:
        provider = InspectableProvider()
        output = io.StringIO()
        with patch(
            "builtins.input",
            side_effect=["/plan", "先做计划", "/do", "执行下一步", "/exit"],
        ), redirect_stdout(output):
            exit_code = _run_chat(provider, self.config)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[1]["messages"][-1].content, "执行下一步")
        tool_names = {tool.name for tool in provider.calls[1]["tools"]}
        self.assertTrue({"Read", "Write", "Edit", "Bash", "Find", "Search"}.issubset(tool_names))
        self.assertIn("已返回 [DEFAULT]", output.getvalue())

    def test_plan_without_inline_task_uses_next_input(self) -> None:
        provider = InspectableProvider()
        output = io.StringIO()
        with patch("builtins.input", side_effect=["/plan", "分析一下 CLI 入口", "/exit"]), redirect_stdout(output):
            exit_code = _run_chat(provider, self.config)

        self.assertEqual(exit_code, 0)
        self.assertEqual(provider.calls[0]["messages"][-1].content, "分析一下 CLI 入口")
        self.assertEqual({tool.name for tool in provider.calls[0]["tools"]}, {"Read", "Find", "Search"})

    def test_clear_resets_mode_to_default(self) -> None:
        provider = InspectableProvider()
        output = io.StringIO()
        with patch(
            "builtins.input",
            side_effect=["/plan", "/clear", "普通请求", "/exit"],
        ), redirect_stdout(output):
            exit_code = _run_chat(provider, self.config)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(provider.calls), 1)
        tool_names = {tool.name for tool in provider.calls[0]["tools"]}
        self.assertIn("Write", tool_names)
        self.assertIn("已开启新会话", output.getvalue())


if __name__ == "__main__":
    unittest.main()
