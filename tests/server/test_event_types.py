"""T7 统一 Runtime Event 的类型、序列化与映射。

验收要求是"覆盖所有事件类型的序列化、反序列化和未知事件兼容行为"，
所以每个已知类型都跑一遍 round-trip，而不是只测一两个代表。
"""

import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from huicode.agent_events import AgentEvent
from huicode.providers.base import ToolCall
from huicode.server.events.mapper import map_agent_event
from huicode.server.events.types import (
    DEFAULT_VISIBILITY,
    KNOWN_EVENT_TYPES,
    TERMINAL_EVENT_TYPES,
    UNKNOWN_EVENT_TYPE,
    EventDecodeError,
    RuntimeEvent,
    visible_to,
)
from huicode.tools.base import ToolError, ToolResult

SESSION = uuid4()
RUN = uuid4()
MOMENT = datetime(2026, 9, 23, 10, 30, tzinfo=timezone.utc)


def make_event(**overrides):
    base = dict(
        type="assistant_text_delta", session_id=SESSION, run_id=RUN,
        sequence=1, payload={"delta": "hi"}, occurred_at=MOMENT,
    )
    base.update(overrides)
    return RuntimeEvent(**base)


class SerialisationTests(unittest.TestCase):
    def test_every_known_type_round_trips(self):
        for event_type in sorted(KNOWN_EVENT_TYPES):
            with self.subTest(event_type=event_type):
                original = make_event(type=event_type, payload={"k": event_type})
                restored = RuntimeEvent.from_dict(original.to_dict())
                self.assertEqual(restored, original)

    def test_json_round_trip(self):
        original = make_event(payload={"delta": "中文内容", "n": 3})
        restored = RuntimeEvent.from_json(original.to_json())
        self.assertEqual(restored, original)

    def test_run_id_may_be_absent(self):
        original = make_event(run_id=None)
        restored = RuntimeEvent.from_dict(original.to_dict())
        self.assertIsNone(restored.run_id)
        self.assertEqual(restored, original)

    def test_occurred_at_is_normalised_to_aware_utc(self):
        """naive 时间必须被当成 UTC，否则之后与 now(utc) 比较会抛 TypeError。"""
        naive = datetime(2026, 9, 23, 10, 30)
        event = make_event(occurred_at=naive)
        self.assertIsNotNone(event.occurred_at.tzinfo)
        self.assertEqual(event.occurred_at, naive.replace(tzinfo=timezone.utc))

        restored = RuntimeEvent.from_dict({**make_event().to_dict(), "occurred_at": "2026-09-23T10:30:00"})
        self.assertIsNotNone(restored.occurred_at.tzinfo)

    def test_timezone_is_converted_not_dropped(self):
        offset = timezone(timedelta(hours=8))
        event = make_event(occurred_at=datetime(2026, 9, 23, 18, 30, tzinfo=offset))
        self.assertEqual(event.occurred_at, MOMENT)


class VisibilityTests(unittest.TestCase):
    def test_default_visibility_comes_from_type(self):
        for event_type in sorted(KNOWN_EVENT_TYPES):
            with self.subTest(event_type=event_type):
                self.assertEqual(make_event(type=event_type).visibility, DEFAULT_VISIBILITY[event_type])

    def test_unknown_visibility_value_fails_closed(self):
        event = make_event(visibility="public")
        self.assertEqual(event.visibility, "internal")

    def test_role_visibility_matrix(self):
        self.assertTrue(visible_to(make_event(visibility="user"), "viewer"))
        self.assertFalse(visible_to(make_event(visibility="admin"), "member"))
        self.assertTrue(visible_to(make_event(visibility="admin"), "admin"))
        self.assertTrue(visible_to(make_event(visibility="admin"), "owner"))
        for role in ("viewer", "member", "admin", "owner"):
            self.assertFalse(visible_to(make_event(visibility="internal"), role), role)

    def test_terminal_flag(self):
        for event_type in TERMINAL_EVENT_TYPES:
            self.assertTrue(make_event(type=event_type).is_terminal)
        self.assertFalse(make_event(type="run_started").is_terminal)


