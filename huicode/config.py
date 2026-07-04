from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ThinkingConfig:
    enabled: bool = False
    budget_tokens: int = 1024
    show: bool = False


@dataclass(frozen=True)
class LLMConfig:
    protocol: str
    model: str
    base_url: str
    api_key: str
    max_tokens: int = 2048
    temperature: float | None = None
    thinking: ThinkingConfig = field(default_factory=ThinkingConfig)
    headers: dict[str, str] = field(default_factory=dict)
    show_usage: bool = False


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> LLMConfig:
    values = _parse_minimal_yaml(Path(path).read_text(encoding="utf-8"))
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

    headers_raw = values.get("headers", {})
    if headers_raw is None:
        headers_raw = {}
    if not isinstance(headers_raw, dict):
        raise ConfigError("配置字段 headers 必须是 YAML 映射")

    return LLMConfig(
        protocol=protocol,
        model=str(values["model"]).strip(),
        base_url=str(values["base_url"]).strip().rstrip("/"),
        api_key=str(values["api_key"]).strip(),
        headers=_as_string_map(headers_raw, "headers"),
        max_tokens=_as_int(values.get("max_tokens", 2048), "max_tokens"),
        temperature=_as_optional_float(values.get("temperature"), "temperature"),
        show_usage=_as_bool(values.get("show_usage", False), "show_usage"),
        thinking=ThinkingConfig(
            enabled=_as_bool(thinking_raw.get("enabled", False), "thinking.enabled"),
            budget_tokens=_as_int(thinking_raw.get("budget_tokens", 1024), "thinking.budget_tokens"),
            show=_as_bool(thinking_raw.get("show", False), "thinking.show"),
        ),
    )


def _parse_minimal_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    current_map: dict[str, Any] | None = None

    for line_no, original in enumerate(text.splitlines(), start=1):
        line = _strip_comment(original).rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent not in (0, 2):
            raise ConfigError(f"第 {line_no} 行缩进不支持，请使用 0 或 2 个空格")

        key, value = _split_pair(line.strip(), line_no)
        if indent == 0:
            if value == "":
                current_map = {}
                root[key] = current_map
            else:
                current_map = None
                root[key] = _parse_scalar(value)
        else:
            if current_map is None:
                raise ConfigError(f"第 {line_no} 行存在没有父级的嵌套字段")
            if value == "":
                raise ConfigError(f"第 {line_no} 行不支持超过一层的嵌套映射")
            current_map[key] = _parse_scalar(value)

    return root


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
