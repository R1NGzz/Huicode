import io
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from huicode.cli import _run_chat
from huicode.config import LLMConfig
from huicode.providers.base import StreamEvent, ToolCall


class ScriptedProvider:
    name = "fake"
    model = "main"

    def __init__(self) -> None:
        self._responses = [
            [
                StreamEvent(
                    "tool_call",
                    tool_call=ToolCall(
                        "agent-1",
                        "Agent",
                        {"type": "defined", "role": "explorer", "task": "检查入口"},
                    ),
                )
            ],
            [StreamEvent("usage", usage={"input_tokens": 10, "output_tokens": 4}), StreamEvent("text", text="入口是 huicode/__main__.py")],
            [StreamEvent("text", text="已完成委派")],
        ]
        self.calls = []
        self._lock = threading.Lock()

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
        with self._lock:
            self.calls.append({"messages": list(messages), "tools": list(tools or []), "prompt": prompt})
            response = self._responses.pop(0)
        yield from response


class SubagentCLIE2ETests(unittest.TestCase):
    def test_defined_foreground_runs_to_completion_and_tasks_are_visible(self) -> None:
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                provider = ScriptedProvider()
                output = io.StringIO()
                config = LLMConfig("openai", "main", "https://example.test", "secret")
                with patch("builtins.input", side_effect=["委派调查", "/tasks", "/exit"]), redirect_stdout(output):
                    code = _run_chat(provider, config)
            finally:
                os.chdir(old_cwd)
        text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertEqual(len(provider.calls), 3)
        self.assertIn("Agents effective=3", text)
        self.assertIn("task-", text)
        self.assertIn("completed/defined", text)
        child_tools = {tool.name for tool in provider.calls[1]["tools"]}
        self.assertEqual(child_tools, {"Read", "Find", "Search"})
        self.assertIn("入口是 huicode/__main__.py", provider.calls[2]["messages"][-1].tool_result.data["summary"])

    def test_fork_completion_does_not_trigger_an_extra_provider_call(self) -> None:
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                provider = RoutingForkProvider()
                output = io.StringIO()
                config = LLMConfig("openai", "main", "https://example.test", "secret")
                inputs = iter(["启动 Fork", "/tasks", "/exit"])

                def read_input(prompt=""):  # noqa: ANN001
                    value = next(inputs)
                    if value == "/tasks":
                        time.sleep(0.2)
                    return value

                with patch("builtins.input", side_effect=read_input), redirect_stdout(output):
                    code = _run_chat(provider, config)
            finally:
                os.chdir(old_cwd)
        self.assertEqual(code, 0)
        self.assertEqual(len(provider.calls), 3)
        self.assertIn("completed/fork", output.getvalue())
        self.assertIn("fork background result", output.getvalue())


class RoutingForkProvider:
    name = "fake"
    model = "main"

    def __init__(self) -> None:
        self.calls = []
        self._lock = threading.Lock()

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
        with self._lock:
            self.calls.append({"messages": list(messages), "tools": list(tools or []), "prompt": prompt})
        last = messages[-1]
        if last.role == "user" and last.content == "启动 Fork":
            yield StreamEvent(
                "tool_call",
                tool_call=ToolCall("fork-1", "Agent", {"type": "fork", "task": "fork work"}),
            )
            return
        if last.role == "user" and last.content == "fork work":
            time.sleep(0.05)
            yield StreamEvent("text", text="fork background result")
            return
        yield StreamEvent("text", text="主任务已提交")


if __name__ == "__main__":
    unittest.main()
