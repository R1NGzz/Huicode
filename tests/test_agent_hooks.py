import json
import sys
import tempfile
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from huicode.agent import run_agent_loop
from huicode.agent_events import AgentOptions, AgentState
from huicode.config import ContextConfig, LLMConfig
from huicode.hooks.manager import HookManager
from huicode.hooks.types import (
    CommandAction,
    HookActionResult,
    HookCatalog,
    HookCondition,
    HookPredicate,
    HookRule,
    HttpAction,
    PromptAction,
)
from huicode.permissions import PermissionContext
from huicode.providers.base import ConversationMessage, StreamEvent, ToolCall
from huicode.tools.base import ToolContext
from huicode.tools.registry import create_default_registry


class ScriptedProvider:
    name = "fake"
    model = "fake"

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
        self.calls.append({"messages": list(messages), "tools": list(tools or []), "prompt": prompt})
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        yield from turn


class RuleExecutor:
    def __init__(self, results=None):
        self.results = results or {}
        self.calls = []

    def execute(self, rule, payload, inject_prompt=None):  # noqa: ANN001
        self.calls.append((rule.id, payload))
        return self.results.get(rule.id, HookActionResult("success", "ok"))


class RaisingConfirmer:
    def confirm(self, request):  # noqa: ANN001
        raise AssertionError("Hook 拒绝后不应触发权限确认")


