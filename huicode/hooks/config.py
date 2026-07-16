from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    import yaml
except ImportError as exc:  # pragma: no cover - 项目依赖缺失时必须明确失败
    raise RuntimeError("Hook 系统需要 PyYAML，请先安装项目依赖") from exc

from .types import (
    HOOK_EVENT_NAMES,
    CommandAction,
    HookCatalog,
    HookCondition,
    HookPredicate,
    HookRule,
    HttpAction,
    PromptAction,
    SubagentAction,
)


class HookConfigError(ValueError):
    pass


@dataclass(frozen=True)
class HookConfigPaths:
    user: Path
    project: Path


_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")
_COMMON_FIELDS = {
    "event",
    "occurred_at",
    "session_id",
    "workspace",
    "mode",
    "turn_id",
    "iteration",
    "agent_scope",
}
_EVENT_FIELD_PREFIXES: dict[str, tuple[str, ...]] = {
    "session_start": ("session.",),
    "session_end": ("session.",),
    "turn_start": ("turn.",),
    "turn_end": ("turn.",),
    "message_received": ("message.",),
    "message_completed": ("message.",),
    "tool_before": ("tool.",),
    "tool_after": ("tool.", "result."),
    "context_before_compact": ("context.",),
    "context_after_compact": ("context.",),
    "agent_error": ("error.",),
}


def hook_config_paths(workspace: Path) -> HookConfigPaths:
    return HookConfigPaths(
        user=Path.home() / ".huicode" / "hooks.yaml",
        project=workspace / ".huicode" / "hooks.yaml",
    )


def load_hook_catalog(
    paths: HookConfigPaths,
    inline_hooks: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    environ: Mapping[str, str] | None = None,
) -> HookCatalog:
    env = os.environ if environ is None else environ
    sources = [
        ("user", str(paths.user), _load_file(paths.user)),
        ("config", "huicode.yaml", list(inline_hooks or [])),
        ("project", str(paths.project), _load_file(paths.project)),
    ]
    ordered: list[HookRule] = []
    index_by_id: dict[str, int] = {}
    for source, source_path, raw_rules in sources:
        parsed = _parse_source(raw_rules, source, source_path, env)
        for rule in parsed:
            if rule.id in index_by_id:
                old_index = index_by_id.pop(rule.id)
                ordered.pop(old_index)
                index_by_id = {item.id: idx for idx, item in enumerate(ordered)}
            index_by_id[rule.id] = len(ordered)
            ordered.append(rule)

    source_counts: dict[str, int] = {}
    for rule in ordered:
        source_counts[rule.source] = source_counts.get(rule.source, 0) + 1
    return HookCatalog(
        rules=tuple(ordered),
        disabled_count=sum(1 for rule in ordered if not rule.enabled),
        source_counts=source_counts,
    )


def _load_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, yaml.YAMLError) as exc:
        raise HookConfigError(f"读取 Hook 配置失败 {path}: {exc}") from exc
    if parsed is None:
        return []
    if not isinstance(parsed, dict):
        raise HookConfigError(f"Hook 配置 {path} 根节点必须是映射")
    hooks = parsed.get("hooks", [])
    if hooks is None:
        return []
    if not isinstance(hooks, list):
        raise HookConfigError(f"Hook 配置 {path} 的 hooks 必须是列表")
    if not all(isinstance(item, dict) for item in hooks):
        raise HookConfigError(f"Hook 配置 {path} 的每条 hooks 规则必须是映射")
    return hooks


def _parse_source(
    raw_rules: list[dict[str, Any]],
    source: str,
    source_path: str,
    environ: Mapping[str, str],
) -> list[HookRule]:
    seen: set[str] = set()
    parsed: list[HookRule] = []
    for position, raw in enumerate(raw_rules, start=1):
        if not isinstance(raw, dict):
            raise HookConfigError(f"Hook 配置 {source_path} 第 {position} 条规则必须是映射")
        rule_id = _required_string(raw, "id", source_path, position)
        if not _ID_PATTERN.fullmatch(rule_id):
            raise _error(rule_id, source_path, "id", "只允许字母、数字、点、下划线和连字符")
        if rule_id in seen:
            raise _error(rule_id, source_path, "id", "同一来源存在重复 id")
        seen.add(rule_id)
        parsed.append(_parse_rule(raw, rule_id, source, source_path, environ))
    return parsed