class DecodeFailureTests(unittest.TestCase):
    def test_unknown_type_is_quarantined_not_rejected(self):
        """不认识的类型不能丢掉整条事件，也不能让普通成员看到它的载荷。"""
        payload = {
            "type": "something_from_the_future",
            "session_id": str(SESSION),
            "sequence": 7,
            "payload": {"secret": "value"},
        }
        event = RuntimeEvent.from_dict(payload)
        self.assertEqual(event.type, UNKNOWN_EVENT_TYPE)
        self.assertEqual(event.visibility, "internal")
        self.assertEqual(event.payload["original_type"], "something_from_the_future")
        self.assertEqual(event.payload["raw"], {"secret": "value"})
        self.assertFalse(visible_to(event, "owner"))

    def test_unknown_type_ignores_a_claimed_user_visibility(self):
        """生产者自称 user 可见也没用：我们看不懂的载荷一律 internal。"""
        event = RuntimeEvent.from_dict({
            "type": "future_type", "session_id": str(SESSION),
            "sequence": 1, "payload": {}, "visibility": "user",
        })
        self.assertEqual(event.visibility, "internal")

    def test_missing_or_invalid_fields_raise(self):
        good = make_event().to_dict()
        for field in ("type", "session_id", "sequence"):
            broken = dict(good)
            broken.pop(field, None)
            with self.subTest(field=field), self.assertRaises(EventDecodeError):
                RuntimeEvent.from_dict(broken)

        for field, value in (
            ("session_id", "not-a-uuid"),
            ("sequence", "1"),
            ("sequence", -1),
            ("payload", ["not", "a", "dict"]),
            ("occurred_at", "not-a-date"),
        ):
            with self.subTest(field=field), self.assertRaises(EventDecodeError):
                RuntimeEvent.from_dict({**good, field: value})

    def test_error_message_does_not_echo_the_payload(self):
        secret = "sk-live-should-not-appear"
        try:
            RuntimeEvent.from_dict({"type": "run_started", "session_id": secret, "sequence": 1})
        except EventDecodeError as exc:
            self.assertNotIn(secret, str(exc))
        else:
            self.fail("应当抛出 EventDecodeError")

    def test_from_json_rejects_garbage(self):
        with self.assertRaises(EventDecodeError):
            RuntimeEvent.from_json("{not json")


