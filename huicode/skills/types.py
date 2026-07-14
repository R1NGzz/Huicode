from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping


SkillMode = Literal["shared", "isolated"]
SkillSource = Literal["builtin", "user", "project"]


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    allowed_tools: tuple[str, ...]
    mode: SkillMode
    history_messages: int
    model: str | None
    body: str
    entry_path: Path
    root_path: Path
    source: SkillSource


@dataclass(frozen=True)
class ActiveSkill:
    definition: SkillDefinition
    arguments: str
    rendered_body: str
    activated_order: int


@dataclass(frozen=True, order=True)
class SkillFileFingerprint:
    source: SkillSource
    path: str
    modified_ns: int
    size: int


@dataclass(frozen=True)
class SkillWarning:
    path: Path
    code: str
    message: str

    def display(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True)
class SkillCatalogSnapshot:
    definitions: Mapping[str, SkillDefinition] = field(
        default_factory=lambda: MappingProxyType({})
    )
    fingerprint: tuple[SkillFileFingerprint, ...] = ()
    overridden_count: int = 0
    skipped_count: int = 0
    warnings: tuple[SkillWarning, ...] = ()
    generation: int = 0

    @classmethod
    def create(
        cls,
        definitions: dict[str, SkillDefinition],
        fingerprint: tuple[SkillFileFingerprint, ...],
        *,
        overridden_count: int = 0,
        skipped_count: int = 0,
        warnings: tuple[SkillWarning, ...] = (),
        generation: int = 0,
    ) -> "SkillCatalogSnapshot":
        return cls(
            definitions=MappingProxyType(dict(definitions)),
            fingerprint=fingerprint,
            overridden_count=overridden_count,
            skipped_count=skipped_count,
            warnings=warnings,
            generation=generation,
        )


@dataclass
class SkillRuntimeState:
    active: dict[str, ActiveSkill] = field(default_factory=dict)
    next_activation_order: int = 0
    turn_model_override: str | None = None
    reload_error: str = ""
    catalog_generation: int = 0
    nesting_depth: int = 0


@dataclass(frozen=True)
class SkillRunResult:
    ok: bool
    status: str
    summary: str
    iterations: int = 0
    stop_reason: str = ""
