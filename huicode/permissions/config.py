from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from huicode.permissions.base import PermissionConfig, PermissionConfigError, PermissionMode, PermissionRule
from huicode.permissions.rules import parse_rule_key


VALID_MODES = {"strict", "default", "permissive"}
VALID_ACTIONS = {"allow", "deny"}
_ENCODED_RULE_PREFIX = "__huicode_b64__:"


@dataclass(frozen=True)
class PermissionConfigPaths:
    user: Path
    project: Path
    local: Path


def permission_config_paths(workspace: Path) -> PermissionConfigPaths:
    return PermissionConfigPaths(
        user=Path.home() / ".huicode" / "permissions.yaml",
        project=workspace / ".huicode-permissions.yaml",
        local=workspace / ".huicode-permissions.local.yaml",
    )


def load_permission_config(paths: PermissionConfigPaths) -> PermissionConfig:
    loaded = [
        _load_one(paths.user, "user"),
        _load_one(paths.project, "project"),
        _load_one(paths.local, "local"),
    ]
    mode: PermissionMode = "default"
    for config in loaded:
        if config is not None and config.mode != "default":
            mode = config.mode

    rules: list[PermissionRule] = []
    for config in reversed([config for config in loaded if config is not None]):
        rules.extend(config.rules)
    return PermissionConfig(mode=mode, rules=tuple(rules))


def append_persistent_rule(path: Path, rule: PermissionRule) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if not existing.strip():
        existing = "mode: default\nrules:\n"
    elif "rules:" not in existing:
        existing = existing.rstrip() + "\nrules:\n"
    raw = rule.raw or f"{rule.tool}({rule.pattern})"
    line = f"  {_quote_key(raw)}: {rule.action}\n"
    path.write_text(existing.rstrip() + "\n" + line, encoding="utf-8")


def _load_one(path: Path, source: str) -> PermissionConfig | None:
    if not path.exists():
        return None
    try:
        parsed = _parse_permission_yaml(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PermissionConfigError(f"读取权限配置失败 {path}: {exc}") from exc

    mode = _parse_mode(parsed.get("mode", "default"), path)
    rules_raw = parsed.get("rules", {})
    if not isinstance(rules_raw, dict):
        raise PermissionConfigError(f"权限配置 {path} 的 rules 必须是映射")
    rules: list[PermissionRule] = []
    for raw_key, raw_action in rules_raw.items():
        action = str(raw_action).strip().lower()
        if action not in VALID_ACTIONS:
            raise PermissionConfigError(f"权限规则 {raw_key} 的结果必须是 allow 或 deny")
        try:
            tool, pattern = parse_rule_key(str(raw_key))
        except ValueError as exc:
            raise PermissionConfigError(str(exc)) from exc
        rules.append(PermissionRule(tool=tool, pattern=pattern, action=action, source=source, raw=str(raw_key)))  # type: ignore[arg-type]
    return PermissionConfig(mode=mode, rules=tuple(rules))


def _parse_mode(value: Any, path: Path) -> PermissionMode:
    mode = str(value).strip().lower()
    if mode not in VALID_MODES:
        raise PermissionConfigError(f"权限配置 {path} 的 mode 必须是 strict、default 或 permissive")
    return mode  # type: ignore[return-value]


def _parse_permission_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    current_map: dict[str, str] | None = None
    for line_no, original in enumerate(text.splitlines(), start=1):
        line = _strip_comment(original).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, value = _split_pair(line.strip(), line_no)
        if indent == 0:
            if value == "":
                current_map = {}
                root[key] = current_map
            else:
                current_map = None
                root[key] = _parse_scalar(value)
        elif indent == 2:
            if current_map is None:
                raise PermissionConfigError(f"第 {line_no} 行存在没有父级的规则")
            if value == "":
                raise PermissionConfigError(f"第 {line_no} 行规则结果不能为空")
            current_map[key] = str(_parse_scalar(value))
        else:
            raise PermissionConfigError(f"第 {line_no} 行缩进不支持，请使用 0 或 2 个空格")
    return root


def _strip_comment(line: str) -> str:
    quote: str | None = None
    for index, char in enumerate(line):
        if char in {"'", '"'}:
            quote = None if quote == char else char
            continue
        if char == "#" and quote is None:
            return line[:index]
    return line


def _split_pair(line: str, line_no: int) -> tuple[str, str]:
    if ":" not in line:
        raise PermissionConfigError(f"第 {line_no} 行应为 key: value 格式")
    key, value = line.rsplit(":", 1)
    key = _unquote_key(key.strip())
    if not key:
        raise PermissionConfigError(f"第 {line_no} 行缺少键")
    return key, value.strip()


def _parse_scalar(value: str) -> Any:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _quote_key(value: str) -> str:
    if "\n" in value or "\r" in value:
        encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
        value = _ENCODED_RULE_PREFIX + encoded
    return "'" + value.replace("'", "''") + "'"


def _unquote_key(value: str) -> str:
    if value.startswith("'") and value.endswith("'"):
        value = value[1:-1].replace("''", "'")
    elif value.startswith('"') and value.endswith('"'):
        value = value[1:-1].replace('\\"', '"')
    if value.startswith(_ENCODED_RULE_PREFIX):
        encoded = value[len(_ENCODED_RULE_PREFIX) :]
        try:
            return base64.b64decode(encoded, altchars=b"-_", validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise PermissionConfigError("权限规则包含损坏的多行编码") from exc
    return value
