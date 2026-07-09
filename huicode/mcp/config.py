from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


MCPTransportType = Literal["stdio", "http"]


class MCPConfigError(ValueError):
    pass


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: MCPTransportType
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    source: str = "unknown"

    def env_map(self) -> dict[str, str]:
        return dict(self.env or {})

    def header_map(self) -> dict[str, str]:
        return dict(self.headers or {})


@dataclass(frozen=True)
class MCPConfig:
    servers: dict[str, MCPServerConfig]


@dataclass(frozen=True)
class MCPConfigPaths:
    user: Path
    project: Path


_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def mcp_config_paths(workspace: Path) -> MCPConfigPaths:
    return MCPConfigPaths(
        user=Path.home() / ".huicode" / "mcp.yaml",
        project=workspace / ".huicode-mcp.yaml",
    )


def load_mcp_config(
    paths: MCPConfigPaths,
    environ: dict[str, str] | None = None,
    inline_mcp: dict[str, Any] | None = None,
) -> MCPConfig:
    env = os.environ if environ is None else environ
    loaded: list[dict[str, MCPServerConfig]] = []
    loaded.append(_load_one(paths.user, "user", env))
    loaded.append(_parse_servers(inline_mcp or {}, "config", env, "huicode.yaml"))
    loaded.append(_load_one(paths.project, "project", env))

    servers: dict[str, MCPServerConfig] = {}
    for server_map in loaded:
        servers.update(server_map)
    return MCPConfig(servers=servers)


def _load_one(path: Path, source: str, environ: dict[str, str]) -> dict[str, MCPServerConfig]:
    if not path.exists():
        return {}
    try:
        parsed = parse_mcp_yaml(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MCPConfigError(f"读取 MCP 配置失败 {path}: {exc}") from exc

    mcp = parsed.get("mcp", {})
    if mcp is None:
        return {}
    if not isinstance(mcp, dict):
        raise MCPConfigError(f"MCP 配置 {path} 的 mcp 必须是映射")

    return _parse_servers(mcp, source, environ, str(path))


def _parse_servers(
    mcp: dict[str, Any],
    source: str,
    environ: dict[str, str],
    source_label: str,
) -> dict[str, MCPServerConfig]:
    servers: dict[str, MCPServerConfig] = {}
    for raw_name, raw_config in mcp.items():
        name = str(raw_name).strip()
        if not name:
            raise MCPConfigError(f"MCP 配置 {source_label} 包含空 server 名称")
        if not isinstance(raw_config, dict):
            raise MCPConfigError(f"MCP server {name} 必须是映射")
        servers[name] = _parse_server(name, raw_config, source, environ)
    return servers


def _parse_server(
    name: str,
    values: dict[str, Any],
    source: str,
    environ: dict[str, str],
) -> MCPServerConfig:
    transport = str(values.get("type", "")).strip().lower()
    if transport not in {"stdio", "http"}:
        raise MCPConfigError(f"MCP server {name} 的 type 必须是 stdio 或 http")

    if transport == "stdio":
        command = _required_string(values, "command", name, environ)
        args = tuple(_expand(str(item), environ, f"mcp.{name}.args") for item in _as_list(values.get("args", []), name, "args"))
        env = _expand_map(_as_map(values.get("env", {}), name, "env"), environ, f"mcp.{name}.env")
        return MCPServerConfig(
            name=name,
            transport="stdio",
            command=command,
            args=args,
            env=env,
            source=source,
        )

    url = _required_string(values, "url", name, environ)
    headers = _expand_map(_as_map(values.get("headers", {}), name, "headers"), environ, f"mcp.{name}.headers")
    return MCPServerConfig(
        name=name,
        transport="http",
        url=url,
        headers=headers,
        source=source,
    )


def _required_string(values: dict[str, Any], key: str, server_name: str, environ: dict[str, str]) -> str:
    value = values.get(key)
    if value is None or str(value).strip() == "":
        raise MCPConfigError(f"MCP server {server_name} 缺少必填字段 {key}")
    return _expand(str(value).strip(), environ, f"mcp.{server_name}.{key}")


def _as_list(value: Any, server_name: str, key: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MCPConfigError(f"MCP server {server_name} 的 {key} 必须是列表")
    return value


def _as_map(value: Any, server_name: str, key: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise MCPConfigError(f"MCP server {server_name} 的 {key} 必须是映射")
    return value


def _expand_map(values: dict[str, Any], environ: dict[str, str], field_path: str) -> dict[str, str]:
    expanded: dict[str, str] = {}
    for key, value in values.items():
        name = str(key).strip()
        if not name:
            raise MCPConfigError(f"{field_path} 包含空键")
        expanded[name] = _expand(str(value), environ, f"{field_path}.{name}")
    return expanded


def _expand(value: str, environ: dict[str, str], field_path: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in environ:
            raise MCPConfigError(f"{field_path} 引用了未定义环境变量 {name}")
        return environ[name]

    return _VAR_PATTERN.sub(replace, value)


def parse_mcp_yaml(text: str) -> dict[str, Any]:
    lines = [
        (line_no, line)
        for line_no, original in enumerate(text.splitlines(), start=1)
        if (line := _strip_comment(original).rstrip()).strip()
    ]
    if not lines:
        return {}
    root, index = _parse_block(lines, 0, _indent(lines[0][1]))
    if index != len(lines):
        line_no, _ = lines[index]
        raise MCPConfigError(f"第 {line_no} 行无法解析")
    if not isinstance(root, dict):
        raise MCPConfigError("MCP 配置根节点必须是映射")
    return root


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    _, line = lines[index]
    stripped = line.strip()
    if stripped.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_map(lines, index, indent)


def _parse_map(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        line_no, line = lines[index]
        current_indent = _indent(line)
        if current_indent < indent:
            break
        if current_indent > indent:
            raise MCPConfigError(f"第 {line_no} 行缩进不匹配")
        stripped = line.strip()
        if stripped.startswith("- "):
            break
        key, value = _split_pair(stripped, line_no)
        if value == "":
            next_index = index + 1
            if next_index >= len(lines) or _indent(lines[next_index][1]) <= indent:
                result[key] = {}
                index = next_index
                continue
            child, index = _parse_block(lines, next_index, _indent(lines[next_index][1]))
            result[key] = child
        else:
            result[key] = _parse_scalar(value)
            index += 1
    return result, index


def _parse_list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        line_no, line = lines[index]
        current_indent = _indent(line)
        if current_indent < indent:
            break
        if current_indent > indent:
            raise MCPConfigError(f"第 {line_no} 行缩进不匹配")
        stripped = line.strip()
        if not stripped.startswith("- "):
            break
        value = stripped[2:].strip()
        if value == "":
            next_index = index + 1
            if next_index >= len(lines) or _indent(lines[next_index][1]) <= indent:
                result.append(None)
                index = next_index
                continue
            child, index = _parse_block(lines, next_index, _indent(lines[next_index][1]))
            result.append(child)
        else:
            result.append(_parse_scalar(value))
            index += 1
    return result, index


def _strip_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            continue
        if char == "#" and quote is None:
            return line[:index]
    return line


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _split_pair(line: str, line_no: int) -> tuple[str, str]:
    if ":" not in line:
        raise MCPConfigError(f"第 {line_no} 行应为 key: value 格式")
    key, value = line.split(":", 1)
    key = key.strip().strip("\"'")
    if not key:
        raise MCPConfigError(f"第 {line_no} 行缺少键")
    return key, value.strip()


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    return value
