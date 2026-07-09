import unittest

from huicode.mcp.config import MCPConfig, MCPServerConfig
from huicode.mcp.manager import MCPManager
from huicode.tools.registry import ToolRegistry


class FakeSessionTransport:
    def __init__(self, server_name: str, fail: bool = False) -> None:
        self.server_name = server_name
        self.fail = fail
        self.closed = False

    def start(self) -> None:
        if self.fail:
            raise RuntimeError("boom")

    def request(self, message, timeout_seconds):  # noqa: ANN001
        method = message["method"]
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": message["id"], "result": {"serverInfo": {"name": self.server_name}}}
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "tools": [
                        {"name": "search", "description": "Search", "inputSchema": {"type": "object"}},
                    ]
                },
            }
        return {"jsonrpc": "2.0", "id": message["id"], "result": {"content": []}}

    def notify(self, message):  # noqa: ANN001
        return None

    def close(self) -> None:
        self.closed = True


class MCPManagerTests(unittest.TestCase):
    def test_registers_multiple_servers_with_unique_names(self) -> None:
        config = MCPConfig(
            servers={
                "one": MCPServerConfig("one", "stdio", command="fake"),
                "two": MCPServerConfig("two", "stdio", command="fake"),
            }
        )
        registry = ToolRegistry()
        transports = {}

        def factory(server):
            transport = FakeSessionTransport(server.name)
            transports[server.name] = transport
            return transport

        manager = MCPManager(config, transport_factory=factory)
        manager.start(registry)

        self.assertEqual(manager.tool_count, 2)
        self.assertIsNotNone(registry.get("mcp__one__search"))
        self.assertIsNotNone(registry.get("mcp__two__search"))
        self.assertEqual(manager.errors, [])

        manager.close()
        self.assertTrue(transports["one"].closed)
        self.assertTrue(transports["two"].closed)

    def test_failed_server_does_not_block_other_servers(self) -> None:
        config = MCPConfig(
            servers={
                "bad": MCPServerConfig("bad", "stdio", command="fake"),
                "good": MCPServerConfig("good", "stdio", command="fake"),
            }
        )
        registry = ToolRegistry()

        def factory(server):
            return FakeSessionTransport(server.name, fail=server.name == "bad")

        manager = MCPManager(config, transport_factory=factory)
        manager.start(registry)

        self.assertEqual(manager.tool_count, 1)
        self.assertEqual(manager.errors[0].server, "bad")
        self.assertIsNotNone(registry.get("mcp__good__search"))


if __name__ == "__main__":
    unittest.main()
