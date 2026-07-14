from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .catalog import SkillCatalogBuilder, SkillConfigError
from .discovery import fingerprint_skill_root
from .parser import render_skill_body
from .types import ActiveSkill, SkillCatalogSnapshot, SkillRuntimeState, SkillSource


class SkillManager:
    def __init__(self, builder: SkillCatalogBuilder) -> None:
        self.builder = builder
        self.snapshot = SkillCatalogSnapshot.create({}, (), generation=0)
        self.reload_errors = 0

    def initialize(self) -> SkillCatalogSnapshot:
        self.snapshot = self.builder.build(generation=1)
        return self.snapshot

    def get(self, name: str):  # noqa: ANN201
        return self.snapshot.definitions.get(name.strip().lower())

    def activate_shared(self, state: SkillRuntimeState, name: str, arguments: str) -> ActiveSkill:
        definition = self.get(name)
        if definition is None:
            raise SkillConfigError(f"未知 Skill: {name}")
        if definition.mode != "shared":
            raise SkillConfigError(f"Skill {name} 不是 shared 模式")
        current = state.active.get(definition.name)
        if current is None:
            order = state.next_activation_order
            state.next_activation_order += 1
        else:
            order = current.activated_order
        active = ActiveSkill(
            definition=definition,
            arguments=arguments,
            rendered_body=render_skill_body(definition, arguments),
            activated_order=order,
        )
        state.active[definition.name] = active
        state.catalog_generation = self.snapshot.generation
        if definition.model:
            state.turn_model_override = definition.model
        return active

    def catalog_items(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(
            (definition.name, definition.description, definition.mode)
            for definition in self.snapshot.definitions.values()
        )

    def active_items(self, state: SkillRuntimeState) -> tuple[ActiveSkill, ...]:
        return tuple(sorted(state.active.values(), key=lambda item: item.activated_order))

    def active_prompt_blocks(self, state: SkillRuntimeState) -> tuple[str, ...]:
        blocks = []
        for item in self.active_items(state):
            definition = item.definition
            tools = ", ".join(definition.allowed_tools) or "none"
            blocks.append(
                f'<huicode_instruction type="active_skill" name="{definition.name}" '
                f'mode="{definition.mode}" priority="highest">\n'
                f"source: {definition.source}\n"
                f"skill_root: {definition.root_path.as_posix()}\n"
                f"allowed_tools: {tools}\n"
                f"{item.rendered_body}\n"
                "</huicode_instruction>"
            )
        return tuple(blocks)

    def active_allowed_tools(self, state: SkillRuntimeState) -> set[str] | None:
        active = self.active_items(state)
        if not active:
            return None
        allowed = set(active[0].definition.allowed_tools)
        for item in active[1:]:
            allowed.intersection_update(item.definition.allowed_tools)
        return allowed

    def reload_if_changed(self, state: SkillRuntimeState | None = None) -> bool:
        current = []
        for source in ("builtin", "user", "project"):
            root = self.builder.roots[source]  # type: ignore[index]
            current.extend(fingerprint_skill_root(root, source))  # type: ignore[arg-type]
        fingerprint = tuple(sorted(set(current)))
        if fingerprint == self.snapshot.fingerprint:
            return False
        try:
            candidate = self.builder.build(generation=self.snapshot.generation + 1)
        except SkillConfigError as exc:
            self.reload_errors += 1
            if state is not None:
                state.reload_error = str(exc)
            return False
        self.snapshot = candidate
        if state is not None:
            self._refresh_active(state)
            state.reload_error = ""
            state.catalog_generation = candidate.generation
        return True

    def clear_state(self, state: SkillRuntimeState) -> None:
        state.active.clear()
        state.next_activation_order = 0
        state.turn_model_override = None
        state.reload_error = ""
        state.catalog_generation = self.snapshot.generation

    def _refresh_active(self, state: SkillRuntimeState) -> None:
        refreshed: dict[str, ActiveSkill] = {}
        for name, active in state.active.items():
            definition = self.snapshot.definitions.get(name)
            if definition is None or definition.mode != "shared":
                continue
            refreshed[name] = replace(
                active,
                definition=definition,
                rendered_body=render_skill_body(definition, active.arguments),
            )
        state.active = refreshed
        if state.turn_model_override and not any(
            item.definition.model == state.turn_model_override for item in refreshed.values()
        ):
            state.turn_model_override = None


def default_skill_roots(workspace: Path) -> dict[SkillSource, Path]:
    return {
        "builtin": Path(__file__).parent / "builtin",
        "user": Path.home() / ".huicode" / "skills",
        "project": workspace / ".huicode" / "skills",
    }
