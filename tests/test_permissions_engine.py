import tempfile
import unittest
from pathlib import Path

from huicode.permissions import PermissionConfirmation, PermissionContext, PermissionRule
from huicode.permissions.engine import evaluate_permission, permission_denied_result
from huicode.providers.base import ToolCall
from huicode.tools.base import ToolContext
from huicode.tools.files import ReadFileTool, WriteFileTool
from huicode.tools.shell import RunCommandTool


class FakeConfirmer:
    def __init__(self, action: str) -> None:
        self.action = action
        self.requests = []

    def confirm(self, request):
        self.requests.append(request)
        return PermissionConfirmation(self.action)


class PermissionEngineTests(unittest.TestCase):
    def test_disabled_permission_context_allows(self) -> None:
        decision = evaluate_permission(
            ToolCall("1", "Bash", {"command": "git status"}),
            RunCommandTool(),
            ToolContext(Path.cwd()),
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.source, "disabled")

    def test_blacklist_overrides_allow_rule_and_permissive_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = ToolContext(
                Path(directory),
                permissions=PermissionContext(
                    workspace=Path(directory),
                    mode="permissive",
                    rules=[PermissionRule("Bash", "git reset --hard", "allow", source="local")],
                ),
            )

            decision = evaluate_permission(
                ToolCall("1", "Bash", {"command": "git reset --hard"}),
                RunCommandTool(),
                context,
            )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.source, "blacklist")

    def test_session_rule_overrides_persistent_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = ToolContext(
                Path(directory),
                permissions=PermissionContext(
                    workspace=Path(directory),
                    rules=[PermissionRule("Bash", "git *", "deny", source="local")],
                    session_rules=[PermissionRule("Bash", "git status", "allow", source="session")],
                ),
            )

            decision = evaluate_permission(
                ToolCall("1", "Bash", {"command": "git status"}),
                RunCommandTool(),
                context,
            )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.source, "session_rule")

    def test_permission_modes_for_unmatched_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            strict = ToolContext(workspace, permissions=PermissionContext(workspace=workspace, mode="strict"))
            permissive = ToolContext(workspace, permissions=PermissionContext(workspace=workspace, mode="permissive"))
            default_read = ToolContext(workspace, permissions=PermissionContext(workspace=workspace, mode="default"))

            self.assertFalse(evaluate_permission(ToolCall("1", "Bash", {"command": "git status"}), RunCommandTool(), strict).allowed)
            self.assertTrue(evaluate_permission(ToolCall("1", "Bash", {"command": "git status"}), RunCommandTool(), permissive).allowed)
            self.assertTrue(evaluate_permission(ToolCall("1", "Read", {"path": "README.md"}), ReadFileTool(), default_read).allowed)

    def test_default_mode_confirms_side_effect_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            confirmer = FakeConfirmer("session")
            permission_context = PermissionContext(workspace=workspace, mode="default", confirmer=confirmer)
            context = ToolContext(workspace, permissions=permission_context)

            first = evaluate_permission(ToolCall("1", "Write", {"path": "a.txt"}), WriteFileTool(), context)
            second = evaluate_permission(ToolCall("2", "Write", {"path": "a.txt"}), WriteFileTool(), context)

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertEqual(len(confirmer.requests), 1)
        self.assertEqual(permission_context.session_rules[0].tool, "Write")

    def test_permission_denied_result_is_structured(self) -> None:
        decision = evaluate_permission(
            ToolCall("1", "Bash", {"command": "git status"}),
            RunCommandTool(),
            ToolContext(Path.cwd(), permissions=PermissionContext(Path.cwd(), mode="strict")),
        )
        result = permission_denied_result(ToolCall("1", "Bash", {"command": "git status"}), decision)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "permission_denied")
        self.assertEqual(result.error.details["source"], "mode")


if __name__ == "__main__":
    unittest.main()
