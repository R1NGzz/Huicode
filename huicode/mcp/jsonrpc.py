from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any


class MCPError(RuntimeError):
    pass


class MCPProtocolError(MCPError):
    pass


class MCPTransportError(MCPError):
    pass


@dataclass(frozen=True)
class JSONRPCError(MCPProtocolError):
    code: int
    message: str
    data: Any = None

    def __str__(self) -> str:
        return f"JSON-RPC error {self.code}: {self.message}"


@dataclass
class JSONRPCPeer:
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def next_id(self) -> int:
        return next(self._ids)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self.next_id(),
            "method": method,
        }
        if params is not None:
            message["params"] = params
        return message

    def notification(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            message["params"] = params
        return message


def validate_response(response: dict[str, Any], expected_id: object) -> Any:
    if response.get("jsonrpc") != "2.0":
        raise MCPProtocolError("JSON-RPC 响应缺少 jsonrpc=2.0")
    if response.get("id") != expected_id:
        raise MCPProtocolError(f"JSON-RPC 响应 id 不匹配: expected={expected_id} actual={response.get('id')}")
    if "error" in response:
        error = response["error"]
        if not isinstance(error, dict):
            raise MCPProtocolError("JSON-RPC error 必须是对象")
        raise JSONRPCError(
            code=int(error.get("code", 0)),
            message=str(error.get("message", "")),
            data=error.get("data"),
        )
    if "result" not in response:
        raise MCPProtocolError("JSON-RPC 响应缺少 result")
    return response["result"]


def validate_notification(message: dict[str, Any]) -> None:
    if message.get("jsonrpc") != "2.0" or not message.get("method") or "id" in message:
        raise MCPProtocolError("JSON-RPC notification 格式无效")
