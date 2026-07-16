from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .types import AgentDefinition, AgentSource


_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
_FIELDS = {
    "name",
    "description",
    "allowed_tools",
    "denied_tools",
    "model",
    "max_iterations",
    "permission_mode",
}


class AgentParseError(ValueError):
    pass


class AgentValidationError(AgentParseError):
    pass


def parse_agent_file(path: Path, source: AgentSource) -> AgentDefinition:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise AgentParseError(f"无法读取角色: {exc}") from exc
    metadata, body = _split_frontmatter(text)
    try:
        values = yaml.safe_load(metadata)
    except yaml.YAMLError as exc:
        raise AgentParseError(f"YAML 解析失败: {exc}") from exc
    if not isinstance(values, dict):
        raise AgentParseError("frontmatter 根节点必须是 YAML 映射")
    unknown = sorted(set(values) - _FIELDS)
    if unknown:
        raise AgentValidationError(f"未知 frontmatter 字段: {', '.join(unknown)}")
    name = _required_string(values, "name")
    if not _NAME_RE.fullmatch(name):
        raise AgentValidationError("name 只能包含小写字母、数字、连字符和下划线")
    description = _required_string(values, "description")
    if "\n" in description or "\r" in description:
        raise AgentValidationError("description 必须是单行文本")
    allowed = _string_list(values.get("allowed_tools"), "allowed_tools")
    denied = _string_list(values.get("denied_tools", []), "denied_tools")
    model = _required_string(values, "model")
    if model not in {"inherit", "haiku", "sonnet", "opus"}:
        raise AgentValidationError("model 只允许 inherit、haiku、sonnet 或 opus")
    iterations = values.get("max_iterations")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or not 1 <= iterations <= 50:
        raise AgentValidationError("max_iterations 必须是 1 到 50 的整数")
    permission_mode = _required_string(values, "permission_mode")
    if permission_mode not in {"strict", "default", "permissive"}:
        raise AgentValidationError("permission_mode 只允许 strict、default 或 permissive")
    if not body.strip():
        raise AgentValidationError("角色正文不能为空")
    return AgentDefinition(
        name=name,
        description=description,
        allowed_tools=allowed,
        denied_tools=denied,
        model=model,  # type: ignore[arg-type]
        max_iterations=iterations,
        permission_mode=permission_mode,  # type: ignore[arg-type]
        instructions=body.strip(),
        source=source,
        source_path=path.resolve(),
    )


def _split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AgentParseError("缺少开头 YAML frontmatter 边界 ---")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    raise AgentParseError("缺少结束 YAML frontmatter 边界 ---")


def _required_string(values: dict[str, Any], field: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AgentValidationError(f"{field} 必须是非空字符串")
    return value.strip()


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AgentValidationError(f"{field} 必须是字符串列表")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise AgentValidationError(f"{field} 中每一项都必须是非空字符串")
    result = tuple(item.strip() for item in value)
    if len(set(result)) != len(result):
        raise AgentValidationError(f"{field} 不能包含重复工具")
    return result
