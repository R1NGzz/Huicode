import tempfile
import unittest
from pathlib import Path

from huicode.config import ConfigError, load_config


BASE = "protocol: openai\nmodel: test\nbase_url: https://example.test\napi_key: key\n"


class TeamConfigTests(unittest.TestCase):
    def load(self, extra: str = ""):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "huicode.yaml"
            path.write_text(BASE + extra, encoding="utf-8")
            return load_config(path)

    def test_defaults_are_disabled_and_safe(self):
        config = self.load()
        self.assertFalse(config.teams.enabled)
        self.assertEqual("auto", config.teams.default_backend)
        self.assertEqual(4, config.teams.max_members)

    def test_full_config(self):
        config = self.load("teams:\n  enabled: true\n  default_backend: coroutine\n  max_members: 6\n  coordinator_enabled: true\n  integration_checks:\n    - python -m unittest\n")
        self.assertTrue(config.teams.enabled)
        self.assertEqual("coroutine", config.teams.default_backend)
        self.assertEqual(("python -m unittest",), config.teams.integration_checks)

    def test_rejects_invalid_backend(self):
        with self.assertRaisesRegex(ConfigError, "teams.default_backend"):
            self.load("teams:\n  default_backend: magic\n")


if __name__ == "__main__":
    unittest.main()
