import unittest

from huicode.commands import (
    CommandContext,
    CommandDispatcher,
    CommandParser,
    CommandType,
    create_builtin_registry,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.messages = []
        self.sent = []
        self.mode = "default"
        self.refresh_count = 0
        self.exit_requested = False
        self.calls = []

    def show_message(self, message, *, error=False):  # noqa: ANN001
        self.messages.append((message, error))

    def send_user_message(self, message):  # noqa: ANN001
        self.sent.append(message)

    def get_mode(self):
        return self.mode

    def set_mode(self, mode):  # noqa: ANN001
        self.mode = mode

    def get_token_status(self):
        return {"last": 10, "window": 100}

    def refresh_status(self):
        self.refresh_count += 1

    def compact(self):
        self.calls.append(("compact", ""))
        return "compacted"

    def clear(self):
        self.calls.append(("clear", ""))
        return "cleared"

    def session(self, arguments):  # noqa: ANN001
        self.calls.append(("session", arguments))
        return f"session:{arguments}"

    def memory(self, arguments):  # noqa: ANN001
        self.calls.append(("memory", arguments))
        return f"memory:{arguments}"

    def permission(self, arguments):  # noqa: ANN001
        self.calls.append(("permission", arguments))
        return f"permission:{arguments}"

    def status(self):
        self.calls.append(("status", ""))
        return "status"

    def context_status(self):
        self.calls.append(("context", ""))
        return "context"

    def toggle_verbose(self):
        self.calls.append(("verbose", ""))
        return "verbose"

    def last(self, arguments):  # noqa: ANN001
        self.calls.append(("last", arguments))
        return f"last:{arguments}"

    def request_exit(self):
        self.exit_requested = True

    def run_skill(self, name, arguments):  # noqa: ANN001
        self.calls.append(("skill", name, arguments))
        return f"skill:{name}:{arguments}"

    def skill_status(self, arguments):  # noqa: ANN001
        self.calls.append(("skill_status", arguments))
        return f"skills:{arguments}"

    def agent_status(self, arguments):  # noqa: ANN001
        self.calls.append(("agents", arguments))
        return f"agents:{arguments}"

    def task_status(self, arguments):  # noqa: ANN001
        self.calls.append(("tasks", arguments))
        return f"tasks:{arguments}"


class BuiltinCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = create_builtin_registry()
        self.runtime = FakeRuntime()
        self.context = CommandContext(self.runtime, self.runtime, self.registry)
        self.dispatcher = CommandDispatcher(self.registry)
        self.parser = CommandParser()

    def run_command(self, text: str):
        return self.dispatcher.dispatch(self.parser.parse(text), self.context)

    def test_registers_twelve_core_visible_commands(self) -> None:
        visible = self.registry.visible_commands()

        self.assertEqual(
            [spec.name for spec in visible],
            [
                "help",
                "compact",
                "clear",
                "plan",
                "do",
                "session",
                "memory",
                "permission",
                "status",
                "skill",
                "agents",
                "tasks",
            ],
        )
        self.assertEqual({spec.command_type for spec in visible}, {CommandType.LOCAL, CommandType.STATE})
        self.assertTrue(all(spec.description and spec.usage and spec.handler for spec in visible))

    def test_help_groups_visible_commands_and_hides_compatibility(self) -> None:
        self.run_command("/help")
        text = self.runtime.messages[-1][0]

        self.assertIn("本地命令", text)
        self.assertIn("状态命令", text)
        self.assertNotIn("Skill 命令", text)
        self.assertNotIn("/resume", text)
        self.assertNotIn("/exit", text)

    def test_help_detail_and_hidden_rejection(self) -> None:
        self.run_command("/help permission")
        detail = self.runtime.messages[-1][0]
        self.run_command("/help resume")

        self.assertIn("/permission", detail)
        self.assertIn("类型: 状态", detail)
        self.assertTrue(self.runtime.messages[-1][1])

    def test_plan_and_do_only_switch_mode(self) -> None:
        self.run_command("/plan")
        self.assertEqual(self.runtime.mode, "plan")
        self.run_command("/do")

        self.assertEqual(self.runtime.mode, "default")
        self.assertEqual(self.runtime.sent, [])
        self.assertEqual(self.runtime.refresh_count, 2)

    def test_argument_validation_prevents_service_calls(self) -> None:
        for command in ("/plan task", "/do now", "/session bad", "/memory bad", "/permission wild", "/status now"):
            with self.subTest(command=command):
                before = len(self.runtime.calls)
                result = self.run_command(command)
                self.assertFalse(result.ok)
                self.assertEqual(len(self.runtime.calls), before)

    def test_session_memory_permission_and_status_dispatch(self) -> None:
        for command in (
            "/session",
            "/session clean",
            "/session resume Session-ID",
            "/memory",
            "/memory update",
            "/memory rebuild",
            "/permission",
            "/permission strict",
            "/status",
            "/skill",
            "/skill review",
        ):
            self.run_command(command)

        self.assertIn(("session", "resume Session-ID"), self.runtime.calls)
        self.assertIn(("memory", "update"), self.runtime.calls)
        self.assertIn(("permission", "strict"), self.runtime.calls)
        self.assertIn(("status", ""), self.runtime.calls)
        self.assertIn(("skill_status", "review"), self.runtime.calls)
        self.assertEqual(self.runtime.sent, [])

    def test_hidden_compatibility_commands_delegate(self) -> None:
        for command in (
            "/sessions clean",
            "/resume Session-ID",
            "/permissions permissive",
            "/perm default",
            "/config",
            "/context",
            "/verbose",
            "/last 2",
        ):
            self.run_command(command)

        self.assertIn(("session", "clean"), self.runtime.calls)
        self.assertIn(("session", "resume Session-ID"), self.runtime.calls)
        self.assertIn(("permission", "permissive"), self.runtime.calls)
        self.assertIn(("status", ""), self.runtime.calls)
        self.assertIn(("last", "2"), self.runtime.calls)

    def test_exit_and_quit_request_exit(self) -> None:
        self.run_command("/exit")
        self.assertTrue(self.runtime.exit_requested)


if __name__ == "__main__":
    unittest.main()
