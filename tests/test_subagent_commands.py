import unittest

from huicode.commands import CommandContext, CommandDispatcher, CommandParser, create_builtin_registry
from tests.test_commands_builtin import FakeRuntime


class SubagentCommandTests(unittest.TestCase):
    def test_agents_and_tasks_dispatch_locally(self) -> None:
        registry = create_builtin_registry()
        runtime = FakeRuntime()
        context = CommandContext(runtime, runtime, registry)
        dispatcher = CommandDispatcher(registry)
        parser = CommandParser()

        dispatcher.dispatch(parser.parse("/agents explorer"), context)
        dispatcher.dispatch(parser.parse("/tasks task-123"), context)

        self.assertIn(("agents", "explorer"), runtime.calls)
        self.assertIn(("tasks", "task-123"), runtime.calls)
        self.assertEqual(runtime.sent, [])

    def test_help_lists_subagent_commands(self) -> None:
        registry = create_builtin_registry()
        runtime = FakeRuntime()
        context = CommandContext(runtime, runtime, registry)
        CommandDispatcher(registry).dispatch(CommandParser().parse("/help"), context)
        text = runtime.messages[-1][0]
        self.assertIn("/agents [name]", text)
        self.assertIn("/tasks [task-id]", text)


if __name__ == "__main__":
    unittest.main()
