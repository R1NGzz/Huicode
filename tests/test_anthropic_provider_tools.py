import unittest
from unittest.mock import patch

from huicode.config import LLMConfig
from huicode.prompts import PromptContext, build_prompt_bundle
from huicode.providers.anthropic import AnthropicProvider
from huicode.providers.base import ConversationMessage, ToolCall, ToolSpec
from huicode.sse import SSEEvent
from huicode.tools.base import ToolResult


class AnthropicProviderToolTests(unittest.TestCase):
    def test_sends_tool_schema_and_parses_partial_json(self) -> None:
        config = LLMConfig("anthropic", "claude-test", "https://api.anthropic.com/v1", "key")
        events = [
            SSEEvent("content_block_start", '{"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"toolu_1","name":"Read","input":{}}}'),
            SSEEvent("content_block_delta", '{"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"pa"}}'),
            SSEEvent("content_block_delta", '{"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"th\\":\\"README.md\\"}"}}'),
            SSEEvent("message_stop", '{"type":"message_stop"}'),
        ]
        tool = ToolSpec("Read", "读取文件", {"type": "object", "properties": {"path": {"type": "string"}}})

        with patch("huicode.providers.anthropic.post_sse", return_value=iter(events)) as mock_post:
            chunks = list(AnthropicProvider(config).stream_chat([ConversationMessage("user", "读 README")], [tool]))

        self.assertEqual(chunks[0].kind, "tool_call")
        self.assertEqual(chunks[0].tool_call.id, "toolu_1")
        self.assertEqual(chunks[0].tool_call.name, "Read")
        self.assertEqual(chunks[0].tool_call.arguments, {"path": "README.md"})
        payload = mock_post.call_args.kwargs["payload"]
        self.assertEqual(payload["tools"][0]["name"], "Read")

    def test_serializes_tool_history_and_can_disable_tools(self) -> None:
        config = LLMConfig("anthropic", "claude-test", "https://api.anthropic.com/v1", "key")
        call = ToolCall(id="toolu_1", name="Read", arguments={"path": "README.md"}, raw_arguments='{"path":"README.md"}')
        messages = [
            ConversationMessage("user", "读 README"),
            ConversationMessage("assistant", "", thinking="先读取 README", thinking_signature="sig-1", tool_calls=[call]),
            ConversationMessage("tool", "", tool_call_id="toolu_1", tool_name="Read", tool_result=ToolResult.success({"content": "hi"}, "ok")),
        ]

        with patch("huicode.providers.anthropic.post_sse", return_value=iter([SSEEvent("message_stop", '{"type":"message_stop"}')])) as mock_post:
            list(AnthropicProvider(config).stream_chat(messages, tools=[], allow_tool_calls=False))

        payload = mock_post.call_args.kwargs["payload"]
        self.assertEqual(
            payload["messages"][1]["content"][0],
            {"type": "thinking", "thinking": "先读取 README", "signature": "sig-1"},
        )
        self.assertEqual(payload["messages"][1]["content"][1]["type"], "tool_use")
        self.assertEqual(payload["messages"][2]["content"][0]["type"], "tool_result")
        self.assertNotIn("tools", payload)

    def test_serializes_multiple_tool_results_in_one_immediate_user_message(self) -> None:
        config = LLMConfig("anthropic", "claude-test", "https://api.anthropic.com/v1", "key")
        calls = [
            ToolCall(id="call_1", name="Find", arguments={"pattern": "*"}),
            ToolCall(id="call_2", name="Find", arguments={"pattern": "*.py"}),
            ToolCall(id="call_3", name="Find", arguments={"pattern": "package.json"}),
        ]
        messages = [
            ConversationMessage("user", "当前项目入口文件有哪些"),
            ConversationMessage("assistant", "", tool_calls=calls),
            ConversationMessage(
                "tool",
                "",
                tool_call_id="call_1",
                tool_name="Find",
                tool_result=ToolResult.success({"count": 50}, "ok, 50 files"),
            ),
            ConversationMessage(
                "tool",
                "",
                tool_call_id="call_2",
                tool_name="Find",
                tool_result=ToolResult.success({"count": 39}, "ok, 39 files"),
            ),
            ConversationMessage(
                "tool",
                "",
                tool_call_id="call_3",
                tool_name="Find",
                tool_result=ToolResult.success({"count": 0}, "ok, 0 files"),
            ),
        ]

        with patch("huicode.providers.anthropic.post_sse", return_value=iter([SSEEvent("message_stop", '{"type":"message_stop"}')])) as mock_post:
            list(AnthropicProvider(config).stream_chat(messages, tools=[], allow_tool_calls=True))

        payload = mock_post.call_args.kwargs["payload"]
        self.assertEqual(len(payload["messages"]), 3)
        self.assertEqual(payload["messages"][1]["role"], "assistant")
        self.assertEqual([block["id"] for block in payload["messages"][1]["content"]], ["call_1", "call_2", "call_3"])
        self.assertEqual(payload["messages"][2]["role"], "user")
        self.assertEqual(
            [block["tool_use_id"] for block in payload["messages"][2]["content"]],
            ["call_1", "call_2", "call_3"],
        )
        self.assertTrue(all(block["type"] == "tool_result" for block in payload["messages"][2]["content"]))

    def test_serializes_text_assistant_thinking(self) -> None:
        config = LLMConfig("anthropic", "claude-test", "https://api.anthropic.com/v1", "key")
        messages = [ConversationMessage("assistant", "结论", thinking="推理过程", thinking_signature="sig-2")]

        with patch("huicode.providers.anthropic.post_sse", return_value=iter([SSEEvent("message_stop", '{"type":"message_stop"}')])) as mock_post:
            list(AnthropicProvider(config).stream_chat(messages, tools=[], allow_tool_calls=False))

        content = mock_post.call_args.kwargs["payload"]["messages"][0]["content"]
        self.assertEqual(content[0], {"type": "thinking", "thinking": "推理过程", "signature": "sig-2"})
        self.assertEqual(content[1], {"type": "text", "text": "结论"})

    def test_parses_thinking_signature_delta(self) -> None:
        config = LLMConfig("anthropic", "claude-test", "https://api.anthropic.com/v1", "key")
        events = [
            SSEEvent("content_block_start", '{"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}'),
            SSEEvent("content_block_delta", '{"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"思考"}}'),
            SSEEvent("content_block_delta", '{"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"sig"}}'),
            SSEEvent("message_stop", '{"type":"message_stop"}'),
        ]

        with patch("huicode.providers.anthropic.post_sse", return_value=iter(events)):
            chunks = list(AnthropicProvider(config).stream_chat([ConversationMessage("user", "hi")]))

        self.assertEqual(chunks[0].kind, "thinking")
        self.assertEqual(chunks[1].text, "思考")
        self.assertEqual(chunks[2].thinking_signature, "sig")

    def test_forwards_usage_event_when_present(self) -> None:
        config = LLMConfig("anthropic", "claude-test", "https://api.anthropic.com/v1", "key")
        events = [
            SSEEvent("message_start", '{"type":"message_start","usage":{"input_tokens":9,"output_tokens":3}}'),
            SSEEvent("message_stop", '{"type":"message_stop"}'),
        ]

        with patch("huicode.providers.anthropic.post_sse", return_value=iter(events)):
            chunks = list(AnthropicProvider(config).stream_chat([ConversationMessage("user", "hi")]))

        self.assertEqual(chunks[0].kind, "usage")
        self.assertEqual(chunks[0].usage["input_tokens"], 9)

    def test_serializes_summary_and_boundary_messages_without_breaking_tool_results(self) -> None:
        config = LLMConfig("anthropic", "claude-test", "https://api.anthropic.com/v1", "key")
        call = ToolCall(id="toolu_1", name="Read", arguments={"path": "README.md"}, raw_arguments='{"path":"README.md"}')
        messages = [
            ConversationMessage("user", '<huicode_context type="conversation_summary">summary</huicode_context>'),
            ConversationMessage("user", '<huicode_context type="compression_boundary">boundary</huicode_context>'),
            ConversationMessage("assistant", "", tool_calls=[call]),
            ConversationMessage("tool", "", tool_call_id="toolu_1", tool_name="Read", tool_result=ToolResult.success({"content": "hi"}, "ok")),
        ]

        with patch("huicode.providers.anthropic.post_sse", return_value=iter([SSEEvent("message_stop", '{"type":"message_stop"}')])) as mock_post:
            list(AnthropicProvider(config).stream_chat(messages, tools=[], allow_tool_calls=False))

        payload = mock_post.call_args.kwargs["payload"]
        self.assertIn("conversation_summary", payload["messages"][0]["content"])
        self.assertIn("compression_boundary", payload["messages"][1]["content"])
        self.assertEqual(payload["messages"][2]["content"][0]["id"], "toolu_1")
        self.assertEqual(payload["messages"][3]["content"][0]["tool_use_id"], "toolu_1")

    def test_serializes_memory_prompt_with_restored_tool_history(self) -> None:
        config = LLMConfig("anthropic", "claude-test", "https://api.anthropic.com/v1", "key")
        prompt = build_prompt_bundle(
            PromptContext(
                workspace=__import__("pathlib").Path("C:/work/project"),
                platform="Windows",
                shell="powershell",
                now="2026-07-09T12:00:00+08:00",
                mode="chat",
                iteration=1,
                max_iterations=8,
                custom_instructions="项目指令",
                memory_index="- [mem-1] 入口知识 (source: .huicode/memory/notes/mem-1.md)",
            )
        )
        call = ToolCall(id="toolu_1", name="Read", arguments={"path": "README.md"})
        messages = [
            ConversationMessage("user", "old"),
            ConversationMessage("assistant", "", tool_calls=[call]),
            ConversationMessage("tool", "", tool_call_id="toolu_1", tool_name="Read", tool_result=ToolResult.success({"content": "hi"}, "ok")),
        ]

        with patch("huicode.providers.anthropic.post_sse", return_value=iter([SSEEvent("message_stop", '{"type":"message_stop"}')])) as mock_post:
            list(AnthropicProvider(config).stream_chat(messages, tools=[], allow_tool_calls=False, prompt=prompt))

        payload = mock_post.call_args.kwargs["payload"]
        system_text = "\n".join(block["text"] for block in payload["system"])
        self.assertIn("项目指令", system_text)
        self.assertIn("memory_index", system_text)
        self.assertEqual(payload["messages"][-2]["content"][0]["id"], "toolu_1")
        self.assertEqual(payload["messages"][-1]["content"][0]["tool_use_id"], "toolu_1")


if __name__ == "__main__":
    unittest.main()
