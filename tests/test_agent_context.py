import tempfile
import unittest
from pathlib import Path

from huicode.agent import run_agent_loop
from huicode.agent_events import AgentOptions, AgentState
from huicode.config import ContextConfig, LLMConfig
from huicode.mcp.tools import MCPToolAdapter
from huicode.prompts.base import PromptBundle
from huicode.providers.base import ConversationMessage, StreamEvent, ToolCall
from huicode.tools.base import ToolContext
from huicode.tools.registry import create_default_registry


class ContextProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = []
        self.turn = 0

    def stream_chat(self, messages: list[ConversationMessage], tools=None, allow_tool_calls=True, prompt=None):
        self.calls.append(
            {
                "messages": list(messages),
                "allow_tool_calls": allow_tool_calls,
                "tools": list(tools or []),
                "prompt": prompt,
            }
        )
        if messages and messages[0].content.startswith("你正在为 HuiCode 压缩较早对话历史"):
            yield StreamEvent(kind="text", text="<summary>## 当前任务\n继续执行</summary>")
            return
        self.turn += 1
        if self.turn == 1:
            yield StreamEvent(kind="usage", usage={"input_tokens": 120})
            yield StreamEvent(kind="text", text="压缩后继续")
            return
        yield StreamEvent(kind="text", text="完成")


class FakeMCPSession:
    def call_tool(self, name, arguments):  # noqa: ANN001
        return {"content": [{"type": "text", "text": arguments["text"] * 2500}]}


class MCPToolProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.turn = 0

    def stream_chat(self, messages: list[ConversationMessage], tools=None, allow_tool_calls=True, prompt=None):
        self.turn += 1
        if self.turn == 1:
            yield StreamEvent(kind="tool_call", tool_call=ToolCall("call_1", "mcp__fake__echo", {"text": "hi"}))
            return
        yield StreamEvent(kind="text", text="完成")


class AgentContextTests(unittest.TestCase):
    def test_summary_runs_before_main_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            provider = ContextProvider()
            state = AgentState(
                messages=[
                    ConversationMessage("user", "旧消息" * 60),
                    ConversationMessage("assistant", "旧回复" * 60),
                    ConversationMessage("user", "新消息"),
                    ConversationMessage("assistant", "新回复"),
                ]
            )
            config = LLMConfig(
                "openai",
                "fake",
                "https://example.test",
                "key",
                context=ContextConfig(window_tokens=60, auto_margin_tokens=20, min_recent_messages=2, recent_keep_tokens=10),
            )

            events = list(
                run_agent_loop(
                    provider=provider,
                    registry=create_default_registry(workspace),
                    context=ToolContext(workspace=workspace),
                    state=state,
                    user_text="继续",
                    config=config,
                    options=AgentOptions(),
                )
            )

        self.assertTrue(any(event.kind == "context" and event.data.get("kind") == "summary" for event in events))
        self.assertEqual(provider.calls[0]["allow_tool_calls"], False)
        self.assertEqual(provider.calls[1]["messages"][0].content.count("conversation_summary"), 1)
        self.assertEqual(state.context.last_input_tokens, 120)

    def test_large_mcp_tool_result_is_spilled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            registry = create_default_registry(workspace)
            registry.register(
                MCPToolAdapter(
                    server_name="fake",
                    remote_name="echo",
                    name="mcp__fake__echo",
                    description="Echo",
                    parameters={"type": "object"},
                    session=FakeMCPSession(),  # type: ignore[arg-type]
                )
            )
            provider = MCPToolProvider()
            state = AgentState()
            config = LLMConfig("openai", "fake", "https://example.test", "key")

            list(
                run_agent_loop(
                    provider=provider,
                    registry=registry,
                    context=ToolContext(workspace=workspace),
                    state=state,
                    user_text="调用 mcp",
                    config=config,
                    options=AgentOptions(),
                )
            )

        tool_message = next(message for message in state.messages if message.role == "tool")
        self.assertIn("__spilled__", tool_message.tool_result.data)


if __name__ == "__main__":
    unittest.main()
