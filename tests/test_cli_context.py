import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from huicode.cli import _run_chat
from huicode.config import ContextConfig, LLMConfig
from huicode.providers.base import ConversationMessage, StreamEvent


class ContextAwareProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = []

    def stream_chat(self, messages: list[ConversationMessage], tools=None, allow_tool_calls=True, prompt=None):
        self.calls.append(list(messages))
        if messages and messages[0].content.startswith("你正在为 HuiCode 压缩较早对话历史"):
            yield StreamEvent(kind="text", text="<summary>## 当前任务\n继续执行</summary>")
            return
        yield StreamEvent(kind="text", text=f"回复{len(self.calls)}")


class CLIContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_cwd = Path.cwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)

    def tearDown(self) -> None:
        os.chdir(self._old_cwd)
        self._tmpdir.cleanup()

    def test_compact_and_context_commands(self) -> None:
        provider = ContextAwareProvider()
        config = LLMConfig(
            "openai",
            "fake-model",
            "https://example.test/v1",
            "secret-api-key",
            context=ContextConfig(min_recent_messages=2, recent_keep_tokens=1),
        )
        output = io.StringIO()
        with patch("builtins.input", side_effect=["第一句", "第二句", "/compact", "/context", "/exit"]), redirect_stdout(output):
            exit_code = _run_chat(provider, config)

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("上下文摘要已生成", text)
        self.assertIn("summary_count=1", text)
        self.assertIn("fuse=false", text)

    def test_clear_resets_context_state(self) -> None:
        provider = ContextAwareProvider()
        config = LLMConfig(
            "openai",
            "fake-model",
            "https://example.test/v1",
            "secret-api-key",
            context=ContextConfig(min_recent_messages=2, recent_keep_tokens=1),
        )
        output = io.StringIO()
        with patch(
            "builtins.input",
            side_effect=["第一句", "第二句", "/compact", "/clear", "/context", "/exit"],
        ), redirect_stdout(output):
            exit_code = _run_chat(provider, config)

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("summary_count=0", text)
        self.assertIn("failure_count=0", text)

    def test_config_shows_context_summary_without_secrets(self) -> None:
        provider = ContextAwareProvider()
        config = LLMConfig(
            "openai",
            "fake-model",
            "https://example.test/v1",
            "secret-api-key",
            headers={"X-Title": "secret-title"},
            context=ContextConfig(window_tokens=64000),
        )
        output = io.StringIO()
        with patch("builtins.input", side_effect=["/config", "/exit"]), redirect_stdout(output):
            exit_code = _run_chat(provider, config)

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("window=64000", text)
        self.assertIn("fuse=false", text)
        self.assertNotIn("secret-api-key", text)
        self.assertNotIn("secret-title", text)


if __name__ == "__main__":
    unittest.main()