class AgentHookTests(unittest.TestCase):
    def test_lifecycle_tool_events_and_turn_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "a.txt").write_text("hello", encoding="utf-8")
            names = [
                "turn_start",
                "message_received",
                "message_completed",
                "tool_before",
                "tool_after",
                "turn_end",
            ]
            rules = tuple(HookRule(name, name, CommandAction(command="noop")) for name in names)
            executor = RuleExecutor()
            manager = HookManager(HookCatalog(rules), workspace, action_executor=executor)
            provider = ScriptedProvider(
                [
                    [StreamEvent(kind="tool_call", tool_call=ToolCall("call-1", "Read", {"path": "a.txt"}))],
                    [StreamEvent(kind="text", text="done")],
                ]
            )
            state = AgentState()
            events = list(
                run_agent_loop(
                    provider,
                    create_default_registry(workspace),
                    ToolContext(workspace),
                    state,
                    "read",
                    LLMConfig("openai", "fake", "https://example.test", "key"),
                    AgentOptions(),
                    hook_manager=manager,
                )
            )
            manager.close()

        called = [rule_id for rule_id, _ in executor.calls]
        self.assertEqual(
            called,
            [
                "turn_start",
                "message_received",
                "message_completed",
                "tool_before",
                "tool_after",
                "message_completed",
                "turn_end",
            ],
        )
        self.assertEqual(events[-1].stop_reason, "final")
        self.assertEqual(state.hooks.turn_id, "")

    def test_tool_before_denial_backfills_and_loop_continues(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            condition = HookCondition("all", (HookPredicate("tool.name", "exact", "Write"),))
            rules = (
                HookRule("deny-write", "tool_before", CommandAction(command="noop"), condition=condition),
                HookRule("after", "tool_after", CommandAction(command="noop")),
            )
            executor = RuleExecutor({"deny-write": HookActionResult("denied", deny_reason="只读项目")})
            manager = HookManager(HookCatalog(rules), workspace, action_executor=executor)
            provider = ScriptedProvider(
                [
                    [StreamEvent(kind="tool_call", tool_call=ToolCall("call-1", "Write", {"path": "x.txt", "content": "x"}))],
                    [StreamEvent(kind="text", text="已改用说明")],
                ]
            )
            state = AgentState()
            events = list(
                run_agent_loop(
                    provider,
                    create_default_registry(workspace),
                    ToolContext(
                        workspace,
                        permissions=PermissionContext(workspace=workspace, mode="default", confirmer=RaisingConfirmer()),
                    ),
                    state,
                    "write",
                    LLMConfig("openai", "fake", "https://example.test", "key"),
                    AgentOptions(),
                    hook_manager=manager,
                )
            )
            manager.close()
            exists = (workspace / "x.txt").exists()

        self.assertFalse(exists)
        self.assertEqual(events[-1].stop_reason, "final")
        result = state.messages[2].tool_result
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "hook_denied")
        self.assertEqual(result.error.details["rule_id"], "deny-write")
        after_payload = next(payload for rule_id, payload in executor.calls if rule_id == "after")
        self.assertEqual(after_payload["result"]["source"], "hook")

    def test_prompt_next_request_and_turn_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            rules = (
                HookRule("next", "turn_start", PromptAction(content="NEXT", scope="next_request")),
                HookRule("turn", "turn_start", PromptAction(content="TURN", scope="turn")),
            )
            manager = HookManager(HookCatalog(rules), workspace)
            (workspace / "a.txt").write_text("hello", encoding="utf-8")
            provider = ScriptedProvider(
                [
                    [StreamEvent(kind="tool_call", tool_call=ToolCall("call-1", "Read", {"path": "a.txt"}))],
                    [StreamEvent(kind="text", text="done")],
                ]
            )
            list(
                run_agent_loop(
                    provider,
                    create_default_registry(workspace),
                    ToolContext(workspace),
                    AgentState(),
                    "read",
                    LLMConfig("openai", "fake", "https://example.test", "key"),
                    AgentOptions(),
                    hook_manager=manager,
                )
            )
            manager.close()

        first = provider.calls[0]["prompt"].dynamic_text()
        second = provider.calls[1]["prompt"].dynamic_text()
        self.assertIn("NEXT", first)
        self.assertNotIn("NEXT", second)
        self.assertIn("TURN", first)
        self.assertIn("TURN", second)

    def test_provider_error_emits_agent_error_and_turn_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            rules = (
                HookRule("error", "agent_error", CommandAction(command="noop")),
                HookRule("end", "turn_end", CommandAction(command="noop")),
            )
            executor = RuleExecutor()
            manager = HookManager(HookCatalog(rules), workspace, action_executor=executor)
            events = list(
                run_agent_loop(
                    ScriptedProvider([RuntimeError("boom")]),
                    create_default_registry(workspace),
                    ToolContext(workspace),
                    AgentState(),
                    "hello",
                    LLMConfig("openai", "fake", "https://example.test", "key"),
                    AgentOptions(),
                    hook_manager=manager,
                )
            )
            manager.close()
        self.assertEqual([rule_id for rule_id, _ in executor.calls], ["error", "end"])
        self.assertEqual(events[-1].stop_reason, "error")

    def test_failed_request_consumes_next_request_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            manager = HookManager(
                HookCatalog((HookRule("next", "turn_start", PromptAction(content="ONCE")),)),
                workspace,
            )
            state = AgentState()
            provider = ScriptedProvider([RuntimeError("boom")])
            events = list(
                run_agent_loop(
                    provider,
                    create_default_registry(workspace),
                    ToolContext(workspace),
                    state,
                    "hello",
                    LLMConfig("openai", "fake", "https://example.test", "key"),
                    AgentOptions(),
                    hook_manager=manager,
                )
            )
            self.assertIn("ONCE", provider.calls[0]["prompt"].dynamic_text())
            self.assertEqual(state.hooks.next_request_blocks, [])
            manager.close()
        self.assertEqual(events[-1].stop_reason, "error")

    def test_mixed_multi_tool_response_keeps_every_result_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "a.txt").write_text("hello", encoding="utf-8")
            condition = HookCondition("all", (HookPredicate("tool.name", "exact", "Write"),))
            manager = HookManager(
                HookCatalog((HookRule("deny-write", "tool_before", CommandAction(command="noop"), condition=condition),)),
                workspace,
                action_executor=RuleExecutor({"deny-write": HookActionResult("denied", deny_reason="只读")}),
            )
            provider = ScriptedProvider(
                [
                    [
                        StreamEvent(kind="tool_call", tool_call=ToolCall("read-1", "Read", {"path": "a.txt"})),
                        StreamEvent(kind="tool_call", tool_call=ToolCall("write-1", "Write", {"path": "x.txt", "content": "x"})),
                    ],
                    [StreamEvent(kind="text", text="done")],
                ]
            )
            events = list(
                run_agent_loop(
                    provider,
                    create_default_registry(workspace),
                    ToolContext(
                        workspace,
                        permissions=PermissionContext(workspace=workspace, mode="default", confirmer=RaisingConfirmer()),
                    ),
                    AgentState(),
                    "inspect and write",
                    LLMConfig("anthropic", "fake", "https://example.test", "key"),
                    AgentOptions(),
                    hook_manager=manager,
                )
            )
            tool_messages = [message for message in provider.calls[1]["messages"] if message.role == "tool"]
            manager.close()
        self.assertEqual([message.tool_call_id for message in tool_messages], ["read-1", "write-1"])
        self.assertEqual(len(tool_messages), 2)
        self.assertEqual(events[-1].stop_reason, "final")

    def test_tool_after_async_command_and_http_do_not_block_agent(self) -> None:
        class SlowHandler(BaseHTTPRequestHandler):
            payloads = []

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                type(self).payloads.append(json.loads(body.decode("utf-8")))
                time.sleep(0.35)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format, *args):  # noqa: A002, ANN001
                return

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            target = workspace / "sample.txt"
            target.write_text("old", encoding="utf-8")
            server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
            Thread(target=server.serve_forever, daemon=True).start()
            formatter = (
                "import json,pathlib,sys; "
                "d=json.load(sys.stdin); p=pathlib.Path(d['tool']['arguments']['path']); "
                "p.write_text(p.read_text(encoding='utf-8').upper(), encoding='utf-8')"
            )
            condition = HookCondition("all", (HookPredicate("tool.name", "exact", "Edit"),))
            rules = (
                HookRule(
                    "format",
                    "tool_after",
                    CommandAction(command=sys.executable, args=("-c", formatter)),
                    condition=condition,
                    async_run=True,
                ),
                HookRule(
                    "notify",
                    "tool_after",
                    HttpAction(url=f"http://127.0.0.1:{server.server_port}/hook"),
                    condition=condition,
                    async_run=True,
                ),
            )
            manager = HookManager(HookCatalog(rules), workspace)
            provider = ScriptedProvider(
                [
                    [
                        StreamEvent(
                            kind="tool_call",
                            tool_call=ToolCall(
                                "edit-1",
                                "Edit",
                                {"path": "sample.txt", "old_text": "old", "new_text": "new"},
                            ),
                        )
                    ],
                    [StreamEvent(kind="text", text="done")],
                ]
            )
            started = time.monotonic()
            events = list(
                run_agent_loop(
                    provider,
                    create_default_registry(workspace),
                    ToolContext(workspace),
                    AgentState(),
                    "edit",
                    LLMConfig("openai", "fake", "https://example.test", "key"),
                    AgentOptions(),
                    hook_manager=manager,
                )
            )
            agent_elapsed = time.monotonic() - started
            manager.close()
            server.shutdown()
            server.server_close()
            formatted = target.read_text(encoding="utf-8")

        self.assertLess(agent_elapsed, 0.3)
        self.assertEqual(formatted, "NEW")
        self.assertEqual(SlowHandler.payloads[0]["tool"]["call_id"], "edit-1")
        self.assertEqual(events[-1].stop_reason, "final")

    def test_context_summary_emits_before_and_after(self) -> None:
        class SummaryProvider(ScriptedProvider):
            def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
                if messages and messages[0].content.startswith("你正在为 HuiCode 压缩较早对话历史"):
                    yield StreamEvent(kind="text", text="<summary>摘要</summary>")
                    return
                yield from super().stream_chat(messages, tools, allow_tool_calls, prompt)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            rules = (
                HookRule("before", "context_before_compact", CommandAction(command="noop")),
                HookRule("after", "context_after_compact", CommandAction(command="noop")),
            )
            executor = RuleExecutor()
            manager = HookManager(HookCatalog(rules), workspace, action_executor=executor)
            state = AgentState(
                messages=[
                    ConversationMessage("user", "old" * 100),
                    ConversationMessage("assistant", "reply" * 100),
                    ConversationMessage("user", "recent"),
                    ConversationMessage("assistant", "recent reply"),
                ]
            )
            provider = SummaryProvider([[StreamEvent(kind="text", text="done")]])
            list(
                run_agent_loop(
                    provider,
                    create_default_registry(workspace),
                    ToolContext(workspace),
                    state,
                    "continue",
                    LLMConfig(
                        "openai",
                        "fake",
                        "https://example.test",
                        "key",
                        context=ContextConfig(
                            window_tokens=80,
                            auto_margin_tokens=20,
                            recent_keep_tokens=10,
                            min_recent_messages=2,
                        ),
                    ),
                    AgentOptions(),
                    hook_manager=manager,
                )
            )
            manager.close()
        self.assertEqual([rule_id for rule_id, _ in executor.calls], ["before", "after"])

    def test_context_prompt_is_present_in_immediate_main_request(self) -> None:
        class SummaryProvider(ScriptedProvider):
            def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):  # noqa: ANN001
                if messages and messages[0].content.startswith("你正在为 HuiCode 压缩较早对话历史"):
                    yield StreamEvent(kind="text", text="<summary>摘要</summary>")
                    return
                yield from super().stream_chat(messages, tools, allow_tool_calls, prompt)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            manager = HookManager(
                HookCatalog((HookRule("inject", "context_after_compact", PromptAction(content="CONTEXT CHECK")),)),
                workspace,
            )
            state = AgentState(
                messages=[
                    ConversationMessage("user", "old" * 100),
                    ConversationMessage("assistant", "reply" * 100),
                    ConversationMessage("user", "recent"),
                    ConversationMessage("assistant", "recent reply"),
                ]
            )
            provider = SummaryProvider([[StreamEvent(kind="text", text="done")]])
            list(
                run_agent_loop(
                    provider,
                    create_default_registry(workspace),
                    ToolContext(workspace),
                    state,
                    "continue",
                    LLMConfig(
                        "openai", "fake", "https://example.test", "key",
                        context=ContextConfig(window_tokens=80, auto_margin_tokens=20, recent_keep_tokens=10, min_recent_messages=2),
                    ),
                    AgentOptions(),
                    hook_manager=manager,
                )
            )
            manager.close()
        self.assertIn("CONTEXT CHECK", provider.calls[0]["prompt"].dynamic_text())


if __name__ == "__main__":
    unittest.main()
