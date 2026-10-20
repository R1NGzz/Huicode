from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

from huicode.providers.base import ConversationMessage, Provider, StreamEvent, ToolCall, ToolSpec


class DemoProvider:
    """面试演示用的确定性 Provider，保留真实 Agent Loop 和工具执行链路。"""

    name = "demo"
    model = "huicode-demo"

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.calls = 0

    def stream_chat(
        self,
        messages: list[ConversationMessage],
        tools: list[ToolSpec] | None = None,
        allow_tool_calls: bool = True,
        prompt=None,
    ) -> Iterator[StreamEvent]:
        self.calls += 1
        time.sleep(0.03)
        if not allow_tool_calls:
            yield from self._text("演示模式已收到请求。当前请求处于只读规划阶段，我会先给出分析，不执行修改。")
            return

        last_user = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        last_message = messages[-1] if messages else None
        last_tool = last_message if last_message is not None and last_message.role == "tool" else None
        tool_names = {spec.name for spec in tools or ()}

        if last_tool is not None:
            if last_tool.tool_name == "Find":
                yield from self._text("我找到了演示项目的 Python 文件。入口在 `src/hello.py`，测试在 `tests/test_hello.py`。")
                return
            if last_tool.tool_name == "Read" and self._is_edit_request(last_user):
                yield from self._call(
                    "Edit",
                    {"path": "src/hello.py", "old_text": 'return f"Hello, {name}!"', "new_text": 'return f"你好，{name}!"'},
                    tool_names,
                )
                return
            if last_tool.tool_name == "Edit":
                yield from self._call(
                    "Bash",
                    {"command": "python -m unittest discover -s tests -v"},
                    tool_names,
                )
                return
            if last_tool.tool_name == "Bash":
                yield from self._text("修改已完成，测试通过。这个过程展示了工具调用、结果回灌和 Agent Loop 的自动衔接。")
                return
            if last_tool.tool_name == "Read":
                yield from self._text("这是演示项目的入口文件，包含一个简单的 greet 函数和可运行的单元测试。")
                return

        if self._is_edit_request(last_user):
            yield from self._call("Read", {"path": "src/hello.py"}, tool_names)
            return
        if "测试" in last_user or "test" in last_user.lower():
            yield from self._call("Bash", {"command": "python -m unittest discover -s tests -v"}, tool_names)
            return
        if "读取" in last_user or "内容" in last_user or "read" in last_user.lower():
            yield from self._call("Read", {"path": "src/hello.py"}, tool_names)
            return
        yield from self._call("Find", {"pattern": "**/*.py"}, tool_names)

    def _call(self, name: str, arguments: dict[str, str], available: set[str]) -> Iterator[StreamEvent]:
        if name not in available:
            yield from self._text(f"演示 Provider 想调用 {name}，但该工具当前不可用。")
            return
        yield StreamEvent(kind="tool_call", tool_call=ToolCall(
            id=f"demo-call-{self.calls}", name=name, arguments=arguments
        ))

    @staticmethod
    def _text(value: str) -> Iterator[StreamEvent]:
        for part in value.split(" "):
            yield StreamEvent(kind="text", text=part + " ")

    @staticmethod
    def _is_edit_request(value: str) -> bool:
        return any(word in value for word in ("修改", "改一下", "edit", "change"))


__all__ = ["DemoProvider"]
