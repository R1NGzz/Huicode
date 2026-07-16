from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .parser import AgentParseError, AgentValidationError, parse_agent_file
from .types import AgentDefinition, AgentSource, AgentWarning


@dataclass(frozen=True)
class AgentLayerResult:
    definitions: dict[str, AgentDefinition]
    skipped_count: int = 0
    warnings: tuple[AgentWarning, ...] = ()


def discover_agent_layer(roots: tuple[Path, ...], source: AgentSource) -> AgentLayerResult:
    candidates: dict[str, list[AgentDefinition]] = {}
    warnings: list[AgentWarning] = []
    skipped = 0
    for root in roots:
        if not root.exists():
            continue
        try:
            entries = sorted(path for path in root.resolve().glob("*.md") if path.is_file())
        except OSError as exc:
            warnings.append(AgentWarning(root, "root_unreadable", str(exc)))
            skipped += 1
            continue
        for entry in entries:
            try:
                entry.resolve(strict=True).relative_to(root.resolve(strict=True))
            except (OSError, ValueError):
                warnings.append(AgentWarning(entry, "path_escape", "角色入口越出来源目录"))
                skipped += 1
                continue
            try:
                definition = parse_agent_file(entry, source)
            except AgentValidationError:
                raise
            except AgentParseError as exc:
                warnings.append(AgentWarning(entry, "parse_error", str(exc)))
                skipped += 1
                continue
            candidates.setdefault(definition.name, []).append(definition)
    duplicates = {name: items for name, items in candidates.items() if len(items) > 1}
    if duplicates:
        name, items = next(iter(duplicates.items()))
        paths = ", ".join(str(item.source_path) for item in items)
        raise ValueError(f"同一 {source} 来源角色 {name} 重复: {paths}")
    return AgentLayerResult(
        {name: items[0] for name, items in candidates.items()},
        skipped_count=skipped,
        warnings=tuple(warnings),
    )
