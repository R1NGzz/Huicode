from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from huicode.tools.base import ToolContext, ToolResult

from .jsonrpc import JSONRPCError, MCPError, MCPProtocolError, MCPTransportError
from .session import MCPClientSession


def public_tool_name(server_name: str, remote_name: str) -> str:
    return f"mcp__{_safe_part(server_name)}__{_safe_part(remote_name)}"


def _safe_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return safe or "tool"


@dataclass
class MCPToolAdapter:
    server_name: str
    remote_name: str
    name: str
    description: str
    parameters: dict[str, Any]
    session: MCPClientSession
    side_effect: bool = True

    @classmethod
    def from_metadata(
        cls,
        server_name: str,
        metadata: dict[str, Any],
        session: MCPClientSession,
    ) -> "MCPToolAdapter":
        remote_name = str(metadata.get("name", "")).strip()
        if not remote_name:
            raise ValueError(f"MCP server {server_name} 返回了缺少 name 的工具")
        description = str(metadata.get("description") or metadata.get("title") or f"MCP tool {remote_name}")
        parameters = metadata.get("inputSchema", {"type": "object", "properties": {}})
        if not isinstance(parameters, dict):
            parameters = {"type": "object", "properties": {}}
        return cls(
            server_name=server_name,
            remote_name=remote_name,
            name=public_tool_name(server_name, remote_name),
            description=f"[MCP:{server_name}] {description}",
            parameters=parameters,
            session=session,
        )

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        try:
            result = self.session.call_tool(self.remote_name, args)
        except JSONRPCError as exc:
            return ToolResult.failure(
                "mcp_protocol_error",
                str(exc),
                {"server": self.server_name, "tool": self.remote_name, "code": exc.code, "data": exc.data},
            )
        except MCPTransportError as exc:
            return ToolResult.failure(
                "mcp_transport_error",
                str(exc),
                {"server": self.server_name, "tool": self.remote_name},
            )
        except (MCPProtocolError, MCPError, ValueError) as exc:
            return ToolResult.failure(
                "mcp_protocol_error",
                str(exc),
                {"server": self.server_name, "tool": self.remote_name},
            )

        return mcp_result_to_tool_result(self.server_name, self.remote_name, result)


def mcp_result_to_tool_result(server_name: str, remote_name: str, result: dict[str, Any]) -> ToolResult:
    content = result.get("content", [])
    if not isinstance(content, list):
        content = []
    text_parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text", "")))
    text = "\n".join(part for part in text_parts if part)
    summary = text if text else f"MCP tool {server_name}/{remote_name} returned {len(content)} content block(s)"
    data = {
        "server": server_name,
        "tool": remote_name,
        "content": content,
        "text": text,
        "raw": result,
    }
    if result.get("isError") is True:
        return ToolResult.failure("mcp_tool_error", summary, data, summary=f"MCP tool error: {summary}")
    return ToolResult.success(data, summary)
