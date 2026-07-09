import unittest

from huicode.mcp.jsonrpc import MCPTransportError
from huicode.mcp.tools import MCPToolAdapter, mcp_result_to_tool_result, public_tool_name
from huicode.tools.base import ToolContext


class FakeSession:
    def __init__(self, result=None, error=None) -> None:
        self.result = result or {"content": [{"type": "text", "text": "hello"}]}
        self.error = error
        self.calls = []

    def call_tool(self, name, arguments):  # noqa: ANN001
        self.calls.append((name, arguments))
        if self.error:
            raise self.error
        return self.result


class MCPToolAdapterTests(unittest.TestCase):
    def test_public_name_is_stable_and_sanitized(self) -> None:
        self.assertEqual(public_tool_name("my server", "search.files"), "mcp__my_server__search_files")

    def test_adapter_calls_remote_name_and_returns_text_result(self) -> None:
        session = FakeSession()
        adapter = MCPToolAdapter.from_metadata(
            "demo",
            {
                "name": "echo",
                "description": "Echo input",
                "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
            },
            session,  # type: ignore[arg-type]
        )

        result = adapter.run({"text": "hi"}, ToolContext(__import__("pathlib").Path.cwd()))

        self.assertTrue(result.ok)
        self.assertEqual(adapter.name, "mcp__demo__echo")
        self.assertTrue(adapter.side_effect)
        self.assertEqual(session.calls, [("echo", {"text": "hi"})])
        self.assertIn("hello", result.summary)

    def test_is_error_result_becomes_failure(self) -> None:
        result = mcp_result_to_tool_result(
            "demo",
            "bad",
            {"isError": True, "content": [{"type": "text", "text": "failed"}]},
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "mcp_tool_error")

    def test_transport_error_becomes_failure(self) -> None:
        adapter = MCPToolAdapter(
            server_name="demo",
            remote_name="echo",
            name="mcp__demo__echo",
            description="Echo",
            parameters={},
            session=FakeSession(error=MCPTransportError("offline")),  # type: ignore[arg-type]
        )

        result = adapter.run({}, ToolContext(__import__("pathlib").Path.cwd()))

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "mcp_transport_error")


if __name__ == "__main__":
    unittest.main()
