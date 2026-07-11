import unittest

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from huicode.commands import (
    CommandAlias,
    CommandRegistry,
    CommandResult,
    CommandSpec,
    CommandType,
    SlashCommandCompleter,
)


def handler(parsed, context):  # noqa: ANN001
    return CommandResult()


def spec(name, *, hidden=False, aliases=()):  # noqa: ANN001
    return CommandSpec(
        name=name,
        aliases=aliases,
        description=f"{name} description",
        usage=f"/{name}",
        command_type=CommandType.LOCAL,
        handler=handler,
        hidden=hidden,
    )


class CommandCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        registry = CommandRegistry()
        registry.register(spec("review"))
        registry.register(spec("session", aliases=(CommandAlias("sess"),)))
        registry.register(spec("status"))
        registry.register(spec("resume", hidden=True))
        self.completer = SlashCommandCompleter(registry)

    def complete(self, text: str):
        return list(
            self.completer.get_completions(
                Document(text, cursor_position=len(text)),
                CompleteEvent(completion_requested=True),
            )
        )

    def test_single_and_multiple_matches(self) -> None:
        self.assertEqual([item.text for item in self.complete("/rev")], ["/review"])
        self.assertEqual(
            [item.text for item in self.complete("/s")],
            ["/session", "/sess", "/status"],
        )

    def test_case_insensitive_and_hidden_filtering(self) -> None:
        self.assertEqual([item.text for item in self.complete("/RE")], ["/review"])
        self.assertNotIn("/resume", [item.text for item in self.complete("/")])

    def test_parameter_area_and_plain_text_have_no_completions(self) -> None:
        self.assertEqual(self.complete("/review api"), [])
        self.assertEqual(self.complete("review"), [])


if __name__ == "__main__":
    unittest.main()
