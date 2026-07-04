import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from huicode.cli import _run_chat
from huicode.config import LLMConfig
from huicode.providers.base import ConversationMessage, StreamEvent, ToolCall


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls: list[list[ConversationMessage]] = []

    def stream_chat(self, messages: list[ConversationMessage], tools=None, allow_tool_calls=True, prompt=None):
        self.calls.append(list(messages))
        yield StreamEvent(kind="text", text=f"第{len(self.calls)}次回复")


class CLITests(unittest.TestCase):
    def test_config_command_does_not_print_api_key_and_exit_works(self) -> None:
        provider = FakeProvider()
        config = LLMConfig(
            protocol="openai",
            model="fake-model",
            base_url="https://example.test/v1",
            api_key="secret-api-key",
            headers={"X-Title": "secret-title"},
        )

        output = io.StringIO()
        with patch("builtins.input", side_effect=["/config", "/exit"]), redirect_stdout(output):
            exit_code = _run_chat(provider, config)

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("protocol=fake", text)
        self.assertIn("fake-model", text)
        self.assertIn("headers=X-Title", text)
        self.assertNotIn("secret-api-key", text)
        self.assertNotIn("secret-title", text)

    def test_multiturn_history_is_sent_to_provider(self) -> None:
        provider = FakeProvider()
        config = LLMConfig(
            protocol="openai",
            model="fake-model",
            base_url="https://example.test/v1",
            api_key="secret-api-key",
        )

        output = io.StringIO()
        with patch("builtins.input", side_effect=["你好", "还记得上一句吗", "/exit"]), redirect_stdout(output):
            exit_code = _run_chat(provider, config)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual([message.role for message in provider.calls[1]], ["user", "assistant", "user"])
        self.assertEqual(provider.calls[1][0].content, "你好")
        self.assertEqual(provider.calls[1][1].content, "第1次回复")
        self.assertEqual(provider.calls[1][2].content, "还记得上一句吗")

    def test_tool_line_is_printed(self) -> None:
        class ToolProvider(FakeProvider):
            def __init__(self) -> None:
                super().__init__()
                self.turn = 0

            def stream_chat(self, messages: list[ConversationMessage], tools=None, allow_tool_calls=True, prompt=None):
                self.calls.append(list(messages))
                self.turn += 1
                if self.turn == 1:
                    yield StreamEvent(
                        kind="tool_call",
                        tool_call=ToolCall(id="call_1", name="Read", arguments={"path": "README.md"}),
                    )
                else:
                    yield StreamEvent(kind="text", text="读完了")

        provider = ToolProvider()
        config = LLMConfig("openai", "fake-model", "https://example.test/v1", "secret-api-key")
        output = io.StringIO()
        with patch("builtins.input", side_effect=["读 README", "/exit"]), redirect_stdout(output):
            exit_code = _run_chat(provider, config)

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("✓ Read(README.md)", text)
        self.assertIn("读完了", text)

    def test_usage_is_hidden_until_verbose_is_enabled(self) -> None:
        class UsageProvider(FakeProvider):
            def stream_chat(self, messages: list[ConversationMessage], tools=None, allow_tool_calls=True, prompt=None):
                self.calls.append(list(messages))
                yield StreamEvent(kind="usage", usage={"total_tokens": 123})
                yield StreamEvent(kind="text", text="完成")

        provider = UsageProvider()
        config = LLMConfig("openai", "fake-model", "https://example.test/v1", "secret-api-key")
        output = io.StringIO()
        with patch("builtins.input", side_effect=["你好", "/verbose", "再来", "/exit"]), redirect_stdout(output):
            exit_code = _run_chat(provider, config)

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertEqual(text.count("tokens:"), 1)
        self.assertIn("详细用量显示已开启", text)

    def test_last_expands_recent_tool_result(self) -> None:
        class BashProvider(FakeProvider):
            def __init__(self) -> None:
                super().__init__()
                self.turn = 0

            def stream_chat(self, messages: list[ConversationMessage], tools=None, allow_tool_calls=True, prompt=None):
                self.calls.append(list(messages))
                self.turn += 1
                if self.turn == 1:
                    yield StreamEvent(
                        kind="tool_call",
                        tool_call=ToolCall(
                            id="call_1",
                            name="Bash",
                            arguments={
                                "command": (
                                    f"\"{__import__('sys').executable}\" -c \"print('expanded-output')\""
                                )
                            },
                        ),
                    )
                else:
                    yield StreamEvent(kind="text", text="执行完了")

        provider = BashProvider()
        config = LLMConfig("openai", "fake-model", "https://example.test/v1", "secret-api-key")
        output = io.StringIO()
        with patch("builtins.input", side_effect=["运行命令", "/last", "/exit"]), redirect_stdout(output):
            exit_code = _run_chat(provider, config)

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("command:", text)
        self.assertIn("stdout:", text)
        self.assertIn("expanded-output", text)


if __name__ == "__main__":
    unittest.main()
