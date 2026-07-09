import sys
import unittest
from pathlib import Path

from huicode.mcp.config import MCPServerConfig
from huicode.mcp.session import MCPClientSession
from huicode.mcp.transport import StdioMCPTransport


class MCPStdioTransportTests(unittest.TestCase):
    def test_stdio_session_lists_and_calls_tool(self) -> None:
        server = Path(__file__).parent / "fixtures" / "mcp_echo_server.py"
        config = MCPServerConfig(
            name="fake",
            transport="stdio",
            command=sys.executable,
            args=(str(server),),
        )
        transport = StdioMCPTransport(config)
        session = MCPClientSession(config, transport, timeout_seconds=5)

        try:
            session.initialize()
            tools = session.list_tools()
            result = session.call_tool("echo", {"text": "hello"})
        finally:
            session.close()

        self.assertEqual(tools[0]["name"], "echo")
        self.assertEqual(result["content"][0]["text"], "echo:hello")
        self.assertIn("fake mcp server ready", transport.recent_stderr())


if __name__ == "__main__":
    unittest.main()
