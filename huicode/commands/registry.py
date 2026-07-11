from __future__ import annotations

from dataclasses import replace

from .types import CommandAlias, CommandSpec, normalize_command_name


class CommandRegistrationError(ValueError):
    pass


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: list[CommandSpec] = []
        self._lookup: dict[str, CommandSpec] = {}
        self._owners: dict[str, str] = {}

    def register(self, spec: CommandSpec) -> None:
        try:
            name = normalize_command_name(spec.name)
            aliases = tuple(
                CommandAlias(normalize_command_name(alias.name), alias.hidden)
                for alias in spec.aliases
            )
        except ValueError as exc:
            raise CommandRegistrationError(str(exc)) from exc

        normalized = replace(spec, name=name, aliases=aliases)
        keys = [name, *(alias.name for alias in aliases)]
        if len(set(keys)) != len(keys):
            duplicate = next(key for key in keys if keys.count(key) > 1)
            raise CommandRegistrationError(
                f"命令 /{name} 内部名称或别名重复: /{duplicate}"
            )
        for key in keys:
            if key in self._lookup:
                owner = self._owners[key]
                raise CommandRegistrationError(
                    f"命令键 /{key} 冲突: 已由 /{owner} 登记，不能再登记到 /{name}"
                )

        self._commands.append(normalized)
        for key in keys:
            self._lookup[key] = normalized
            self._owners[key] = name

    def register_many(self, specs: list[CommandSpec] | tuple[CommandSpec, ...]) -> None:
        for spec in specs:
            self.register(spec)

    def resolve(self, name: str) -> CommandSpec | None:
        candidate = name.strip()
        if candidate.startswith("/"):
            candidate = candidate[1:]
        try:
            key = normalize_command_name(candidate)
        except ValueError:
            return None
        return self._lookup.get(key)

    def commands(self) -> tuple[CommandSpec, ...]:
        return tuple(self._commands)

    def visible_commands(self) -> tuple[CommandSpec, ...]:
        return tuple(spec for spec in self._commands if not spec.hidden)

    def completion_entries(self) -> tuple[tuple[str, CommandSpec], ...]:
        entries: list[tuple[str, CommandSpec]] = []
        for spec in self._commands:
            if spec.hidden:
                continue
            entries.append((spec.name, spec))
            entries.extend(
                (alias.name, spec)
                for alias in spec.aliases
                if not alias.hidden
            )
        return tuple(entries)
