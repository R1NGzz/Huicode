import json
import tempfile
import unittest
from pathlib import Path

from huicode.hooks.events import event_payload, make_event, sanitize_payload, tool_data
from huicode.providers.base import ToolCall
from huicode.tools.base import ToolResult


class HookEventTests(unittest.TestCase):
    def test_payload_is_serializable_redacted_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            event = make_event(
                "agent_error",
                session_id="session",
                workspace=Path(directory),
                data={
                    "error": {"summary": "x" * 5000, "api_key": "top-secret"},
                    "headers": {"Authorization": "Bearer secret"},
                    "plain": "api_key=inline-secret Bearer another-secret",
                },
            )
            payload = event_payload(event)
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("top-secret", encoded)
        self.assertNotIn("Bearer secret", encoded)
        self.assertNotIn("inline-secret", encoded)
        self.assertNotIn("another-secret", encoded)
        self.assertIn("[REDACTED]", encoded)
        self.assertLess(len(payload["error"]["summary"]), 4200)

    def test_tool_data_uses_canonical_name_and_result(self) -> None:
        call = ToolCall("call-1", "Glob", {"pattern": "**/*.py", "token": "hidden"})
        result = ToolResult.failure("permission_denied", "no")
        data = tool_data(call, result, source="permission")
        self.assertEqual(data["tool"]["name"], "Find")
        self.assertEqual(data["tool"]["original_name"], "Glob")
        self.assertEqual(data["tool"]["canonical_name"], "Find")
        self.assertEqual(data["tool"]["arguments"]["token"], "[REDACTED]")
        self.assertEqual(data["result"]["source"], "permission")

    def test_collections_are_truncated(self) -> None:
        safe = sanitize_payload({"items": list(range(80))}, max_items=5)
        self.assertEqual(len(safe["items"]), 6)


if __name__ == "__main__":
    unittest.main()
