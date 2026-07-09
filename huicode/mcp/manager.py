from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from huicode.tools.registry import ToolRegistry

from .config import MCPConfig, MCPServerConfig
from .session import MCPClientSession
from .tools import MCPToolAdapter
from .transport import MCPTransport, create_transport


@dataclass(frozen=True)
class MCPServerError:
    server: str
    message: str


TransportFactory = Callable[[MCPServerConfig], MCPTransport]


@dataclass
class MCPManager:
    config: MCPConfig
    timeout_seconds: float = 10
    transport_factory: TransportFactory = create_transport
    sessions: dict[str, MCPClientSession] = field(default_factory=dict)
    tools: list[MCPToolAdapter] = field(default_factory=list)
    errors: list[MCPServerError] = field(default_factory=list)

    def start(self, registry: ToolRegistry) -> None:
        for server in self.config.servers.values():
            try:
                session = MCPClientSession(
                    config=server,
                    transport=self.transport_factory(server),
                    timeout_seconds=self.timeout_seconds,
                )
                session.initialize()
                self.sessions[server.name] = session
                for metadata in session.list_tools():
                    adapter = MCPToolAdapter.from_metadata(server.name, metadata, session)
                    registry.register(adapter)
                    self.tools.append(adapter)
            except Exception as exc:  # noqa: BLE001 - 单个 MCP server 失败必须隔离
                self.errors.append(MCPServerError(server=server.name, message=str(exc)))

    def close(self) -> None:
        for session in list(self.sessions.values()):
            try:
                session.close()
            except Exception:
                pass
        self.sessions.clear()

    @property
    def server_count(self) -> int:
        return len(self.config.servers)

    @property
    def active_server_count(self) -> int:
        return len(self.sessions)

    @property
    def tool_count(self) -> int:
        return len(self.tools)
