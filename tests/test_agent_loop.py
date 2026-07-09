import tempfile
import unittest
from pathlib import Path

from huicode.agent import run_agent_loop
from huicode.agent_events import AgentOptions, AgentState
from huicode.config import LLMConfig
from huicode.permissions import PermissionContext
from huicode.providers.base import ConversationMessage, StreamEvent, ToolCall
from huicode.tools.base import ToolContext
from huicode.tools.registry import create_default_registry
from huicode.mcp.tools import MCPToolAdapter


class ScriptedProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls: list[dict[str, object]] = []

    def stream_chat(self, messages, tools=None, allow_tool_calls=True, prompt=None):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools or []),
                "allow_tool_calls": allow_tool_calls,
                "prompt": prompt,
            }
        )
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        yield from turn


class FakeMCPSession:
    def __init__(self) -> None:
        self.calls = []

    def call_tool(self, name, arguments):  # noqa: ANN001
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": f"mcp:{arguments.get('text', '')}"}]}


class AgentLoopTests(unittest.TestCase):
    def test_text_events_stream_and_history_is_saved(self) -> None:
        provider = ScriptedProvider(
            [[StreamEvent(kind="thinking", text="思考"), StreamEvent(kind="thinking", thinking_signature="sig-1"), StreamEvent(kind="text", text="你好")]]
        )
        state = AgentState()

        events = list(
            run_agent_loop(
                provider=provider,
                registry=create_default_registry(Path.cwd()),
                context=ToolContext(workspace=Path.cwd()),
                state=state,
                user_text="打招呼",
                config=LLMConfig("anthropic", "fake", "https://example.test", "key"),
                options=AgentOptions(),
            )
        )

        self.assertEqual([event.kind for event in events], ["progress", "thinking", "thinking", "text", "done"])
        self.assertEqual([message.role for message in state.messages], ["user", "assistant"])
        self.assertEqual(state.messages[-1].content, "你好")
        self.assertEqual(state.messages[-1].thinking, "思考")
        self.assertEqual(state.messages[-1].thinking_signature, "sig-1")

    def test_multi_turn_tool_loop_executes_and_backfills_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "a.txt").write_text("hello", encoding="utf-8")
            provider = ScriptedProvider(
                [
                    [StreamEvent(kind="tool_call", tool_call=ToolCall(id="call_1", name="Read", arguments={"path": "a.txt"}))],
                    [StreamEvent(kind="text", text="文件内容是 hello")],
                ]
            )
            state = AgentState()

            events = list(
                run_agent_loop(
                    provider=provider,
                    registry=create_default_registry(workspace),
                    context=ToolContext(workspace=workspace),
                    state=state,
                    user_text="读文件",
                    config=LLMConfig("openai", "fake", "https://example.test", "key"),
                    options=AgentOptions(),
                )
            )

        self.assertEqual([message.role for message in state.messages], ["user", "assistant", "tool", "assistant"])
        self.assertEqual(state.messages[1].tool_calls[0].name, "Read")
        self.assertTrue(state.messages[2].tool_result.ok)
        self.assertEqual([event.kind for event in events], ["progress", "tool_call", "tool_result", "progress", "text", "done"])
        self.assertEqual(provider.calls[1]["messages"][2].role, "tool")

    def test_max_iterations_stops_after_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "a.txt").write_text("hello", encoding="utf-8")
            provider = ScriptedProvider(
                [[StreamEvent(kind="tool_call", tool_call=ToolCall(id="call_1", name="Read", arguments={"path": "a.txt"}))]]
            )
            state = AgentState()

            events = list(
                run_agent_loop(
                    provider=provider,
                    registry=create_default_registry(workspace),
                    context=ToolContext(workspace=workspace),
                    state=state,
                    user_text="读文件",
                    config=LLMConfig("openai", "fake", "https://example.test", "key"),
                    options=AgentOptions(max_iterations=1),
                )
            )

        self.assertEqual(events[-1].kind, "done")
        self.assertEqual(events[-1].stop_reason, "max_iterations")

    def test_unknown_tool_limit_stops_loop(self) -> None:
        provider = ScriptedProvider(
            [
                [StreamEvent(kind="tool_call", tool_call=ToolCall(id="call_1", name="Missing", arguments={}))],
                [StreamEvent(kind="tool_call", tool_call=ToolCall(id="call_2", name="Missing", arguments={}))],
            ]
        )
        state = AgentState()

        events = list(
            run_agent_loop(
                provider=provider,
                registry=create_default_registry(Path.cwd()),
                context=ToolContext(workspace=Path.cwd()),
                state=state,
                user_text="试试看",
                config=LLMConfig("openai", "fake", "https://example.test", "key"),
                options=AgentOptions(max_iterations=4, max_unknown_tools=2),
            )
        )

        self.assertEqual(events[-1].stop_reason, "unknown_tool_limit")

    def test_provider_error_yields_error_event(self) -> None:
        provider = ScriptedProvider([RuntimeError("boom")])
        state = AgentState()

        events = list(
            run_agent_loop(
                provider=provider,
                registry=create_default_registry(Path.cwd()),
                context=ToolContext(workspace=Path.cwd()),
                state=state,
                user_text="你好",
                config=LLMConfig("openai", "fake", "https://example.test", "key"),
                options=AgentOptions(),
            )
        )

        self.assertEqual([event.kind for event in events], ["progress", "error", "done"])
        self.assertEqual(events[-1].stop_reason, "error")

    def test_usage_event_is_forwarded(self) -> None:
        provider = ScriptedProvider(
            [[StreamEvent(kind="usage", usage={"input_tokens": 3, "output_tokens": 5}), StreamEvent(kind="text", text="ok")]]
        )
        state = AgentState()

        events = list(
            run_agent_loop(
                provider=provider,
                registry=create_default_registry(Path.cwd()),
                context=ToolContext(workspace=Path.cwd()),
                state=state,
                user_text="hi",
                config=LLMConfig("openai", "fake", "https://example.test", "key"),
                options=AgentOptions(),
            )
        )

        usage_events = [event for event in events if event.kind == "usage"]
        self.assertEqual(usage_events[0].data["usage"]["input_tokens"], 3)
        self.assertEqual(usage_events[0].data["usage"]["cache"], {})

    def test_agent_passes_prompt_bundle_and_enhanced_tools(self) -> None:
        provider = ScriptedProvider([[StreamEvent(kind="text", text="ok")]])
        state = AgentState()

        list(
            run_agent_loop(
                provider=provider,
                registry=create_default_registry(Path.cwd()),
                context=ToolContext(workspace=Path.cwd()),
                state=state,
                user_text="hi",
                config=LLMConfig("openai", "fake", "https://example.test", "key"),
                options=AgentOptions(mode="plan"),
            )
        )

        prompt = provider.calls[0]["prompt"]
        self.assertIsNotNone(prompt)
        self.assertIn("identity", prompt.module_names())
        self.assertIn('<huicode_instruction type="plan_mode" scope="turn">', prompt.supplemental_text())
        tool_names = {tool.name for tool in provider.calls[0]["tools"]}
        self.assertEqual(tool_names, {"Read", "Find", "Search"})
        read_tool = next(tool for tool in provider.calls[0]["tools"] if tool.name == "Read")
        self.assertIn("不要编造工具结果", read_tool.description)

    def test_empty_response_retries_once_and_answers(self) -> None:
        provider = ScriptedProvider(
            [
                [StreamEvent(kind="usage", usage={"total_tokens": 0})],
                [StreamEvent(kind="text", text="项目结构如下")],
            ]
        )
        state = AgentState()

        events = list(
            run_agent_loop(
                provider=provider,
                registry=create_default_registry(Path.cwd()),
                context=ToolContext(workspace=Path.cwd()),
                state=state,
                user_text="当前项目结构是怎样的",
                config=LLMConfig("openai", "fake", "https://example.test", "key"),
                options=AgentOptions(),
            )
        )

        self.assertEqual([event.kind for event in events], ["progress", "usage", "progress", "text", "done"])
        self.assertEqual(events[-1].stop_reason, "final")
        self.assertEqual(provider.calls[1]["messages"][-1].role, "user")
        self.assertIn("没有返回任何可显示内容", provider.calls[1]["messages"][-1].content)

    def test_repeated_empty_response_stops_with_error(self) -> None:
        provider = ScriptedProvider(
            [
                [StreamEvent(kind="usage", usage={"total_tokens": 0})],
                [StreamEvent(kind="usage", usage={"total_tokens": 0})],
            ]
        )
        state = AgentState()

        events = list(
            run_agent_loop(
                provider=provider,
                registry=create_default_registry(Path.cwd()),
                context=ToolContext(workspace=Path.cwd()),
                state=state,
                user_text="当前项目结构是怎样的",
                config=LLMConfig("openai", "fake", "https://example.test", "key"),
                options=AgentOptions(max_empty_responses=1),
            )
        )

        self.assertEqual(events[-2].kind, "error")
        self.assertEqual(events[-1].stop_reason, "error")
        self.assertIn("空回复", events[-2].data["message"])


    def test_permission_denial_backfills_history_and_loop_continues(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            provider = ScriptedProvider(
                [
                    [StreamEvent(kind="tool_call", tool_call=ToolCall("call_1", "Bash", {"command": "git reset --hard"}))],
                    [StreamEvent(kind="text", text="已改用安全说明。")],
                ]
            )
            state = AgentState()

            events = list(
                run_agent_loop(
                    provider=provider,
                    registry=create_default_registry(workspace),
                    context=ToolContext(
                        workspace=workspace,
                        permissions=PermissionContext(workspace=workspace, mode="permissive"),
                    ),
                    state=state,
                    user_text="执行危险命令",
                    config=LLMConfig("openai", "fake", "https://example.test", "key"),
                    options=AgentOptions(),
                )
            )

        self.assertEqual(events[-1].stop_reason, "final")
        self.assertEqual(state.messages[2].role, "tool")
        self.assertFalse(state.messages[2].tool_result.ok)
        self.assertEqual(state.messages[2].tool_result.error.code, "permission_denied")

    def test_plan_mode_denies_side_effect_tool_before_confirmation_and_continues(self) -> None:
        class RaisingConfirmer:
            def confirm(self, request):  # noqa: ANN001
                raise AssertionError("Plan Mode should deny before permission confirmation")

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            target = workspace / "hello.txt"
            target.write_text("old", encoding="utf-8")
            provider = ScriptedProvider(
                [
                    [
                        StreamEvent(
                            kind="tool_call",
                            tool_call=ToolCall("call_1", "Bash", {"command": "echo 2 > hello.txt"}),
                        )
                    ],
                    [StreamEvent(kind="text", text="Plan Mode 已拒绝写入。")],
                ]
            )
            state = AgentState()

            events = list(
                run_agent_loop(
                    provider=provider,
                    registry=create_default_registry(workspace),
                    context=ToolContext(
                        workspace=workspace,
                        permissions=PermissionContext(
                            workspace=workspace,
                            mode="default",
                            confirmer=RaisingConfirmer(),
                        ),
                    ),
                    state=state,
                    user_text="用 bash 写一个数字 2 到 hello.txt",
                    config=LLMConfig("openai", "fake", "https://example.test", "key"),
                    options=AgentOptions(mode="plan"),
                )
            )
            file_content = target.read_text(encoding="utf-8")

        self.assertEqual(file_content, "old")
        self.assertEqual(events[-1].stop_reason, "final")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(events[0].data["mode"], "plan")
        self.assertEqual(events[0].data["permission_mode"], "default")
        tool_message = state.messages[2]
        self.assertEqual(tool_message.role, "tool")
        self.assertFalse(tool_message.tool_result.ok)
        self.assertEqual(tool_message.tool_result.error.code, "permission_denied")
        self.assertIn("Plan Mode", tool_message.tool_result.summary)

    def test_mcp_tool_result_backfills_history_and_loop_continues(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = FakeMCPSession()
            registry = create_default_registry(workspace)
            registry.register(
                MCPToolAdapter(
                    server_name="fake",
                    remote_name="echo",
                    name="mcp__fake__echo",
                    description="Echo",
                    parameters={"type": "object"},
                    session=session,  # type: ignore[arg-type]
                )
            )
            provider = ScriptedProvider(
                [
                    [StreamEvent(kind="tool_call", tool_call=ToolCall("call_1", "mcp__fake__echo", {"text": "hi"}))],
                    [StreamEvent(kind="text", text="done")],
                ]
            )
            state = AgentState()

            events = list(
                run_agent_loop(
                    provider=provider,
                    registry=registry,
                    context=ToolContext(workspace=workspace),
                    state=state,
                    user_text="call mcp",
                    config=LLMConfig("openai", "fake", "https://example.test", "key"),
                    options=AgentOptions(),
                )
            )

        self.assertEqual(events[-1].stop_reason, "final")
        self.assertEqual(session.calls, [("echo", {"text": "hi"})])
        self.assertEqual(state.messages[2].role, "tool")
        self.assertTrue(state.messages[2].tool_result.ok)
        self.assertIn("mcp:hi", state.messages[2].tool_result.summary)
        self.assertEqual(provider.calls[1]["messages"][2].role, "tool")

    def test_plan_mode_denies_mcp_tool_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = FakeMCPSession()
            registry = create_default_registry(workspace)
            registry.register(
                MCPToolAdapter(
                    server_name="fake",
                    remote_name="echo",
                    name="mcp__fake__echo",
                    description="Echo",
                    parameters={"type": "object"},
                    session=session,  # type: ignore[arg-type]
                )
            )
            provider = ScriptedProvider(
                [
                    [StreamEvent(kind="tool_call", tool_call=ToolCall("call_1", "mcp__fake__echo", {"text": "hi"}))],
                    [StreamEvent(kind="text", text="denied")],
                ]
            )
            state = AgentState()

            list(
                run_agent_loop(
                    provider=provider,
                    registry=registry,
                    context=ToolContext(workspace=workspace),
                    state=state,
                    user_text="call mcp",
                    config=LLMConfig("openai", "fake", "https://example.test", "key"),
                    options=AgentOptions(mode="plan"),
                )
            )

        self.assertEqual(session.calls, [])
        self.assertFalse(state.messages[2].tool_result.ok)
        self.assertEqual(state.messages[2].tool_result.error.code, "permission_denied")


if __name__ == "__main__":
    unittest.main()
