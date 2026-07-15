import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from huicode.cli import _run_chat
from huicode.config import LLMConfig
from huicode.providers.base import StreamEvent, ToolCall


class RecordingProvider:
    name = "fake"
    model = "fake"

    def __init__(self, responses=None):
        self.responses = list(responses or [[StreamEvent(kind="text", text="done")]])
        self.calls = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
        self.calls.append({"messages": list(messages), "prompt": prompt})
        yield from self.responses.pop(0)


class CLIHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_cwd = Path.cwd()
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        os.chdir(self.workspace)

    def tearDown(self) -> None:
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def test_start_end_summary_status_and_manual_compact_events(self) -> None:
        hooks = [
            {"id": "start", "event": "session_start", "action": {"type": "subagent", "task": "start"}},
            {"id": "before", "event": "context_before_compact", "action": {"type": "subagent", "task": "before"}},
            {"id": "after", "event": "context_after_compact", "action": {"type": "subagent", "task": "after"}},
            {"id": "end", "event": "session_end", "action": {"type": "subagent", "task": "end"}},
        ]
        output = io.StringIO()
        with patch("builtins.input", side_effect=["/compact", "/status", "/exit"]), redirect_stdout(output):
            code = _run_chat(
                RecordingProvider(),
                LLMConfig("openai", "fake", "https://example.test", "key", hooks=hooks),
            )
        self.assertEqual(code, 0)
        text = output.getvalue()
        self.assertIn("Hooks effective=4", text)
        self.assertIn("hooks: effective=4", text)
        records = [
            json.loads(line)
            for line in (self.workspace / ".huicode" / "logs" / "hooks.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([record["event"] for record in records], [
            "session_start",
            "context_before_compact",
            "context_after_compact",
            "session_end",
        ])

    def test_inline_tool_before_denial_avoids_permission_prompt(self) -> None:
        deny_script = "import sys; print('project hook denied', file=sys.stderr); raise SystemExit(2)"
        hooks = [
            {
                "id": "deny-write",
                "event": "tool_before",
                "if": {"all": [{"field": "tool.name", "exact": "Write"}]},
                "action": {"type": "command", "command": sys.executable, "args": ["-c", deny_script]},
            }
        ]
        provider = RecordingProvider(
            [
                [StreamEvent(kind="tool_call", tool_call=ToolCall("call-1", "Write", {"path": "x.txt", "content": "x"}))],
                [StreamEvent(kind="text", text="blocked and continued")],
            ]
        )
        output = io.StringIO()
        with patch("builtins.input", side_effect=["write file", "/exit"]), redirect_stdout(output):
            code = _run_chat(
                provider,
                LLMConfig("openai", "fake", "https://example.test", "key", hooks=hooks),
            )
        self.assertEqual(code, 0)
        self.assertFalse((self.workspace / "x.txt").exists())
        self.assertNotIn("权限确认", output.getvalue())
        self.assertIn("blocked and continued", output.getvalue())
        tool_result = provider.calls[1]["messages"][2].tool_result
        self.assertEqual(tool_result.error.code, "hook_denied")

    def test_invalid_hook_configuration_returns_two(self) -> None:
        output = io.StringIO()
        hooks = [{"id": "bad", "event": "unknown", "action": {"type": "command", "command": "echo"}}]
        with redirect_stdout(output):
            code = _run_chat(
                RecordingProvider(),
                LLMConfig("openai", "fake", "https://example.test", "key", hooks=hooks),
            )
        self.assertEqual(code, 2)
        self.assertIn("Hook 配置错误", output.getvalue())

    def test_duplicate_inline_ids_report_rule_source_and_reason(self) -> None:
        output = io.StringIO()
        hooks = [
            {"id": "same", "event": "turn_start", "action": {"type": "command", "command": "echo"}},
            {"id": "same", "event": "turn_end", "action": {"type": "command", "command": "echo"}},
        ]
        with redirect_stdout(output):
            code = _run_chat(
                RecordingProvider(),
                LLMConfig("openai", "fake", "https://example.test", "key", hooks=hooks),
            )
        text = output.getvalue()
        self.assertEqual(code, 2)
        self.assertIn("same", text)
        self.assertIn("huicode.yaml", text)
        self.assertIn("重复 id", text)

    def test_eof_triggers_session_end_once(self) -> None:
        hooks = [{"id": "end", "event": "session_end", "action": {"type": "subagent", "task": "end"}}]
        with patch("builtins.input", side_effect=EOFError), redirect_stdout(io.StringIO()):
            code = _run_chat(
                RecordingProvider(),
                LLMConfig("openai", "fake", "https://example.test", "key", hooks=hooks),
            )
        records = [
            json.loads(line)
            for line in (self.workspace / ".huicode" / "logs" / "hooks.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(code, 0)
        self.assertEqual([record["event"] for record in records], ["session_end"])


if __name__ == "__main__":
    unittest.main()
