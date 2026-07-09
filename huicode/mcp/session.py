from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import MCPServerConfig
from .jsonrpc import JSONRPCPeer, validate_response
from .transport import MCPTransport


MCP_PROTOCOL_VERSION = "2025-11-25"


@dataclass
class MCPClientSession:
    config: MCPServerConfig
    transport: MCPTransport
    timeout_seconds: float = 10
    peer: JSONRPCPeer = field(default_factory=JSONRPCPeer)
    initialized: bool = False
    server_info: dict[str, Any] = field(default_factory=dict)

    def initialize(self) -> None:
        self.transport.start()
        message = self.peer.request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "HuiCode",
                    "version": "0.1.0",
                },
            },
        )
        result = self._request(message)
        if not isinstance(result, dict):
            raise ValueError(f"MCP server {self.config.name} initialize result 必须是对象")
        server_info = result.get("serverInfo", {})
        if isinstance(server_info, dict):
            self.server_info = server_info
        self.transport.notify(self.peer.notification("notifications/initialized"))
        self.initialized = True

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request(self.peer.request("tools/list"))
        if not isinstance(result, dict):
            raise ValueError(f"MCP server {self.config.name} tools/list result 必须是对象")
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise ValueError(f"MCP server {self.config.name} tools/list.tools 必须是列表")
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._request(
            self.peer.request(
                "tools/call",
                {
                    "name": name,
                    "arguments": arguments,
                },
            )
        )
        if not isinstance(result, dict):
            raise ValueError(f"MCP server {self.config.name} tools/call result 必须是对象")
        return result

    def close(self) -> None:
        self.transport.close()

    def _request(self, message: dict[str, Any]) -> Any:
        response = self.transport.request(message, self.timeout_seconds)
        return validate_response(response, message.get("id"))
