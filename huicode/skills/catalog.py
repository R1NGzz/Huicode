from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from huicode.tools.registry import ToolRegistry

from .discovery import discover_skill_layer
from .parser import SkillDependencyError, ensure_skill_dependencies
from .types import SkillCatalogSnapshot, SkillDefinition, SkillSource


class SkillConfigError(ValueError):
    pass


class SkillCatalogBuilder:
    def __init__(
        self,
        roots: dict[SkillSource, Path],
        registry: ToolRegistry,
        reserved_commands: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        self.roots = roots
        self.registry = registry
        self.reserved_commands = {name.lower() for name in reserved_commands}

    def build(self, generation: int = 1) -> SkillCatalogSnapshot:
        try:
            ensure_skill_dependencies()
        except SkillDependencyError as exc:
            raise SkillConfigError(str(exc)) from exc
        merged: dict[str, SkillDefinition] = {}
        fingerprints = []
        warnings = []
        skipped = 0
        overridden = 0
        for source in ("builtin", "user", "project"):
            result = discover_skill_layer(self.roots[source], source)  # type: ignore[arg-type]
            fingerprints.extend(result.fingerprint)
            warnings.extend(result.warnings)
            skipped += result.skipped_count
            for name, definition in result.definitions.items():
                if name in merged:
                    overridden += 1
                merged[name] = definition

        normalized: dict[str, SkillDefinition] = {}
        for name, definition in merged.items():
            if name in self.reserved_commands:
                raise SkillConfigError(
                    f"Skill 命令 /{name} 与核心或兼容命令冲突: {definition.entry_path}"
                )
            tools: list[str] = []
            missing: list[str] = []
            for requested in definition.allowed_tools:
                resolved = self.registry.resolve_name(requested)
                if resolved is None:
                    missing.append(requested)
                elif resolved not in tools:
                    tools.append(resolved)
            if missing:
                raise SkillConfigError(
                    f"Skill {name} 的工具白名单存在未知工具 {', '.join(missing)}: "
                    f"{definition.entry_path}"
                )
            normalized[name] = replace(definition, allowed_tools=tuple(tools))

        return SkillCatalogSnapshot.create(
            normalized,
            tuple(sorted(set(fingerprints))),
            overridden_count=overridden,
            skipped_count=skipped,
            warnings=tuple(warnings),
            generation=generation,
        )
