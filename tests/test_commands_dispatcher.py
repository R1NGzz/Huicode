import unittest

from huicode.commands import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    CommandSpec,
    CommandType,
    InputRouter,
    RouteKind,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.messages = []
        self.sent = []
        self.mode = "default"
        self.refresh_count = 0
        self.exit_requested = False

    def show_message(self, message, *, error=False):  # noqa: ANN001
        self.messages.append((message, error))

    def send_user_message(self, message):  # noqa: ANN001
        self.sent.append(message)

    def get_mode(self):
        return self.mode

    def set_mode(self, mode):  # noqa: ANN001
        self.mode = mode

    def get_token_status(self):
        return {}

    def refresh_status(self):
        self.refresh_count += 1

    def request_exit(self):
        self.exit_requested = True


class CommandDispatcherTests(unittest.TestCase):
    def make_context(self, handler):  # noqa: ANN001
        registry = CommandRegistry()
        registry.register(
            CommandSpec(
                name="test",
                description="test",
                usage="/test",
                command_type=CommandType.LOCAL,
                handler=handler,
            )
        )
        runtime = FakeRuntime()
        return InputRouter(registry), CommandContext(runtime, runtime, registry), runtime

    def test_routes_plain_messages_and_ignores_empty_input(self) -> None:
        router, context, runtime = self.make_context(lambda parsed, ctx: CommandResult())

        empty = router.route("   ", context)
        message = router.route("Hello API", context)

        self.assertEqual(empty.kind, RouteKind.IGNORED)
        self.assertEqual(message.kind, RouteKind.MESSAGE)
        self.assertEqual(runtime.sent, ["Hello API"])

    def test_routes_command_and_renders_result(self) -> None:
        router, context, runtime = self.make_context(
            lambda parsed, ctx: CommandResult(message=f"args={parsed.arguments}")
        )

        result = router.route("/TEST Focus", context)

        self.assertEqual(result.kind, RouteKind.COMMAND)
        self.assertEqual(runtime.sent, [])
        self.assertEqual(runtime.messages, [("args=Focus", False)])

    def test_unknown_command_does_not_send_message(self) -> None:
        router, context, runtime = self.make_context(lambda parsed, ctx: CommandResult())

        result = router.route("/missing", context)

        self.assertFalse(result.command_result.ok)
        self.assertEqual(runtime.sent, [])
        self.assertIn("/help", runtime.messages[0][0])

    def test_handler_exception_is_contained(self) -> None:
        def broken(parsed, context):  # noqa: ANN001
            raise RuntimeError("boom")

        router, context, runtime = self.make_context(broken)

        first = router.route("/test", context)
        second = router.route("still alive", context)

        self.assertFalse(first.command_result.ok)
        self.assertEqual(second.kind, RouteKind.MESSAGE)
        self.assertEqual(runtime.sent, ["still alive"])
        self.assertIn("boom", runtime.messages[0][0])

    def test_exit_result_requests_service_exit(self) -> None:
        router, context, runtime = self.make_context(
            lambda parsed, ctx: CommandResult(exit_requested=True)
        )

        router.route("/test", context)

        self.assertTrue(runtime.exit_requested)


if __name__ == "__main__":
    unittest.main()
