import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from huicode.cli import _run_chat
from huicode.config import LLMConfig, MemoryConfig
from huicode.memory.codec import message_to_json
from huicode.providers.base import ConversationMessage, StreamEvent


class FakeProvider:
    name = "fake"
    model = "fake"

    def __init__(self) -> None:
        self.calls = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
        self.calls.append({"messages": list(messages), "allow_tool_calls": allow_tool_calls, "prompt": prompt})
        if not allow_tool_calls:
            yield StreamEvent(kind="text", text='{"operations":[{"action":"noop"}]}')
            return
        yield StreamEvent(kind="text", text="ok")


class CLIMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_cwd = Path.cwd()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def test_memory_status_sessions_and_clear(self) -> None:
        provider = FakeProvider()
        config = LLMConfig(
            "openai",
            "fake",
            "https://example.test",
            "secret-api-key",
            memory=MemoryConfig(enabled=True, auto_update=False),
        )
        output = io.StringIO()
        with patch.dict("os.environ", {"HUICODE_HOME": str(self.root / "home")}):
            with patch("builtins.input", side_effect=["hello", "/memory", "/sessions", "/clear", "/memory", "/exit"]):
                with redirect_stdout(output):
                    exit_code = _run_chat(provider, config)

        text = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("memory enabled=true", text)
        self.assertIn("sessions:", text)
        self.assertNotIn("secret-api-key", text)
        sessions = list((self.root / ".huicode" / "sessions").glob("*.jsonl"))
        self.assertGreaterEqual(len(sessions), 1)

    def test_resume_restores_session_before_next_request(self) -> None:
        session_id = "20260709-010101-abcd"
        session_dir = self.root / ".huicode" / "sessions"
        session_dir.mkdir(parents=True)
        record = {
            "type": "message",
            "session_id": session_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "message": message_to_json(ConversationMessage(role="user", content="old question")),
        }
        (session_dir / f"{session_id}.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        provider = FakeProvider()
        config = LLMConfig(
            "openai",
            "fake",
            "https://example.test",
            "key",
            memory=MemoryConfig(enabled=True, auto_update=False),
        )

        output = io.StringIO()
        with patch.dict("os.environ", {"HUICODE_HOME": str(self.root / "home")}):
            with patch("builtins.input", side_effect=[f"/resume {session_id}", "follow up", "/exit"]):
                with redirect_stdout(output):
                    exit_code = _run_chat(provider, config)

        self.assertEqual(exit_code, 0)
        self.assertIn("已恢复会话", output.getvalue())
        self.assertEqual(provider.calls[0]["messages"][0].content, "old question")
        self.assertEqual(provider.calls[0]["messages"][-1].content, "follow up")

    def test_bare_resume_lists_sessions_without_calling_provider(self) -> None:
        session_id = "20260709-010101-list"
        session_dir = self.root / ".huicode" / "sessions"
        session_dir.mkdir(parents=True)
        record = {
            "type": "message",
            "session_id": session_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "message": message_to_json(ConversationMessage(role="user", content="listed session")),
        }
        (session_dir / f"{session_id}.jsonl").write_text(
            json.dumps(record, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        provider = FakeProvider()
        config = LLMConfig(
            "openai",
            "fake",
            "https://example.test",
            "key",
            memory=MemoryConfig(enabled=True, auto_update=False),
        )

        output = io.StringIO()
        with patch.dict("os.environ", {"HUICODE_HOME": str(self.root / "home")}):
            with patch("builtins.input", side_effect=["/resume", "/exit"]):
                with redirect_stdout(output):
                    exit_code = _run_chat(provider, config)

        self.assertEqual(exit_code, 0)
        self.assertIn(session_id, output.getvalue())
        self.assertIn("/resume <session-id>", output.getvalue())
        self.assertEqual(provider.calls, [])

    def test_memory_update_and_rebuild_commands(self) -> None:
        provider = FakeProvider()
        config = LLMConfig(
            "openai",
            "fake",
            "https://example.test",
            "key",
            memory=MemoryConfig(enabled=True, auto_update=False),
        )
        output = io.StringIO()
        with patch.dict("os.environ", {"HUICODE_HOME": str(self.root / "home")}):
            with patch("builtins.input", side_effect=["hello", "/memory update", "/memory rebuild", "/exit"]):
                with redirect_stdout(output):
                    exit_code = _run_chat(provider, config)

        text = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("没有需要更新的记忆", text)
        self.assertIn("记忆索引已重建", text)


if __name__ == "__main__":
    unittest.main()
