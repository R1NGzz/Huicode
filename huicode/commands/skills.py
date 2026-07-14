from __future__ import annotations

from huicode.skills.types import SkillCatalogSnapshot, SkillDefinition

from .registry import CommandRegistry
from .types import CommandResult, CommandSpec, CommandType, ParsedCommand
from .ui import CommandContext


def registry_with_skill_commands(
    base_registry: CommandRegistry,
    snapshot: SkillCatalogSnapshot,
) -> CommandRegistry:
    registry = base_registry.clone()
    for definition in snapshot.definitions.values():
        registry.register(_skill_spec(definition))
    return registry


def _skill_spec(definition: SkillDefinition) -> CommandSpec:
    def run_skill(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
        message = context.services.run_skill(definition.name, parsed.arguments)
        return CommandResult(message=message)

    return CommandSpec(
        name=definition.name,
        description=definition.description,
        usage=f"/{definition.name} [arguments]",
        command_type=CommandType.SKILL,
        handler=run_skill,
        argument_hint="[arguments]",
    )
