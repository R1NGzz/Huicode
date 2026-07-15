from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - 项目依赖缺失时必须明确失败
    raise RuntimeError("HuiCode 需要 PyYAML，请先安装项目依赖") from exc


@dataclass(frozen=True)
class ThinkingConfig:
    enabled: bool = False
    budget_tokens: int = 1024
    show: bool = False


@dataclass(frozen=True)
class ContextConfig:
    enabled: bool = True
    window_tokens: int = 128000
    auto_margin_tokens: int = 13000
    manual_margin_tokens: int = 3000
    recent_keep_tokens: int = 10000
    min_recent_messages: int = 5
    single_tool_result_tokens: int = 1000
    tool_result_group_tokens: int = 6000
    preview_chars: int = 1200
    max_summary_failures: int = 3


@dataclass(frozen=True)
class MemoryConfig:
    enabled: bool = False
    auto_update: bool = True
    instruction_include_depth: int = 5
    session_retention_days: int = 30
    stale_session_notice_hours: int = 24
    index_max_lines: int = 200
    index_max_bytes: int = 25 * 1024
    update_timeout_seconds: int = 45


@dataclass(frozen=True)
class LLMConfig:
    protocol: str
    model: str
    base_url: str
    api_key: str
    max_tokens: int = 2048
    temperature: float | None = None
    thinking: ThinkingConfig = field(default_factory=ThinkingConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    headers: dict[str, str] = field(default_factory=dict)
    show_usage: bool = False
    mcp: dict[str, Any] = field(default_factory=dict)
    hooks: list[dict[str, Any]] = field(default_factory=list)


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> LLMConfig:
    values = _parse_minimal_yaml(Path(path).read_text(encoding="utf-8-sig"))
    missing = [key for key in ("protocol", "model", "base_url", "api_key") if not values.get(key)]
    if missing:
        raise ConfigError(f"缺少必填配置字段: {', '.join(missing)}")

    protocol = str(values["protocol"]).strip().lower()
    if protocol not in {"openai", "anthropic"}:
        raise ConfigError("配置字段 protocol 只支持 openai 或 anthropic")

    thinking_raw = values.get("thinking", {})
    if thinking_raw is None:
        thinking_raw = {}
    if not isinstance(thinking_raw, dict):
        raise ConfigError("配置字段 thinking 必须是 YAML 映射")

    context_raw = values.get("context", {})
    if context_raw is None:
        context_raw = {}
    if not isinstance(context_raw, dict):
        raise ConfigError("配置字段 context 必须是 YAML 映射")

    memory_raw = values.get("memory", {})
    if memory_raw is None:
        memory_raw = {}
    if not isinstance(memory_raw, dict):
        raise ConfigError("配置字段 memory 必须是 YAML 映射")

    headers_raw = values.get("headers", {})
    if headers_raw is None:
        headers_raw = {}
    if not isinstance(headers_raw, dict):
        raise ConfigError("配置字段 headers 必须是 YAML 映射")

    mcp_raw = values.get("mcp", {})
    if mcp_raw is None:
        mcp_raw = {}
    if not isinstance(mcp_raw, dict):
        raise ConfigError("配置字段 mcp 必须是 YAML 映射")

    hooks_raw = values.get("hooks", [])
    if hooks_raw is None:
        hooks_raw = []
    if not isinstance(hooks_raw, list) or not all(isinstance(item, dict) for item in hooks_raw):
        raise ConfigError("配置字段 hooks 必须是 YAML 映射列表")

    context = ContextConfig(
        enabled=_as_bool(context_raw.get("enabled", True), "context.enabled"),
        window_tokens=_as_int(context_raw.get("window_tokens", 128000), "context.window_tokens"),
        auto_margin_tokens=_as_int(context_raw.get("auto_margin_tokens", 13000), "context.auto_margin_tokens"),
        manual_margin_tokens=_as_int(
            context_raw.get("manual_margin_tokens", 3000),
            "context.manual_margin_tokens",
        ),
        recent_keep_tokens=_as_int(
            context_raw.get("recent_keep_tokens", 10000),
            "context.recent_keep_tokens",
        ),
        min_recent_messages=_as_int(
            context_raw.get("min_recent_messages", 5),
            "context.min_recent_messages",
        ),
        single_tool_result_tokens=_as_int(
            context_raw.get("single_tool_result_tokens", 1000),
            "context.single_tool_result_tokens",
        ),
        tool_result_group_tokens=_as_int(
            context_raw.get("tool_result_group_tokens", 6000),
            "context.tool_result_group_tokens",
        ),
        preview_chars=_as_int(context_raw.get("preview_chars", 1200), "context.preview_chars"),
        max_summary_failures=_as_int(
            context_raw.get("max_summary_failures", 3),
            "context.max_summary_failures",
        ),
    )
    _validate_context_config(context)

    memory = MemoryConfig(
        enabled=_as_bool(memory_raw.get("enabled", True), "memory.enabled"),
        auto_update=_as_bool(memory_raw.get("auto_update", True), "memory.auto_update"),
        instruction_include_depth=_as_int(
            memory_raw.get("instruction_include_depth", 5),
            "memory.instruction_include_depth",
        ),
        session_retention_days=_as_int(
            memory_raw.get("session_retention_days", 30),
            "memory.session_retention_days",
        ),
        stale_session_notice_hours=_as_int(
            memory_raw.get("stale_session_notice_hours", 24),
            "memory.stale_session_notice_hours",
        ),
        index_max_lines=_as_int(memory_raw.get("index_max_lines", 200), "memory.index_max_lines"),
        index_max_bytes=_as_int(memory_raw.get("index_max_bytes", 25 * 1024), "memory.index_max_bytes"),
        update_timeout_seconds=_as_int(
            memory_raw.get("update_timeout_seconds", 45),
            "memory.update_timeout_seconds",
        ),
    )

    return LLMConfig(
        protocol=protocol,
        model=str(values["model"]).strip(),
        base_url=str(values["base_url"]).strip().rstrip("/"),
        api_key=str(values["api_key"]).strip(),
        headers=_as_string_map(headers_raw, "headers"),
        mcp=mcp_raw,
        hooks=hooks_raw,
        max_tokens=_as_int(values.get("max_tokens", 2048), "max_tokens"),
        temperature=_as_optional_float(values.get("temperature"), "temperature"),
        show_usage=_as_bool(values.get("show_usage", False), "show_usage"),
        thinking=ThinkingConfig(
            enabled=_as_bool(thinking_raw.get("enabled", False), "thinking.enabled"),
            budget_tokens=_as_int(thinking_raw.get("budget_tokens", 1024), "thinking.budget_tokens"),
            show=_as_bool(thinking_raw.get("show", False), "thinking.show"),
        ),
        context=context,
        memory=memory,
    )


def _parse_minimal_yaml(text: str) -> dict[str, Any]:
    try:
        root = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f"第 {mark.line + 1} 行第 {mark.column + 1} 列" if mark is not None else "未知位置"
        raise ConfigError(f"YAML 语法错误（{location}）: {exc}") from exc
    if root is None:
        return {}
    if not isinstance(root, dict):
        raise ConfigError("配置根节点必须是映射")
    return root


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    _, line = lines[index]
    if line.strip().startswith("- "):
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
            raise ConfigError(f"第 {line_no} 行缩进不匹配")
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
            raise ConfigError(f"第 {line_no} 行缩进不匹配")
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


def _split_pair(line: str, line_no: int) -> tuple[str, str]:
    if ":" not in line:
        raise ConfigError(f"第 {line_no} 行应为 key: value 格式")
    key, value = line.split(":", 1)
    key = key.strip()
    if not key:
        raise ConfigError(f"第 {line_no} 行缺少配置键")
    return key, value.strip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _as_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"配置字段 {field_name} 必须是整数") from exc
    if parsed <= 0:
        raise ConfigError(f"配置字段 {field_name} 必须大于 0")
    return parsed


def _as_optional_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"配置字段 {field_name} 必须是数字") from exc


def _as_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ConfigError(f"配置字段 {field_name} 必须是 true 或 false")


def _as_string_map(value: dict[str, Any], field_name: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, raw_value in value.items():
        name = str(key).strip()
        if not name:
            raise ConfigError(f"配置字段 {field_name} 包含空键")
        if raw_value is None:
            raise ConfigError(f"配置字段 {field_name}.{name} 不能为空")
        result[name] = str(raw_value).strip()
    return result


def _validate_context_config(context: ContextConfig) -> None:
    if context.auto_margin_tokens >= context.window_tokens:
        raise ConfigError("配置字段 context.auto_margin_tokens 必须小于 context.window_tokens")
    if context.manual_margin_tokens >= context.window_tokens:
        raise ConfigError("配置字段 context.manual_margin_tokens 必须小于 context.window_tokens")
    if context.recent_keep_tokens >= context.window_tokens:
        raise ConfigError("配置字段 context.recent_keep_tokens 必须小于 context.window_tokens")