def _parse_rule(
    raw: dict[str, Any],
    rule_id: str,
    source: str,
    source_path: str,
    environ: Mapping[str, str],
) -> HookRule:
    event = str(raw.get("event", "")).strip().lower()
    if event not in HOOK_EVENT_NAMES:
        raise _error(rule_id, source_path, "event", f"未知事件 {event or '<empty>'}")
    enabled = _bool(raw.get("enabled", True), rule_id, source_path, "enabled")
    once = _bool(raw.get("once", False), rule_id, source_path, "once")
    async_run = _bool(raw.get("async", False), rule_id, source_path, "async")
    timeout = _int(raw.get("timeout_seconds", 30), rule_id, source_path, "timeout_seconds")
    if not 1 <= timeout <= 300:
        raise _error(rule_id, source_path, "timeout_seconds", "必须在 1 到 300 之间")
    condition = _parse_condition(raw.get("if"), event, rule_id, source_path)
    action_raw = raw.get("action")
    if not isinstance(action_raw, dict):
        raise _error(rule_id, source_path, "action", "必须是映射")
    action = _parse_action(action_raw, event, rule_id, source_path, environ)
    if event == "tool_before" and async_run:
        raise _error(rule_id, source_path, "async", "tool_before 拦截事件不允许异步")
    if isinstance(action, PromptAction) and async_run:
        raise _error(rule_id, source_path, "async", "prompt 动作不允许异步")
    if event == "tool_before" and isinstance(action, SubagentAction):
        raise _error(rule_id, source_path, "action.type", "tool_before 不允许 subagent 动作")
    if event == "session_end" and isinstance(action, PromptAction):
        raise _error(rule_id, source_path, "action.type", "session_end 不允许 prompt 动作")
    return HookRule(
        id=rule_id,
        event=event,  # type: ignore[arg-type]
        condition=condition,
        action=action,
        enabled=enabled,
        once=once,
        async_run=async_run,
        timeout_seconds=timeout,
        source=source,
        source_path=source_path,
    )


def _parse_condition(raw: Any, event: str, rule_id: str, source_path: str) -> HookCondition | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _error(rule_id, source_path, "if", "必须是映射")
    modes = [name for name in ("all", "any") if name in raw]
    if len(modes) != 1 or len(raw) != 1:
        raise _error(rule_id, source_path, "if", "只能包含 all 或 any 其中一个")
    mode = modes[0]
    items = raw[mode]
    if not isinstance(items, list) or not items:
        raise _error(rule_id, source_path, f"if.{mode}", "必须是非空列表")
    predicates = tuple(
        _parse_predicate(item, event, rule_id, source_path, f"if.{mode}[{index}]")
        for index, item in enumerate(items)
    )
    return HookCondition(mode=mode, predicates=predicates)  # type: ignore[arg-type]


def _parse_predicate(raw: Any, event: str, rule_id: str, source_path: str, field_path: str) -> HookPredicate:
    if not isinstance(raw, dict):
        raise _error(rule_id, source_path, field_path, "必须是映射")
    field = str(raw.get("field", "")).strip()
    if not field or not _field_allowed(event, field):
        raise _error(rule_id, source_path, f"{field_path}.field", f"事件 {event} 不支持字段 {field or '<empty>'}")
    match_keys = [name for name in ("exact", "glob", "regex", "not") if name in raw]
    if len(match_keys) != 1 or set(raw) != {"field", match_keys[0]}:
        raise _error(rule_id, source_path, field_path, "每个条件只能包含一种匹配方式")
    key = match_keys[0]
    negate = key == "not"
    if negate:
        nested = raw["not"]
        if not isinstance(nested, dict) or len(nested) != 1:
            raise _error(rule_id, source_path, f"{field_path}.not", "必须只包含 exact、glob 或 regex 之一")
        key, value = next(iter(nested.items()))
        if key not in {"exact", "glob", "regex"}:
            raise _error(rule_id, source_path, f"{field_path}.not", f"未知匹配方式 {key}")
    else:
        value = raw[key]
    expected = str(value)
    if key == "regex":
        try:
            re.compile(expected)
        except re.error as exc:
            raise _error(rule_id, source_path, f"{field_path}.regex", f"无效正则: {exc}") from exc
    return HookPredicate(field=field, operator=key, value=expected, negate=negate)  # type: ignore[arg-type]


