import unittest

from huicode.commands import (
    CommandAlias,
    CommandRegistrationError,
    CommandRegistry,
    CommandResult,
    CommandSpec,
    CommandType,
)


def noop_handler(parsed, context):  # noqa: ANN001
    return CommandResult()


def make_spec(name: str, *aliases: CommandAlias, hidden: bool = False) -> CommandSpec:
    return CommandSpec(
        name=name,
        aliases=tuple(aliases),
        description=name,
        usage=f"/{name}",
        command_type=CommandType.LOCAL,
        handler=noop_handler,
        hidden=hidden,
    )


class CommandRegistryTests(unittest.TestCase):
    def test_resolves_names_and_aliases_case_insensitively(self) -> None:
        registry = CommandRegistry()
        registry.register(make_spec("Status", CommandAlias("st")))

        self.assertEqual(registry.resolve("STATUS").name, "status")
        self.assertEqual(registry.resolve("/ST").name, "status")
        self.assertIsNone(registry.resolve("missing"))

    def test_rejects_name_and_alias_conflicts(self) -> None:
        cases = [
            (make_spec("status"), make_spec("STATUS")),
            (make_spec("status", CommandAlias("st")), make_spec("st")),
            (make_spec("status"), make_spec("other", CommandAlias("STATUS"))),
            (
                make_spec("status", CommandAlias("st")),
                make_spec("other", CommandAlias("ST")),
            ),
        ]
        for first, second in cases:
            with self.subTest(first=first.name, second=second.name):
                registry = CommandRegistry()
                registry.register(first)
                with self.assertRaisesRegex(CommandRegistrationError, "冲突"):
                    registry.register(second)

    def test_rejects_internal_duplicates_and_invalid_names(self) -> None:
        registry = CommandRegistry()
        with self.assertRaises(CommandRegistrationError):
            registry.register(make_spec("help", CommandAlias("HELP")))
        with self.assertRaises(CommandRegistrationError):
            registry.register(make_spec("help", CommandAlias("h"), CommandAlias("H")))
        with self.assertRaises(CommandRegistrationError):
            registry.register(make_spec("/bad"))

    def test_visible_and_completion_entries_filter_hidden_items(self) -> None:
        registry = CommandRegistry()
        registry.register(
            make_spec(
                "help",
                CommandAlias("h"),
                CommandAlias("legacy-help", hidden=True),
            )
        )
        registry.register(make_spec("exit", hidden=True))

        self.assertEqual([spec.name for spec in registry.visible_commands()], ["help"])
        self.assertEqual(
            [name for name, _ in registry.completion_entries()],
            ["help", "h"],
        )


if __name__ == "__main__":
    unittest.main()
