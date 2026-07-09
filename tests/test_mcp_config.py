import tempfile
import unittest
from pathlib import Path

from huicode.mcp.config import MCPConfigError, MCPConfigPaths, load_mcp_config, parse_mcp_yaml


class MCPConfigTests(unittest.TestCase):
    def test_loads_stdio_and_http_servers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / ".huicode-mcp.yaml"
            project.write_text(
                "\n".join(
                    [
                        "mcp:",
                        "  local_echo:",
                        "    type: stdio",
                        "    command: python",
                        "    args:",
                        "      - server.py",
                        "      - ${PROJECT_ROOT}",
                        "    env:",
                        "      ECHO_PREFIX: ${ECHO_PREFIX}",
                        "  remote_search:",
                        "    type: http",
                        "    url: ${MCP_URL}",
                        "    headers:",
                        "      Authorization: Bearer ${MCP_TOKEN}",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_mcp_config(
                MCPConfigPaths(root / "missing-user.yaml", project),
                environ={
                    "PROJECT_ROOT": str(root),
                    "ECHO_PREFIX": "hi",
                    "MCP_URL": "http://localhost/mcp",
                    "MCP_TOKEN": "secret-token",
                },
            )

        self.assertEqual(set(config.servers), {"local_echo", "remote_search"})
        self.assertEqual(config.servers["local_echo"].transport, "stdio")
        self.assertEqual(config.servers["local_echo"].args[-1], str(root))
        self.assertEqual(config.servers["local_echo"].env_map()["ECHO_PREFIX"], "hi")
        self.assertEqual(config.servers["remote_search"].transport, "http")
        self.assertEqual(config.servers["remote_search"].url, "http://localhost/mcp")
        self.assertEqual(config.servers["remote_search"].header_map()["Authorization"], "Bearer secret-token")

    def test_merges_user_and_project_with_project_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            user = root / "user.yaml"
            project = root / "project.yaml"
            user.write_text(
                "mcp:\n  shared:\n    type: http\n    url: http://user/mcp\n  only_user:\n    type: stdio\n    command: user\n",
                encoding="utf-8",
            )
            project.write_text(
                "mcp:\n  shared:\n    type: http\n    url: http://project/mcp\n  only_project:\n    type: stdio\n    command: project\n",
                encoding="utf-8",
            )

            config = load_mcp_config(MCPConfigPaths(user, project), environ={})

        self.assertEqual(set(config.servers), {"shared", "only_user", "only_project"})
        self.assertEqual(config.servers["shared"].url, "http://project/mcp")
        self.assertEqual(config.servers["shared"].source, "project")
        self.assertEqual(config.servers["only_user"].source, "user")

    def test_missing_variable_and_required_fields_are_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "mcp.yaml"
            path.write_text("mcp:\n  bad:\n    type: http\n    url: ${MISSING}\n", encoding="utf-8")

            with self.assertRaisesRegex(MCPConfigError, "MISSING"):
                load_mcp_config(MCPConfigPaths(root / "missing.yaml", path), environ={})

            path.write_text("mcp:\n  bad:\n    type: stdio\n", encoding="utf-8")
            with self.assertRaisesRegex(MCPConfigError, "command"):
                load_mcp_config(MCPConfigPaths(root / "missing.yaml", path), environ={})

    def test_parser_supports_nested_maps_and_lists(self) -> None:
        parsed = parse_mcp_yaml("mcp:\n  s:\n    args:\n      - one\n      - 'two'\n")

        self.assertEqual(parsed["mcp"]["s"]["args"], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
