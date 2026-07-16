import tempfile
import unittest
from pathlib import Path

from huicode.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_worktree_defaults_full_config_and_path_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = "protocol: openai\nmodel: test\nbase_url: https://example.test\napi_key: secret\n"
            path = root / "config.yaml"
            path.write_text(base, encoding="utf-8")
            defaults = load_config(path).worktrees
            self.assertEqual(defaults.root, ".huicode/worktrees")
            self.assertEqual(defaults.stale_after_days, 7)
            path.write_text(
                base
                + "worktrees:\n"
                + "  root: .huicode/wt\n"
                + "  stale_after_days: 3\n"
                + "  cleanup_interval_seconds: 60\n"
                + "  copy_files: [huicode.yaml]\n"
                + "  symlink_directories: [node_modules]\n"
                + "  restore_ignored: [fixtures/**/*.bin]\n"
                + "  hooks_path: .githooks\n",
                encoding="utf-8",
            )
            config = load_config(path).worktrees
            self.assertEqual(config.root, ".huicode/wt")
            self.assertEqual(config.symlink_directories, ("node_modules",))
            path.write_text(base + "worktrees:\n  root: ../outside\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)
    def test_loads_core_fields_and_thinking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huicode.yaml"
            path.write_text(
                "\n".join(
                    [
                        "protocol: anthropic",
                        "model: claude-test",
                        "base_url: https://api.anthropic.com/v1",
                        "api_key: test-key",
                        "max_tokens: 4096",
                        "temperature: 0.2",
                        "show_usage: true",
                        "headers:",
                        "  HTTP-Referer: https://example.test",
                        "  X-Title: HuiCode",
                        "thinking:",
                        "  enabled: true",
                        "  budget_tokens: 1024",
                        "  show: true",
                        "context:",
                        "  enabled: true",
                        "  window_tokens: 64000",
                        "  auto_margin_tokens: 12000",
                        "  single_tool_result_tokens: 1500",
                        "memory:",
                        "  enabled: true",
                        "  auto_update: false",
                        "  index_max_lines: 120",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.protocol, "anthropic")
        self.assertEqual(config.model, "claude-test")
        self.assertEqual(config.base_url, "https://api.anthropic.com/v1")
        self.assertEqual(config.api_key, "test-key")
        self.assertEqual(
            config.headers,
            {
                "HTTP-Referer": "https://example.test",
                "X-Title": "HuiCode",
            },
        )
        self.assertEqual(config.max_tokens, 4096)
        self.assertEqual(config.temperature, 0.2)
        self.assertTrue(config.show_usage)
        self.assertTrue(config.thinking.enabled)
        self.assertEqual(config.thinking.budget_tokens, 1024)
        self.assertTrue(config.thinking.show)
        self.assertTrue(config.context.enabled)
        self.assertEqual(config.context.window_tokens, 64000)
        self.assertEqual(config.context.auto_margin_tokens, 12000)
        self.assertEqual(config.context.single_tool_result_tokens, 1500)
        self.assertTrue(config.memory.enabled)
        self.assertFalse(config.memory.auto_update)
        self.assertEqual(config.memory.index_max_lines, 120)

    def test_rejects_missing_core_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huicode.yaml"
            path.write_text("protocol: openai\nmodel: test\nbase_url: http://example.test\n", encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "api_key"):
                load_config(path)

    def test_rejects_unsupported_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huicode.yaml"
            path.write_text(
                "protocol: other\nmodel: test\nbase_url: http://example.test\napi_key: key\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "protocol"):
                load_config(path)

    def test_rejects_invalid_bool_and_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huicode.yaml"
            path.write_text(
                "\n".join(
                    [
                        "protocol: anthropic",
                        "model: test",
                        "base_url: http://example.test",
                        "api_key: key",
                        "thinking:",
                        "  enabled: maybe",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "thinking.enabled"):
                load_config(path)

            path.write_text(
                "protocol: openai\nmodel: test\nbase_url: http://example.test\napi_key: key\nmax_tokens: nope\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "max_tokens"):
                load_config(path)

    def test_rejects_non_mapping_headers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huicode.yaml"
            path.write_text(
                "protocol: openai\nmodel: test\nbase_url: http://example.test\napi_key: key\nheaders: nope\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "headers"):
                load_config(path)

    def test_context_defaults_and_rejects_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huicode.yaml"
            path.write_text(
                "protocol: openai\nmodel: test\nbase_url: http://example.test\napi_key: key\n",
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertTrue(config.context.enabled)
            self.assertEqual(config.context.window_tokens, 128000)
            self.assertEqual(config.context.manual_margin_tokens, 3000)
            self.assertTrue(config.memory.enabled)
            self.assertTrue(config.memory.auto_update)

            path.write_text(
                "\n".join(
                    [
                        "protocol: openai",
                        "model: test",
                        "base_url: http://example.test",
                        "api_key: key",
                        "context:",
                        "  enabled: maybe",
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "context.enabled"):
                load_config(path)

            path.write_text(
                "\n".join(
                    [
                        "protocol: openai",
                        "model: test",
                        "base_url: http://example.test",
                        "api_key: key",
                        "context:",
                        "  single_tool_result_tokens: 0",
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "context.single_tool_result_tokens"):
                load_config(path)

    def test_memory_defaults_and_rejects_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huicode.yaml"
            path.write_text(
                "protocol: openai\nmodel: test\nbase_url: http://example.test\napi_key: key\n",
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertTrue(config.memory.enabled)
            self.assertEqual(config.memory.session_retention_days, 30)
            self.assertEqual(config.memory.index_max_bytes, 25 * 1024)

            path.write_text(
                "\n".join(
                    [
                        "protocol: openai",
                        "model: test",
                        "base_url: http://example.test",
                        "api_key: key",
                        "memory:",
                        "  enabled: maybe",
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "memory.enabled"):
                load_config(path)

            path.write_text(
                "\n".join(
                    [
                        "protocol: openai",
                        "model: test",
                        "base_url: http://example.test",
                        "api_key: key",
                        "memory:",
                        "  index_max_lines: 0",
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "memory.index_max_lines"):
                load_config(path)

    def test_rejects_context_thresholds_that_exceed_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huicode.yaml"
            path.write_text(
                "\n".join(
                    [
                        "protocol: openai",
                        "model: test",
                        "base_url: http://example.test",
                        "api_key: key",
                        "context:",
                        "  window_tokens: 5000",
                        "  auto_margin_tokens: 13000",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "context.auto_margin_tokens"):
                load_config(path)

            path.write_text(
                "\n".join(
                    [
                        "protocol: openai",
                        "model: test",
                        "base_url: http://example.test",
                        "api_key: key",
                        "context:",
                        "  window_tokens: 5000",
                        "  auto_margin_tokens: 1000",
                        "  recent_keep_tokens: 10000",
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "context.recent_keep_tokens"):
                load_config(path)

    def test_loads_inline_mcp_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huicode.yaml"
            path.write_text(
                "\n".join(
                    [
                        "protocol: openai",
                        "model: test",
                        "base_url: http://example.test",
                        "api_key: key",
                        "mcp:",
                        "  context7:",
                        "    type: stdio",
                        "    command: npx.cmd",
                        "    args:",
                        "      - -y",
                        "      - '@upstash/context7-mcp'",
                        "    env:",
                        "      NODE_ENV: production",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.mcp["context7"]["type"], "stdio")
        self.assertEqual(config.mcp["context7"]["command"], "npx.cmd")
        self.assertEqual(config.mcp["context7"]["args"], ["-y", "@upstash/context7-mcp"])
        self.assertEqual(config.mcp["context7"]["env"]["NODE_ENV"], "production")

    def test_loads_nested_inline_hook_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huicode.yaml"
            path.write_text(
                """protocol: openai
model: test
base_url: https://example.test
api_key: key
hooks:
  - id: python-edit
    event: tool_after
    if:
      all:
        - field: tool.name
          exact: Edit
        - field: tool.arguments.path
          glob: "**/*.py"
    action:
      type: prompt
      content: "edited {{tool.arguments.path}}"
""",
                encoding="utf-8",
            )
            config = load_config(path)
        self.assertEqual(config.hooks[0]["id"], "python-edit")
        self.assertEqual(config.hooks[0]["if"]["all"][1]["glob"], "**/*.py")

    def test_rejects_non_list_hooks_with_yaml_location(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huicode.yaml"
            path.write_text(
                "protocol: openai\nmodel: test\nbase_url: https://example.test\napi_key: key\nhooks: nope\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "hooks"):
                load_config(path)

            path.write_text("protocol: [\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, r"第 [12] 行第 1 列"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
