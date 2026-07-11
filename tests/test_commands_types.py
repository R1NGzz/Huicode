import unittest

from huicode.commands import (
    CommandAlias,
    CommandResult,
    CommandSpec,
    CommandType,
    ParsedCommand,
    normalize_command_name,
)


def noop_handler(parsed, context):  # noqa: ANN001
    return CommandResult()


class CommandTypesTests(unittest.TestCase):
    def test_command_metadata_and_defaults(self) -> None:
        spec = CommandSpec(
            name="help",
            aliases=(CommandAlias("h"),),
            description="帮助",
            usage="/help [command]",
            command_type=CommandType.LOCAL,
            handler=noop_handler,
        )
        parsed = ParsedCommand("/help", "help")

        self.assertEqual(spec.aliases[0].name, "h")
        self.assertFalse(spec.hidden)
        self.assertEqual(parsed.arguments, "")
        self.assertTrue(CommandResult().ok)

    def test_normalize_command_name(self) -> None:
        self.assertEqual(normalize_command_name(" StAtUs "), "status")
        for invalid in ("", "/help", "bad name", "中文"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_command_name(invalid)


if __name__ == "__main__":
    unittest.main()
