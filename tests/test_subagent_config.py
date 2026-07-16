import tempfile
import unittest
from pathlib import Path

from huicode.config import ConfigError, load_config


BASE = """protocol: openai
model: main
base_url: https://example.test
api_key: secret
"""


class SubagentConfigTests(unittest.TestCase):
    def test_defaults_and_model_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(
                BASE
                + """subagents:
  foreground_timeout_seconds: 0.5
  max_background_tasks: 2
  shutdown_wait_seconds: 1.5
  background_allowed_tools: [Read, Find]
  model_aliases:
    haiku: fast-model
""",
                encoding="utf-8",
            )
            config = load_config(path)
        self.assertEqual(config.subagents.foreground_timeout_seconds, 0.5)
        self.assertEqual(config.subagents.background_allowed_tools, ("Read", "Find"))
        self.assertEqual(config.subagents.model_aliases["haiku"], "fast-model")

    def test_rejects_invalid_fields(self) -> None:
        invalid = (
            "subagents:\n  max_background_tasks: 0\n",
            "subagents:\n  foreground_timeout_seconds: -1\n",
            "subagents:\n  background_allowed_tools: Read\n",
            "subagents:\n  model_aliases:\n    turbo: model\n",
        )
        for suffix in invalid:
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.yaml"
                path.write_text(BASE + suffix, encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_config(path)

    def test_rejects_duplicate_model_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(
                BASE
                + """subagents:
  model_aliases:
    haiku: first
    haiku: second
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as caught:
                load_config(path)
        self.assertIn("duplicate key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
