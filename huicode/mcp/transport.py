from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import MCPServerConfig
from .jsonrpc import MCPProtocolError, MCPTransportError


class MCPTransport(Protocol):
    def start(self) -> None:
        ...

    def request(self, message: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        ...

    def notify(self, message: dict[str, Any]) -> None:
        ...

    def close(self) -> None:
        ...


@dataclass
class StdioMCPTransport:
    config: MCPServerConfig
    process: subprocess.Popen[str] | None = None
    _messages: "queue.Queue[dict[str, Any] | Exception]" = field(default_factory=queue.Queue)
    _stderr_lines: list[str] = field(default_factory=list)
    _write_lock: threading.Lock = field(default_factory=threading.Lock)
    _closed: bool = False

    def start(self) -> None:
        if self.process is not None:
            return
        if not self.config.command:
            raise MCPTransportError(f"MCP stdio server {self.config.name} 缺少 command")
        env = os.environ.copy()
        env.update(self.config.env_map())
        try:
            self.process = subprocess.Popen(
                [self.config.command, *self.config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except OSError as exc:
            raise MCPTransportError(f"启动 MCP stdio server {self.config.name} 失败: {exc}") from exc
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def request(self, message: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        expected_id = message.get("id")
        self._write_message(message)
        pending: list[dict[str, Any]] = []
        while True:
            try:
                received = self._messages.get(timeout=timeout_seconds)
            except queue.Empty as exc:
                raise MCPTransportError(f"MCP stdio server {self.config.name} 响应超时") from exc
            if isinstance(received, Exception):
                raise received
            if received.get("id") == expected_id:
                for item in pending:
                    self._messages.put(item)
                return received
            pending.append(received)

    def notify(self, message: dict[str, Any]) -> None:
        self._write_message(message)

    def close(self) -> None:
        self._closed = True
        process = self.process
        if process is None:
            return
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        for stream in (process.stdout, process.stderr):
            if stream:
                try:
                    stream.close()
                except OSError:
                    pass
        self.process = None

    def recent_stderr(self) -> str:
        return "\n".join(self._stderr_lines[-20:])

    def _write_message(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise MCPTransportError(f"MCP stdio server {self.config.name} 尚未启动")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            try:
                self.process.stdin.write(payload + "\n")
                self.process.stdin.flush()
            except OSError as exc:
                raise MCPTransportError(f"写入 MCP stdio server {self.config.name} 失败: {exc}") from exc

    def _read_stdout(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None
        for line in self.process.stdout:
            if self._closed:
                break
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError as exc:
                self._messages.put(MCPProtocolError(f"MCP stdio server {self.config.name} 输出了无效 JSON"))
                continue
            if not isinstance(message, dict):
                self._messages.put(MCPProtocolError(f"MCP stdio server {self.config.name} 输出的 JSON-RPC 消息必须是对象"))
                continue
            self._messages.put(message)

    def _read_stderr(self) -> None:
        assert self.process is not None
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self._stderr_lines.append(line.rstrip())
            if len(self._stderr_lines) > 50:
                del self._stderr_lines[: len(self._stderr_lines) - 50]


@dataclass
class HTTPMCPTransport:
    config: MCPServerConfig
    session_id: str | None = None
    opener: Any = None

    def start(self) -> None:
        if not self.config.url:
            raise MCPTransportError(f"MCP HTTP server {self.config.name} 缺少 url")

    def request(self, message: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        return self._post(message, timeout_seconds)

    def notify(self, message: dict[str, Any]) -> None:
        self._post(message, timeout_seconds=10, expect_response=False)

    def close(self) -> None:
        self.session_id = None

    def _post(self, message: dict[str, Any], timeout_seconds: float, expect_response: bool = True) -> dict[str, Any]:
        if not self.config.url:
            raise MCPTransportError(f"MCP HTTP server {self.config.name} 缺少 url")
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.config.header_map(),
        }
        if self.session_id:
            headers["MCP-Session-Id"] = self.session_id
        request = urllib.request.Request(self.config.url, data=body, headers=headers, method="POST")
        opener = self.opener or urllib.request
        try:
            response = opener.urlopen(request, timeout=timeout_seconds)
            with response:
                session_id = response.headers.get("MCP-Session-Id")
                if session_id:
                    self.session_id = session_id
                raw = response.read().decode("utf-8")
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise MCPTransportError(f"MCP HTTP server {self.config.name} 返回 HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise MCPTransportError(f"MCP HTTP server {self.config.name} 请求失败: {exc}") from exc
        except OSError as exc:
            raise MCPTransportError(f"MCP HTTP server {self.config.name} 请求失败: {exc}") from exc

        if not expect_response and not raw.strip():
            return {"jsonrpc": "2.0", "result": None}

        try:
            if "text/event-stream" in content_type:
                return _parse_sse_json(raw)
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MCPProtocolError(f"MCP HTTP server {self.config.name} 返回了无效 JSON") from exc
        if not isinstance(parsed, dict):
            raise MCPProtocolError(f"MCP HTTP server {self.config.name} 返回的 JSON-RPC 消息必须是对象")
        return parsed


def _parse_sse_json(text: str) -> dict[str, Any]:
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif line == "" and data_lines:
            break
    if not data_lines:
        raise MCPProtocolError("MCP SSE 响应缺少 data")
    parsed = json.loads("\n".join(data_lines))
    if not isinstance(parsed, dict):
        raise MCPProtocolError("MCP SSE data 必须是 JSON 对象")
    return parsed


def create_transport(config: MCPServerConfig) -> MCPTransport:
    if config.transport == "stdio":
        return StdioMCPTransport(config)
    return HTTPMCPTransport(config)
