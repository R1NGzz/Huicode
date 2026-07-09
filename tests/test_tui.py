import io
import unittest

from huicode.agent_events import AgentEvent
from huicode.permissions.base import PermissionRequest
from huicode.providers.base import ToolCall
from huicode.tools.base import ToolResult
from huicode.tui import format_permission_request, format_tool_call_line, format_tool_result_line, render_agent_event


class TUITests(unittest.TestCase):
    def test_tool_call_line(self) -> None:
        line = format_tool_call_line(ToolCall(id="1", name="Read", arguments={"path": "huicode/cli.py"}))

        self.assertEqual(line, "● Read(huicode/cli.py)")

    def test_result_lines(self) -> None:
        ok = format_tool_result_line(ToolResult.success({"x": 1}, "ok, 1 line"))
        error = format_tool_result_line(ToolResult.failure("bad", "出错了"))

        self.assertIn("✓ ok, 1 line", ok)
        self.assertIn("✗ 出错了", error)

    def test_render_agent_event_stream(self) -> None:
        output = io.StringIO()
        render_agent_event(AgentEvent(kind="progress", data={"stage": "assistant_turn_start"}), output)
        render_agent_event(AgentEvent(kind="text", text="你好"), output)
        render_agent_event(
            AgentEvent(kind="tool_call", tool_call=ToolCall(id="1", name="Read", arguments={"path": "README.md"})),
            output,
        )
        call = ToolCall(id="1", name="Read", arguments={"path": "README.md"})
        render_agent_event(
            AgentEvent(
                kind="tool_result",
                tool_call=call,
                tool_result=ToolResult.success({"path": "README.md"}, "ok, 10 lines"),
            ),
            output,
        )
        render_agent_event(AgentEvent(kind="done", stop_reason="final"), output)

        rendered = output.getvalue()
        self.assertIn("HuiCode> 思考中...", rendered)
        self.assertIn("HuiCode> 正在回答...", rendered)
        self.assertIn("HuiCode> ● 你好", rendered)
        self.assertIn("HuiCode> 调用工具...", rendered)
        self.assertIn("✓ Read(README.md)", rendered)

    def test_progress_renders_task_and_permission_mode(self) -> None:
        output = io.StringIO()
        render_agent_event(
            AgentEvent(
                kind="progress",
                data={"stage": "assistant_turn_start", "mode": "plan", "permission_mode": "strict"},
            ),
            output,
        )

        rendered = output.getvalue()
        self.assertIn("mode=plan", rendered)
        self.assertIn("permission=strict", rendered)

    def test_groups_multiple_tool_calls_and_shows_elapsed(self) -> None:
        output = io.StringIO()
        read_call = ToolCall(id="1", name="Read", arguments={"path": "README.md"})
        bash_call = ToolCall(id="2", name="Bash", arguments={"command": "dir"})

        render_agent_event(AgentEvent(kind="progress", data={"stage": "assistant_turn_start"}), output)
        render_agent_event(AgentEvent(kind="tool_call", tool_call=read_call), output)
        render_agent_event(AgentEvent(kind="tool_call", tool_call=bash_call), output)
        render_agent_event(
            AgentEvent(
                kind="tool_result",
                tool_call=read_call,
                tool_result=ToolResult.success({"path": "README.md"}, "ok, 10 lines"),
            ),
            output,
        )
        render_agent_event(
            AgentEvent(
                kind="tool_result",
                tool_call=bash_call,
                tool_result=ToolResult.success({"command": "dir"}, "exit 0, stdout 1 chars, stderr 0 chars"),
            ),
            output,
        )

        rendered = output.getvalue()
        self.assertEqual(rendered.count("HuiCode> 调用工具..."), 1)
        self.assertIn("HuiCode> 思考完成 (", rendered)
        self.assertIn("✓ Read(README.md)", rendered)
        self.assertIn("✓ Bash(dir)", rendered)
        self.assertNotIn("running", rendered)
        self.assertRegex(rendered, r"✓ Read\(README\.md\) \(\d+\.\d{2}s\)")
        self.assertRegex(rendered, r"✓ Bash\(dir\) \(\d+\.\d{2}s\)")

    def test_plain_text_streams_before_done(self) -> None:
        output = io.StringIO()
        render_agent_event(AgentEvent(kind="progress", data={"stage": "assistant_turn_start"}), output)
        render_agent_event(AgentEvent(kind="text", text="当前项目大致是一个 Python 项目"), output)

        self.assertIn("当前项目大致是一个 Python 项目", output.getvalue())
        self.assertIn("HuiCode> 思考完成 (", output.getvalue())

    def test_text_code_block_streams_before_closing_fence(self) -> None:
        output = io.StringIO()
        render_agent_event(AgentEvent(kind="progress", data={"stage": "assistant_turn_start"}), output)
        render_agent_event(AgentEvent(kind="text", text="当前项目大致结构如下：\n\n```text\n."), output)

        rendered = output.getvalue()
        self.assertIn("当前项目大致结构如下：", rendered)
        self.assertIn(".", rendered)
        self.assertNotIn("```text", rendered)

        render_agent_event(AgentEvent(kind="text", text="\n├─ huicode\n└─ tests\n"), output)
        self.assertIn("├─ huicode", output.getvalue())

        render_agent_event(AgentEvent(kind="text", text="```\n\n补充说明：\n- ok"), output)
        render_agent_event(AgentEvent(kind="done", stop_reason="final"), output)

        rendered = output.getvalue()
        self.assertIn("补充说明", rendered)
        self.assertNotIn("```", rendered)

    def test_render_markdown_with_rich(self) -> None:
        output = io.StringIO()
        markdown = "# Title\n\n- Item\n\n```python\nprint('hi')\n```"

        render_agent_event(AgentEvent(kind="progress", data={"stage": "assistant_turn_start"}), output)
        render_agent_event(AgentEvent(kind="text", text=markdown), output)
        render_agent_event(AgentEvent(kind="done", stop_reason="final"), output)

        rendered = output.getvalue()
        self.assertIn("Title", rendered)
        self.assertIn("Item", rendered)
        self.assertIn("print", rendered)
        self.assertNotIn("# Title", rendered)
        self.assertNotIn("```python", rendered)

    def test_usage_summary_expands_cache_fields(self) -> None:
        output = io.StringIO()
        render_agent_event(
            AgentEvent(
                kind="usage",
                data={
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 3,
                        "cache": {
                            "creation_input_tokens": 2,
                            "read_input_tokens": 5,
                            "cached_tokens": 7,
                        },
                    }
                },
            ),
            output,
        )

        rendered = output.getvalue()
        self.assertIn("input_tokens=10", rendered)
        self.assertIn("cache_creation_input_tokens=2", rendered)
        self.assertIn("cache_read_input_tokens=5", rendered)
        self.assertIn("cached_tokens=7", rendered)

    def test_permission_request_format(self) -> None:
        text = format_permission_request(
            PermissionRequest(
                call=ToolCall("1", "Bash", {"command": "git status"}),
                target="git status",
                risk="medium",
                reason="默认模式需要确认",
            )
        )

        self.assertIn("权限确认", text)
        self.assertIn("Bash(git status)", text)
        self.assertIn("[d]eny", text)
        self.assertIn("[o]nce", text)
        self.assertIn("[s]ession", text)
        self.assertIn("[a]lways", text)
        self.assertIn("enter=deny", text)

    def test_context_events_render(self) -> None:
        output = io.StringIO()
        render_agent_event(
            AgentEvent(
                kind="context",
                data={"kind": "lightweight", "spilled_count": 2, "tokens_freed": 5300, "paths": ["a.json"]},
            ),
            output,
        )
        render_agent_event(
            AgentEvent(
                kind="context",
                data={"kind": "summary", "tokens_before": 42000, "tokens_after": 18000},
            ),
            output,
        )
        render_agent_event(
            AgentEvent(
                kind="context",
                data={"kind": "failure", "message": "摘要没有返回正式 summary"},
            ),
            output,
        )

        rendered = output.getvalue()
        self.assertIn("上下文整理", rendered)
        self.assertIn("spilled 2 tool result(s)", rendered)
        self.assertIn("summary created", rendered)
        self.assertIn("上下文压缩失败", rendered)


if __name__ == "__main__":
    unittest.main()
