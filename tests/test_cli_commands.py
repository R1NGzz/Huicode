import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from huicode.cli import _create_prompt_session, _run_chat
from huicode.commands import (
    CommandRegistrationError,
    REVIEW_PROMPT,
    SlashCommandCompleter,
    create_builtin_registry,
)
from huicode.config import LLMConfig
from huicode.providers.base import ConversationMessage, StreamEvent


class RecordingProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = []

    def stream_chat(self, messages: list[ConversationMessage], tools=None, allow_tool_calls=True, prompt=None):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools or []),
                "allow_tool_calls": allow_tool_calls,
                "prompt": prompt,
            }
        )
        yield StreamEvent(kind="text", text="done")


class CLICommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_cwd = Path.cwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self.config = LLMConfig(
            "openai",
            "fake-model",
            "https://example.test/v1",
            "secret-api-key",
            headers={"Authorization": "Bearer header-secret"},
        )

    def tearDown(self) -> None:
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def test_local_and_state_commands_do_not_call_provider(self) -> None:
        provider = RecordingProvider()
        output = io.StringIO()
        commands = [
            "/help",
            "/plan",
            "/do",
            "/session",
            "/memory",
            "/permission",
            "/permission strict",
            "/status",
            "/clear",
            "/exit",
        ]

        with patch("builtins.input", side_effect=commands), redirect_stdout(output):
            exit_code = _run_chat(provider, self.config)

        self.assertEqual(exit_code, 0)
        self.assertEqual(provider.calls, [])
        text = output.getvalue()
        self.assertIn("本地命令", text)
        self.assertIn("[PLAN]", text)
        self.assertIn("[DEFAULT]", text)
        self.assertNotIn("secret-api-key", text)
        self.assertNotIn("header-secret", text)

    def test_unknown_and_invalid_commands_do_not_call_provider(self) -> None:
        provider = RecordingProvider()
        output = io.StringIO()
        with patch(
            "builtins.input",
            side_effect=["/wat", "/plan task", "/session bad", "/permission wild", "/exit"],
        ), redirect_stdout(output):
            exit_code = _run_chat(provider, self.config)

        self.assertEqual(exit_code, 0)
        self.assertEqual(provider.calls, [])
        self.assertIn("未知命令 /wat", output.getvalue())
        self.assertIn("输入 /help", output.getvalue())

    def test_review_expands_prompt_and_uses_current_mode(self) -> None:
        provider = RecordingProvider()
        output = io.StringIO()
        with patch(
            "builtins.input",
            side_effect=["/plan", "/review Focus On API", "/exit"],
        ), redirect_stdout(output):
            exit_code = _run_chat(provider, self.config)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(provider.calls), 1)
        sent = provider.calls[0]["messages"][-1].content
        self.assertIn(REVIEW_PROMPT, sent)
        self.assertIn("本次额外审查重点：Focus On API", sent)
        self.assertEqual(
            {tool.name for tool in provider.calls[0]["tools"]},
            {"Read", "Find", "Search"},
        )

    def test_non_tty_prompt_tracks_mode(self) -> None:
        provider = RecordingProvider()
        output = io.StringIO()
        with patch("builtins.input", side_effect=["/plan", "/do", "/exit"]) as mocked_input:
            with redirect_stdout(output):
                exit_code = _run_chat(provider, self.config)

        self.assertEqual(exit_code, 0)
        prompts = [call.args[0] for call in mocked_input.call_args_list]
        self.assertIn("[DEFAULT] You>", prompts[0])
        self.assertIn("[PLAN] You>", prompts[1])
        self.assertIn("[DEFAULT] You>", prompts[2])

    def test_help_hides_compatibility_commands(self) -> None:
        provider = RecordingProvider()
        output = io.StringIO()
        with patch("builtins.input", side_effect=["/help", "/exit"]), redirect_stdout(output):
            _run_chat(provider, self.config)

        help_text = output.getvalue()
        self.assertIn("/review [focus]", help_text)
        for hidden in ("/resume", "/permissions", "/config", "/context", "/verbose", "/last"):
            self.assertNotIn(hidden, help_text)

    def test_registration_failure_happens_before_chat_loop(self) -> None:
        provider = RecordingProvider()
        output = io.StringIO()

        def broken_registry():
            raise CommandRegistrationError("/x 冲突")

        with redirect_stdout(output):
            exit_code = _run_chat(
                provider,
                self.config,
                command_registry_factory=broken_registry,
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(provider.calls, [])
        self.assertIn("命令注册错误", output.getvalue())

    def test_prompt_session_uses_registry_completer_and_toolbar(self) -> None:
        captured = {}
        expected_session = SimpleNamespace(app=SimpleNamespace(invalidate=lambda: None))

        def fake_prompt_session(**kwargs):
            captured.update(kwargs)
            return expected_session

        runtime = SimpleNamespace(toolbar_text=lambda: "[DEFAULT]")
        registry = create_builtin_registry()
        with patch("huicode.cli.sys.stdin.isatty", return_value=True):
            with patch("huicode.cli.PromptSession", side_effect=fake_prompt_session):
                session = _create_prompt_session(registry, runtime)

        self.assertIs(session, expected_session)
        self.assertIsInstance(captured["completer"], SlashCommandCompleter)
        self.assertIs(captured["bottom_toolbar"], runtime.toolbar_text)
        completion_names = [
            name for name, _ in captured["completer"].registry.completion_entries()
        ]
        self.assertIn("review", completion_names)
        self.assertNotIn("resume", completion_names)


if __name__ == "__main__":
    unittest.main()