def _parse_action(
    raw: dict[str, Any],
    event: str,
    rule_id: str,
    source_path: str,
    environ: Mapping[str, str],
):
    action_type = str(raw.get("type", "")).strip().lower()
    prefix = "action"
    if action_type == "command":
        command = _expand(_action_string(raw, "command", rule_id, source_path), environ, rule_id, source_path, f"{prefix}.command")
        args_raw = raw.get("args", [])
        if not isinstance(args_raw, list):
            raise _error(rule_id, source_path, f"{prefix}.args", "必须是列表")
        args = tuple(_expand(str(value), environ, rule_id, source_path, f"{prefix}.args") for value in args_raw)
        cwd_raw = raw.get("cwd")
        cwd = None if cwd_raw is None else _expand(str(cwd_raw), environ, rule_id, source_path, f"{prefix}.cwd")
        env_raw = raw.get("env", {})
        if not isinstance(env_raw, dict):
            raise _error(rule_id, source_path, f"{prefix}.env", "必须是映射")
        env = {
            str(key): _expand(str(value), environ, rule_id, source_path, f"{prefix}.env.{key}")
            for key, value in env_raw.items()
        }
        return CommandAction(command=command, args=args, cwd=cwd, env=env)
    if action_type == "prompt":
        content = _action_string(raw, "content", rule_id, source_path)
        scope = str(raw.get("scope", "next_request")).strip().lower()
        if scope not in {"next_request", "turn", "session"}:
            raise _error(rule_id, source_path, f"{prefix}.scope", "必须是 next_request、turn 或 session")
        _validate_templates(content, event, rule_id, source_path, f"{prefix}.content")
        return PromptAction(content=content, scope=scope)  # type: ignore[arg-type]
    if action_type == "http":
        url = _expand(_action_string(raw, "url", rule_id, source_path), environ, rule_id, source_path, f"{prefix}.url")
        method = str(raw.get("method", "POST")).strip().upper()
        if not method:
            raise _error(rule_id, source_path, f"{prefix}.method", "不能为空")
        headers_raw = raw.get("headers", {})
        if not isinstance(headers_raw, dict):
            raise _error(rule_id, source_path, f"{prefix}.headers", "必须是映射")
        headers = {
            str(key): _expand(str(value), environ, rule_id, source_path, f"{prefix}.headers.{key}")
            for key, value in headers_raw.items()
        }
        status_raw = raw.get("expected_status", [200, 299])
        if not isinstance(status_raw, list) or len(status_raw) != 2:
            raise _error(rule_id, source_path, f"{prefix}.expected_status", "必须是 [最小值, 最大值]")
        try:
            expected = (int(status_raw[0]), int(status_raw[1]))
        except (TypeError, ValueError) as exc:
            raise _error(rule_id, source_path, f"{prefix}.expected_status", "必须包含整数") from exc
        if expected[0] < 100 or expected[1] > 599 or expected[0] > expected[1]:
            raise _error(rule_id, source_path, f"{prefix}.expected_status", "状态范围无效")
        return HttpAction(url=url, method=method, headers=headers, expected_status=expected)
    if action_type == "subagent":
        task = _action_string(raw, "task", rule_id, source_path)
        role = str(raw.get("role", "general")).strip()
        if not role:
            raise _error(rule_id, source_path, f"{prefix}.role", "不能为空")
        _validate_templates(task, event, rule_id, source_path, f"{prefix}.task")
        _validate_templates(role, event, rule_id, source_path, f"{prefix}.role")
        return SubagentAction(task=task, role=role)
    raise _error(rule_id, source_path, "action.type", f"未知动作 {action_type or '<empty>'}")


def _field_allowed(event: str, field: str) -> bool:
    return field in _COMMON_FIELDS or any(field.startswith(prefix) for prefix in _EVENT_FIELD_PREFIXES[event])


def _validate_templates(text: str, event: str, rule_id: str, source_path: str, field_path: str) -> None:
    for field in _TEMPLATE_PATTERN.findall(text):
        if not _field_allowed(event, field):
            raise _error(rule_id, source_path, field_path, f"事件 {event} 不支持模板字段 {field}")


def _expand(value: str, environ: Mapping[str, str], rule_id: str, source_path: str, field_path: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in environ:
            raise _error(rule_id, source_path, field_path, f"引用了未定义环境变量 {name}")
        return environ[name]

    return _VAR_PATTERN.sub(replace, value)


def _required_string(raw: dict[str, Any], key: str, source_path: str, position: int) -> str:
    value = raw.get(key)
    if value is None or not str(value).strip():
        raise HookConfigError(f"Hook 配置 {source_path} 第 {position} 条规则缺少必填字段 {key}")
    return str(value).strip()


def _action_string(raw: dict[str, Any], key: str, rule_id: str, source_path: str) -> str:
    value = raw.get(key)
    if value is None or not str(value).strip():
        raise _error(rule_id, source_path, f"action.{key}", "不能为空")
    return str(value).strip()


def _bool(value: Any, rule_id: str, source_path: str, field_path: str) -> bool:
    if isinstance(value, bool):
        return value
    raise _error(rule_id, source_path, field_path, "必须是 true 或 false")


def _int(value: Any, rule_id: str, source_path: str, field_path: str) -> int:
    if isinstance(value, bool):
        raise _error(rule_id, source_path, field_path, "必须是整数")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _error(rule_id, source_path, field_path, "必须是整数") from exc


def _error(rule_id: str, source_path: str, field_path: str, message: str) -> HookConfigError:
    return HookConfigError(f"Hook {rule_id} ({source_path}) 字段 {field_path}: {message}")
