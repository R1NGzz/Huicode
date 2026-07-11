import unittest

from huicode.commands import CommandParser


class CommandParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = CommandParser()

    def test_empty_and_plain_input_return_none(self) -> None:
        self.assertIsNone(self.parser.parse(""))
        self.assertIsNone(self.parser.parse("   "))
        self.assertIsNone(self.parser.parse("review /status"))

    def test_parses_case_insensitive_name_and_preserves_arguments(self) -> None:
        parsed = self.parser.parse("  /ReView   Focus On API  ")

        self.assertEqual(parsed.name, "review")
        self.assertEqual(parsed.arguments, "Focus On API")
        self.assertEqual(parsed.raw, "  /ReView   Focus On API  ")

    def test_parses_bare_slash_for_unknown_command_handling(self) -> None:
        parsed = self.parser.parse("/")

        self.assertEqual(parsed.name, "")
        self.assertEqual(parsed.arguments, "")


if __name__ == "__main__":
    unittest.main()
