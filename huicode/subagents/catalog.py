from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from huicode.config import SubagentConfig
from huicode.tools.registry import ToolRegistry

from .discovery import discover_agent_layer
from .types import AgentCatalogSnapshot, AgentDefinition, AgentSource


class SubagentConfigError(ValueError):
    pass


class AgentCatalog:
    def __init__(
        self,
        roots: dict[AgentSource, tuple[Path, ...]],
        registry: ToolRegistry,
        config: SubagentConfig,
    ) -> None:
        self.roots = roots
        self.registry = registry
        self.config = config
        self.snapshot = AgentCatalogSnapshot.create({})

    def initialize(self) -> AgentCatalogSnapshot:
        merged: dict[str, AgentDefinition] = {}
        warnings = []
        skipped = 0
        overridden = 0
        try:
            for source in ("plugin", "builtin", "user", "project"):
                result = discover_agent_layer(self.roots.get(source, ()), source)  # type: ignore[arg-type]
                warnings.extend(result.warnings)
                skipped += result.skipped_count
                for name, definition in result.definitions.items():
                    if name in merged:
                        overridden += 1
                    merged[name] = definition
        except ValueError as exc:
            raise SubagentConfigError(str(exc)) from exc

        background, missing_background = self.registry.normalize_names(
            set(self.config.background_allowed_tools)
        )
        if missing_background:
            raise SubagentConfigError(
                "配置字段 subagents.background_allowed_tools 包含未知工具: "
                + ", ".join(sorted(missing_background))
            )
        normalized: dict[str, AgentDefinition] = {}
        for name, definition in merged.items():
            requested = set(definition.allowed_tools) | set(definition.denied_tools)
            resolved, missing = self.registry.normalize_names(requested)
            if missing:
                raise SubagentConfigError(
                    f"角色 {name} 引用未知工具 {', '.join(sorted(missing))}: {definition.source_path}"
                )
            forbidden = resolved & {"Agent", "Skill"}
            if forbidden:
                raise SubagentConfigError(
                    f"角色 {name} 不得引用系统禁止工具 {', '.join(sorted(forbidden))}: "
                    f"{definition.source_path}"
                )
            if definition.model != "inherit" and definition.model not in self.config.model_aliases:
                raise SubagentConfigError(
                    f"角色 {name} 的模型别名 {definition.model} 未在 "
                    f"subagents.model_aliases 中映射: {definition.source_path}"
                )
            allowed = tuple(
                resolved_name
                for tool_name in definition.allowed_tools
                if (resolved_name := self.registry.resolve_name(tool_name)) is not None
            )
            denied = tuple(
                resolved_name
                for tool_name in definition.denied_tools
                if (resolved_name := self.registry.resolve_name(tool_name)) is not None
            )
            normalized[name] = replace(definition, allowed_tools=allowed, denied_tools=denied)
        self.snapshot = AgentCatalogSnapshot.create(
            normalized,
            overridden_count=overridden,
            skipped_count=skipped,
            warnings=tuple(warnings),
        )
        return self.snapshot

    def get(self, name: str) -> AgentDefinition | None:
        return self.snapshot.definitions.get(name.strip().lower())

    def list(self) -> tuple[AgentDefinition, ...]:
        return tuple(self.snapshot.definitions.values())

    def catalog_items(self) -> tuple[tuple[str, str], ...]:
        return tuple((item.name, item.description) for item in self.list())


def default_agent_roots(
    workspace: Path,
    plugin_roots: tuple[Path, ...] = (),
) -> dict[AgentSource, tuple[Path, ...]]:
    if not plugin_roots:
        configured = os.environ.get("HUICODE_PLUGIN_AGENT_PATHS", "")
        plugin_roots = tuple(
            Path(item).expanduser()
            for item in configured.split(os.pathsep)
            if item.strip()
        )
    return {
        "plugin": plugin_roots,
        "builtin": (Path(__file__).parent / "builtin",),
        "user": (Path.home() / ".huicode" / "agents",),
        "project": (workspace / ".huicode" / "agents",),
    }
