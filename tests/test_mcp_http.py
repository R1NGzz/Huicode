import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from huicode.mcp.config import MCPServerConfig
from huicode.mcp.session import MCPClientSession
from huicode.mcp.transport import HTTPMCPTransport


class RecordingHandler(BaseHTTPRequestHandler):
    records = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.records.append({"headers": dict(self.headers), "payload": payload})
        method = payload.get("method")
        response_headers = {"Content-Type": "application/json"}
        if method == "initialize":
            response_headers["MCP-Session-Id"] = "session-123"
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-http"},
            }
        elif method == "tools/list":
            result = {"tools": [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object"}}]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": payload["params"]["arguments"]["text"]}]}
        else:
            result = {}
        body = json.dumps({"jsonrpc": "2.0", "id": payload.get("id"), "result": result}).encode("utf-8")
        self.send_response(200)
        for key, value in response_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002
        return


class EmptyNotifyHandler(BaseHTTPRequestHandler):
    records = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.records.append(payload)
        if payload.get("method") == "notifications/initialized":
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "serverInfo": {"name": "empty-notify"},
                },
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002
        return


class MCPHTTPTransportTests(unittest.TestCase):
    def test_http_session_posts_json_and_reuses_session_header(self) -> None:
        RecordingHandler.records = []
        server = HTTPServer(("127.0.0.1", 0), RecordingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = MCPServerConfig(
            name="remote",
            transport="http",
            url=f"http://127.0.0.1:{server.server_port}/mcp",
            headers={"Authorization": "Bearer secret"},
        )
        session = MCPClientSession(config, HTTPMCPTransport(config), timeout_seconds=5)

        try:
            session.initialize()
            tools = session.list_tools()
            result = session.call_tool("echo", {"text": "hello"})
        finally:
            session.close()
            server.shutdown()
            server.server_close()

        self.assertEqual(tools[0]["name"], "echo")
        self.assertEqual(result["content"][0]["text"], "hello")
        self.assertEqual(RecordingHandler.records[0]["headers"]["Accept"], "application/json, text/event-stream")
        self.assertEqual(RecordingHandler.records[0]["headers"]["Authorization"], "Bearer secret")
        self.assertNotIn("MCP-Session-Id", RecordingHandler.records[0]["headers"])
        self.assertEqual(_header(RecordingHandler.records[1]["headers"], "MCP-Session-Id"), "session-123")
        self.assertEqual(_header(RecordingHandler.records[2]["headers"], "MCP-Session-Id"), "session-123")

    def test_http_notification_accepts_empty_response(self) -> None:
        EmptyNotifyHandler.records = []
        server = HTTPServer(("127.0.0.1", 0), EmptyNotifyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = MCPServerConfig(
            name="remote",
            transport="http",
            url=f"http://127.0.0.1:{server.server_port}/mcp",
        )
        session = MCPClientSession(config, HTTPMCPTransport(config), timeout_seconds=5)

        try:
            session.initialize()
        finally:
            session.close()
            server.shutdown()
            server.server_close()

        self.assertEqual(EmptyNotifyHandler.records[1]["method"], "notifications/initialized")


def _header(headers: dict[str, str], name: str) -> str | None:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


if __name__ == "__main__":
    unittest.main()
