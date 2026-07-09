import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from huicode.config import MemoryConfig
from huicode.memory.codec import message_to_json
from huicode.memory.sessions import SessionStore
from huicode.providers.base import ConversationMessage, ToolCall
from huicode.tools.base import ToolResult


class MemorySessionTests(unittest.TestCase):
    def test_append_list_and_roundtrip_messages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            store = SessionStore(workspace, MemoryConfig(enabled=True))
            recorder = store.open("20260709-010101-abcd")
            recorder.append_message(ConversationMessage(role="user", content="hello"))
            recorder.append_message(
                ConversationMessage(
                    role="assistant",
                    content="",
                    thinking="think",
                    thinking_signature="sig",
                    tool_calls=[ToolCall("call_1", "Read", {"path": "a.txt"})],
                )
            )
            recorder.append_message(
                ConversationMessage(
                    role="tool",
                    content="ok",
                    tool_call_id="call_1",
                    tool_name="Read",
                    tool_result=ToolResult.success({"content": "hello"}, "ok"),
                )
            )
            recorder.close()

            summaries = store.list_sessions()
            recovered = store.recover("20260709-010101-abcd")

        self.assertEqual(summaries[0].title, "hello")
        self.assertEqual(summaries[0].message_count, 3)
        self.assertEqual(len(recovered.messages), 3)
        self.assertEqual(recovered.messages[1].thinking, "think")
        self.assertEqual(recovered.messages[2].tool_result.summary, "ok")

    def test_bad_lines_are_skipped_and_unmatched_tools_are_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            store = SessionStore(workspace, MemoryConfig(enabled=True))
            path = store.root / "20260709-010101-bad1.jsonl"
            path.parent.mkdir(parents=True)
            record = {
                "type": "message",
                "session_id": "20260709-010101-bad1",
                "ts": datetime.now(timezone.utc).isoformat(),
                "message": message_to_json(ConversationMessage(role="user", content="safe")),
            }
            broken = {
                "type": "message",
                "session_id": "20260709-010101-bad1",
                "ts": datetime.now(timezone.utc).isoformat(),
                "message": message_to_json(
                    ConversationMessage(
                        role="assistant",
                        content="",
                        tool_calls=[ToolCall("call_1", "Read", {"path": "a.txt"})],
                    )
                ),
            }
            path.write_text(json.dumps(record, ensure_ascii=False) + "\n{bad json\n" + json.dumps(broken, ensure_ascii=False), encoding="utf-8")

            recovered = store.recover("20260709-010101-bad1")

        self.assertEqual(recovered.skipped_bad_lines, 1)
        self.assertTrue(recovered.truncated)
        self.assertEqual([message.role for message in recovered.messages], ["user"])

    def test_stale_notice_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            settings = MemoryConfig(enabled=True, stale_session_notice_hours=1, session_retention_days=30)
            store = SessionStore(workspace, settings)
            old = datetime.now(timezone.utc) - timedelta(days=40)
            recent = datetime.now(timezone.utc)
            for session_id, ts in [
                ("20260101-010101-old1", old),
                ("20260709-010101-active", old),
                ("20260709-020202-new1", recent),
            ]:
                path = store.root / f"{session_id}.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                record = {
                    "type": "message",
                    "session_id": session_id,
                    "ts": ts.isoformat(),
                    "message": message_to_json(ConversationMessage(role="user", content=session_id)),
                }
                path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

            recovered = store.recover("20260101-010101-old1", now=recent)
            removed = store.cleanup_expired("20260709-010101-active", now=recent)

            self.assertTrue(recovered.time_gap_inserted)
            self.assertIn("session_time_gap", recovered.messages[-1].content)
            self.assertEqual(removed, 1)
            self.assertFalse((store.root / "20260101-010101-old1.jsonl").exists())
            self.assertTrue((store.root / "20260709-010101-active.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