class MapperTests(unittest.TestCase):
    def map_one(self, agent_event, sequence=1):
        return map_agent_event(agent_event, session_id=SESSION, run_id=RUN, sequence=sequence)

    def test_every_agent_kind_maps_to_an_expected_type(self):
        cases = [
            (AgentEvent(kind="text", text="hello"), "assistant_text_delta"),
            (AgentEvent(kind="thinking", text="hmm"), "thinking_delta"),
            (AgentEvent(kind="tool_call", tool_call=ToolCall("c1", "Read", {"path": "a.py"})), "tool_call_started"),
            (AgentEvent(kind="tool_result", tool_call=ToolCall("c1", "Read", {}),
                        tool_result=ToolResult.success({"x": 1}, "读取完成")), "tool_call_finished"),
            (AgentEvent(kind="progress", text="进行中"), "tool_call_progress"),
            (AgentEvent(kind="usage", data={"usage": {"input_tokens": 10}}), "usage_updated"),
            (AgentEvent(kind="context", data={"before": 100, "after": 40}), "context_compacted"),
            (AgentEvent(kind="memory", data={"message": "记住了一件事"}), "memory_updated"),
            (AgentEvent(kind="error", data={"message": "上游返回 500"}), "error"),
            (AgentEvent(kind="done", stop_reason="final"), "run_completed"),
        ]
        for agent_event, expected in cases:
            with self.subTest(kind=agent_event.kind):
                mapped = self.map_one(agent_event)
                self.assertIsNotNone(mapped)
                self.assertEqual(mapped.type, expected)
                self.assertEqual(mapped.session_id, SESSION)
                self.assertEqual(mapped.run_id, RUN)
                self.assertEqual(mapped.sequence, 1)

    def test_text_payload_carries_the_delta(self):
        mapped = self.map_one(AgentEvent(kind="text", text="片段"))
        self.assertEqual(mapped.payload["delta"], "片段")

    def test_empty_text_delta_produces_no_event(self):
        for kind in ("text", "thinking"):
            with self.subTest(kind=kind):
                self.assertIsNone(self.map_one(AgentEvent(kind=kind, text="")))

    def test_tool_arguments_are_included(self):
        """T11 的脱敏上线后这笔欠账还掉了：参数值进载荷，脱敏由写入路径负责。

        链路验证在 tests/server/test_scrubber.py 的
        `test_tool_arguments_are_scrubbed_on_the_way_to_the_database`——
        单独看这条只能说明"值被带上了"，说明不了"落库是安全的"。
        """
        call = ToolCall("c1", "Write", {"path": "a.py", "content": "hello"})
        mapped = self.map_one(AgentEvent(kind="tool_call", tool_call=call))

        self.assertEqual(mapped.payload["tool_name"], "Write")
        self.assertEqual(mapped.payload["tool_call_id"], "c1")
        self.assertEqual(mapped.payload["arguments"], {"path": "a.py", "content": "hello"})

    def test_oversized_arguments_fall_back_to_keys_only(self):
        """整份文件内容不该塞进事件表——订阅者会按 sequence 全量扫描它。"""
        call = ToolCall("c1", "Write", {"path": "big.py", "content": "x" * 10_000})
        mapped = self.map_one(AgentEvent(kind="tool_call", tool_call=call))

        self.assertTrue(mapped.payload["arguments_truncated"])
        self.assertEqual(mapped.payload["argument_keys"], ["content", "path"])
        self.assertNotIn("arguments", mapped.payload)

    def test_tool_failure_records_the_error_code(self):
        call = ToolCall("c1", "Shell", {"command": "false"})
        result = ToolResult(ok=False, error=ToolError(code="timeout", message="超时"))
        mapped = self.map_one(AgentEvent(kind="tool_result", tool_call=call, tool_result=result))
        self.assertFalse(mapped.payload["ok"])
        self.assertEqual(mapped.payload["error_code"], "timeout")

    def test_done_maps_by_stop_reason(self):
        cases = {
            "final": "run_completed",
            "cancelled": "run_cancelled",
            "error": "run_failed",
            "max_iterations": "run_failed",
            "unknown_tool_limit": "run_failed",
        }
        for stop_reason, expected in cases.items():
            with self.subTest(stop_reason=stop_reason):
                mapped = self.map_one(AgentEvent(kind="done", stop_reason=stop_reason))
                self.assertEqual(mapped.type, expected)
                self.assertEqual(mapped.payload["stop_reason"], stop_reason)

    def test_unrecognised_stop_reason_fails_rather_than_reports_success(self):
        """把不认识的停止原因报成"完成"是最糟的默认值。"""
        mapped = self.map_one(AgentEvent(kind="done", stop_reason="something_new"))
        self.assertEqual(mapped.type, "run_failed")
        self.assertEqual(mapped.payload["error_code"], "unknown_stop_reason")

    def test_max_iterations_exposes_a_budget_error_code(self):
        mapped = self.map_one(AgentEvent(kind="done", stop_reason="max_iterations"))
        self.assertEqual(mapped.payload["error_code"], "max_iterations_exceeded")

    def test_unknown_agent_kind_is_preserved_but_internal(self):
        mapped = self.map_one(AgentEvent(kind="brand_new_kind", data={"x": 1}))
        self.assertEqual(mapped.type, UNKNOWN_EVENT_TYPE)
        self.assertEqual(mapped.visibility, "internal")
        self.assertEqual(mapped.payload["original_kind"], "brand_new_kind")
        self.assertFalse(visible_to(mapped, "owner"))

    def test_iteration_is_carried_when_present(self):
        mapped = self.map_one(AgentEvent(kind="text", text="x", iteration=4))
        self.assertEqual(mapped.payload["iteration"], 4)
        absent = self.map_one(AgentEvent(kind="text", text="x"))
        self.assertNotIn("iteration", absent.payload)

    def test_long_payloads_are_bounded(self):
        mapped = self.map_one(AgentEvent(kind="text", text="x" * 50_000))
        self.assertLessEqual(len(mapped.payload["delta"]), 8192)

    def test_mapped_events_round_trip_through_json(self):
        mapped = self.map_one(AgentEvent(kind="tool_result",
                                         tool_call=ToolCall("c1", "Read", {"path": "a.py"}),
                                         tool_result=ToolResult.success({}, "ok")))
        self.assertEqual(RuntimeEvent.from_json(mapped.to_json()), mapped)


if __name__ == "__main__":
    unittest.main()
