from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .parser import SkillParseError, parse_skill_file
from .types import SkillDefinition, SkillFileFingerprint, SkillSource, SkillWarning


@dataclass(frozen=True)
class SkillLayerResult:
    definitions: dict[str, SkillDefinition]
    fingerprint: tuple[SkillFileFingerprint, ...]
    skipped_count: int
    warnings: tuple[SkillWarning, ...]


def discover_skill_layer(root: Path, source: SkillSource) -> SkillLayerResult:
    if not root.exists():
        return SkillLayerResult({}, (), 0, ())
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        warning = SkillWarning(root, "root_unreadable", f"无法访问 Skill 目录: {exc}")
        return SkillLayerResult({}, (), 1, (warning,))

    entries = _entry_candidates(resolved_root)
    candidates: dict[str, list[SkillDefinition]] = {}
    warnings: list[SkillWarning] = []
    skipped = 0
    for entry in entries:
        try:
            definition = parse_skill_file(entry, resolved_root, source)
        except SkillParseError as exc:
            skipped += 1
            warnings.append(SkillWarning(entry, "parse_error", str(exc)))
            continue
        candidates.setdefault(definition.name, []).append(definition)

    definitions: dict[str, SkillDefinition] = {}
    for name, matches in candidates.items():
        if len(matches) == 1:
            definitions[name] = matches[0]
            continue
        skipped += len(matches)
        paths = ", ".join(str(item.entry_path) for item in matches)
        warnings.append(
            SkillWarning(resolved_root, "duplicate_name", f"同层 Skill {name} 重复，已跳过: {paths}")
        )
    return SkillLayerResult(
        definitions=definitions,
        fingerprint=fingerprint_skill_root(resolved_root, source),
        skipped_count=skipped,
        warnings=tuple(warnings),
    )


def fingerprint_skill_root(root: Path, source: SkillSource) -> tuple[SkillFileFingerprint, ...]:
    if not root.exists():
        return ()
    try:
        resolved_root = root.resolve(strict=True)
    except OSError:
        return ()
    fingerprints: list[SkillFileFingerprint] = []
    for entry in _entry_candidates(resolved_root):
        package_root = entry.parent if entry.name == "SKILL.md" else None
        files = [entry]
        if package_root is not None:
            files = sorted(path for path in package_root.rglob("*") if path.is_file())
        for path in files:
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(resolved_root)
                stat = resolved.stat()
            except (OSError, ValueError):
                continue
            fingerprints.append(
                SkillFileFingerprint(
                    source=source,
                    path=resolved.relative_to(resolved_root).as_posix(),
                    modified_ns=stat.st_mtime_ns,
                    size=stat.st_size,
                )
            )
    return tuple(sorted(set(fingerprints)))


def _entry_candidates(root: Path) -> list[Path]:
    entries = [path for path in root.glob("*.md") if path.is_file()]
    entries.extend(path for path in root.glob("*/SKILL.md") if path.is_file())
    return sorted(set(entries), key=lambda path: path.as_posix().lower())
