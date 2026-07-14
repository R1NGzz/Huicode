import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from huicode.cli import _run_chat
from huicode.config import LLMConfig
from huicode.providers.base import StreamEvent


class RecordingProvider:
    name = "fake"
    model = "main"

    def __init__(self) -> None:
        self.calls = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
        self.calls.append({"messages": list(messages), "tools": list(tools or []), "prompt": prompt})
        yield StreamEvent(kind="text", text="done")


def write_shared_skill(root: Path, *, tools=("Read",), body="FOCUS {{args}}") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    entry = root / "focus.md"
    tool_lines = "\n".join(f"  - {tool}" for tool in tools)
    entry.write_text(
        f"""---
name: focus
description: Focus current task
allowed_tools:
{tool_lines}
mode: shared
---
{body}
""",
        encoding="utf-8",
    )
    return entry


class CLISkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_cwd = Path.cwd()
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        os.chdir(self.workspace)
        self.config = LLMConfig("openai", "main", "https://example.test", "secret")

    def tearDown(self) -> None:
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def test_shared_command_activates_sop_restricts_tools_and_clear_resets_status(self) -> None:
        write_shared_skill(self.workspace / ".huicode" / "skills")
        provider = RecordingProvider()
        output = io.StringIO()

        with patch("builtins.input", side_effect=["/focus Focus On API", "/clear", "/status", "/exit"]), redirect_stdout(output):
            code = _run_chat(provider, self.config)

        self.assertEqual(code, 0)
        self.assertEqual(len(provider.calls), 1)
        self.assertIn("FOCUS Focus On API", provider.calls[0]["prompt"].dynamic_text())
        self.assertEqual({tool.name for tool in provider.calls[0]["tools"]}, {"Read", "Skill"})
        self.assertIn("active=none", output.getvalue())

    def test_new_skill_is_available_on_same_input_after_hot_reload(self) -> None:
        provider = RecordingProvider()
        output = io.StringIO()
        calls = 0

        def input_side_effect(prompt):  # noqa: ANN001
            nonlocal calls
            calls += 1
            if calls == 1:
                return "/help"
            if calls == 2:
                write_shared_skill(self.workspace / ".huicode" / "skills", body="RELOADED {{args}}")
                return "/focus Mixed Case"
            return "/exit"

        with patch("builtins.input", side_effect=input_side_effect), redirect_stdout(output):
            code = _run_chat(provider, self.config)

        self.assertEqual(code, 0)
        self.assertEqual(len(provider.calls), 1)
        self.assertIn("RELOADED Mixed Case", provider.calls[0]["prompt"].dynamic_text())

    def test_invalid_hot_reload_keeps_previous_skill_and_command(self) -> None:
        entry = write_shared_skill(self.workspace / ".huicode" / "skills", body="VALID {{args}}")
        provider = RecordingProvider()
        output = io.StringIO()
        calls = 0

        def input_side_effect(prompt):  # noqa: ANN001
            nonlocal calls
            calls += 1
            if calls == 1:
                return "/focus First"
            if calls == 2:
                write_shared_skill(entry.parent, tools=("Missing",), body="INVALID {{args}}")
                return "/focus Second"
            return "/exit"

        with patch("builtins.input", side_effect=input_side_effect), redirect_stdout(output):
            code = _run_chat(provider, self.config)

        self.assertEqual(code, 0)
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("VALID Second", provider.calls[1]["prompt"].dynamic_text())
        self.assertIn("Skill 热更新失败", output.getvalue())

    def test_builtin_catalog_contains_commit_review_and_test(self) -> None:
        provider = RecordingProvider()
        output = io.StringIO()
        with patch("builtins.input", side_effect=["/help", "/exit"]), redirect_stdout(output):
            _run_chat(provider, self.config)

        text = output.getvalue()
        self.assertIn("/commit [arguments]", text)
        self.assertIn("/review [arguments]", text)
        self.assertIn("/test [arguments]", text)
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
