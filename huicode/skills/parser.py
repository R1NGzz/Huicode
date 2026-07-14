from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .types import SkillDefinition, SkillSource

try:
    import yaml
except ImportError:  # pragma: no cover - 安装元数据保证运行时依赖
    yaml = None


_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
_FIELDS = {"name", "description", "allowed_tools", "mode", "history_messages", "model"}


class SkillParseError(ValueError):
    pass


def parse_skill_file(
    entry_path: Path,
    source_root: Path,
    source: SkillSource,
) -> SkillDefinition:
    entry = _resolve_within(entry_path, source_root, "Skill 入口")
    package_root = entry.parent
    _resolve_within(package_root, source_root, "Skill 根目录")
    try:
        text = entry.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise SkillParseError(f"无法读取 Skill: {exc}") from exc
    metadata, body = _split_frontmatter(text)
    values = _load_yaml(metadata)
    unknown = sorted(set(values) - _FIELDS)
    if unknown:
        raise SkillParseError(f"未知 frontmatter 字段: {', '.join(unknown)}")

    name = _required_string(values, "name")
    if not _NAME_RE.fullmatch(name):
        raise SkillParseError("name 只能包含小写字母、数字、连字符和下划线")
    description = _required_string(values, "description")
    if "\n" in description or "\r" in description:
        raise SkillParseError("description 必须是单行文本")
    allowed_tools = _string_list(values.get("allowed_tools"), "allowed_tools")
    mode = _required_string(values, "mode")
    if mode not in {"shared", "isolated"}:
        raise SkillParseError("mode 只允许 shared 或 isolated")
    history_messages = values.get("history_messages", 0)
    if isinstance(history_messages, bool) or not isinstance(history_messages, int) or history_messages < 0:
        raise SkillParseError("history_messages 必须是非负整数")
    model_raw = values.get("model")
    if model_raw is not None and (not isinstance(model_raw, str) or not model_raw.strip()):
        raise SkillParseError("model 必须是非空字符串")
    if not body.strip():
        raise SkillParseError("Skill 正文不能为空")

    return SkillDefinition(
        name=name,
        description=description,
        allowed_tools=allowed_tools,
        mode=mode,  # type: ignore[arg-type]
        history_messages=history_messages,
        model=model_raw.strip() if isinstance(model_raw, str) else None,
        body=body.strip(),
        entry_path=entry,
        root_path=package_root,
        source=source,
    )


def render_skill_body(definition: SkillDefinition, arguments: str) -> str:
    return definition.body.replace("{{args}}", arguments)


def _split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillParseError("缺少开头 YAML frontmatter 边界 ---")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    raise SkillParseError("缺少结束 YAML frontmatter 边界 ---")


def _load_yaml(text: str) -> dict[str, Any]:
    if yaml is None:
        raise SkillParseError("缺少 PyYAML 依赖，请安装项目运行时依赖")
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SkillParseError(f"YAML 解析失败: {exc}") from exc
    if not isinstance(value, dict):
        raise SkillParseError("frontmatter 根节点必须是 YAML 映射")
    return value


def _required_string(values: dict[str, Any], field: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SkillParseError(f"{field} 必须是非空字符串")
    return value.strip()


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SkillParseError(f"{field} 必须是字符串列表")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise SkillParseError(f"{field} 中每一项都必须是非空字符串")
    items = tuple(item.strip() for item in value)
    if len(set(items)) != len(items):
        raise SkillParseError(f"{field} 不能包含重复工具")
    return items


def _resolve_within(path: Path, root: Path, label: str) -> Path:
    try:
        resolved_root = root.resolve(strict=False)
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise SkillParseError(f"{label}越出来源目录") from exc
    return resolved
