from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from huicode.agent import run_agent_loop
from huicode.agent_events import AgentMode, AgentOptions, AgentState
from huicode.config import ConfigError, LLMConfig, load_config
from huicode.provider_factory import create_provider
from huicode.providers.base import Provider
from huicode.tools.base import ToolContext
from huicode.tools.registry import create_default_registry
from huicode.tui import render_agent_event

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import InMemoryHistory
except ImportError:  # pragma: no cover - prompt_toolkit 是交互增强，缺失时回退 input()
    PromptSession = None
    WordCompleter = None
    InMemoryHistory = None


COMMANDS = [
    "/exit",
    "/quit",
    "/clear",
    "/config",
    "/plan",
    "/do",
    "/verbose",
    "/last",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="huicode", description="HuiCode 流式命令行 AI 助手")
    parser.add_argument(
        "-c",
        "--config",
        default=os.environ.get("HUICODE_CONFIG", str(Path.home() / ".huicode.yaml")),
        help="YAML 配置文件路径，默认读取 HUICODE_CONFIG 或 ~/.huicode.yaml",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        provider = create_provider(config)
    except (ConfigError, OSError, ValueError) as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    return _run_chat(provider, config)


def _run_chat(provider: Provider, config: LLMConfig) -> int:
    workspace = Path.cwd()
    registry = create_default_registry(workspace)
    tool_context = ToolContext(workspace=workspace)
    state = AgentState()
    current_mode: AgentMode = "chat"
    prompt_session = _create_prompt_session()
    show_usage = config.show_usage
    print(f"HuiCode 已连接: {provider.name}:{provider.model}")
    print("输入 /exit 退出，/clear 清空会话记忆，/plan 进入计划模式，/do 执行最近计划，/last 展开最近工具结果。")

    while True:
        try:
            user_text = _read_user_input(prompt_session).strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print("\n已中断输入。输入 /exit 可退出。")
            continue

        if not user_text:
            continue

        command = user_text.lower()
        if command in {"/exit", "/quit"}:
            return 0
        if command == "/clear":
            state.messages.clear()
            state.last_plan = ""
            state.cancel_requested = False
            state.unknown_tool_count = 0
            state.iterations = 0
            current_mode = "chat"
            print("本次会话记忆和计划状态已清空。")
            continue
        if command == "/config":
            print(_format_config_summary(provider, config, show_usage))
            continue
        if command == "/verbose":
            show_usage = not show_usage
            print(f"详细用量显示已{'开启' if show_usage else '关闭'}。")
            continue
        if command == "/last" or command.startswith("/last "):
            print(_format_last_tool_results(state, command))
            continue
        if command == "/plan":
            current_mode = "plan"
            print("已进入 Plan Mode。接下来会只使用读类工具。")
            continue
        if command.startswith("/plan "):
            current_mode = "plan"
            _run_request(provider, registry, tool_context, state, command[6:].strip(), config, "plan", show_usage)
            continue
        if command == "/do":
            if not state.last_plan:
                print("当前还没有最近计划，请先使用 /plan。")
                continue
            current_mode = "chat"
            _run_request(provider, registry, tool_context, state, "请根据最近计划继续执行。", config, "do", show_usage)
            continue
        if command.startswith("/do "):
            current_mode = "chat"
            _run_request(provider, registry, tool_context, state, command[4:].strip(), config, "do", show_usage)
            continue

        mode: AgentMode = "plan" if current_mode == "plan" else "chat"
        _run_request(provider, registry, tool_context, state, user_text, config, mode, show_usage)


def _create_prompt_session():
    if PromptSession is None or WordCompleter is None or InMemoryHistory is None or not sys.stdin.isatty():
        return None
    try:
        return PromptSession(
            history=InMemoryHistory(),
            completer=WordCompleter(COMMANDS, ignore_case=True),
            complete_while_typing=True,
        )
    except Exception:
        return None


def _read_user_input(prompt_session) -> str:
    if prompt_session is None:
        return input("\nYou> ")
    return prompt_session.prompt("\nYou> ")


def _format_config_summary(provider: Provider, config: LLMConfig, show_usage: bool | None = None) -> str:
    summary = f"protocol={provider.name} model={provider.model} base_url={config.base_url}"
    if config.headers:
        summary += f" headers={','.join(sorted(config.headers))}"
    if show_usage is not None:
        summary += f" show_usage={str(show_usage).lower()}"
    return summary


def _format_last_tool_results(state: AgentState, command: str) -> str:
    count = _parse_last_count(command)
    tool_messages = [message for message in state.messages if message.role == "tool" and message.tool_result is not None]
    if not tool_messages:
        return "还没有可展开的工具结果。"
    selected = tool_messages[-count:]
    return "\n\n".join(_format_tool_message(message, index) for index, message in enumerate(selected, start=1))


def _parse_last_count(command: str) -> int:
    parts = command.split()
    if len(parts) < 2:
        return 1
    try:
        return max(1, min(int(parts[1]), 5))
    except ValueError:
        return 1


def _format_tool_message(message, index: int) -> str:
    result = message.tool_result
    header = f"[{index}] {message.tool_name or 'Tool'}: {result.summary}"
    if message.tool_name == "Bash" and result.data:
        return "\n".join(
            [
                header,
                f"command: {result.data.get('command', '')}",
                f"returncode: {result.data.get('returncode', '')}",
                "stdout:",
                str(result.data.get("stdout", "")),
                "stderr:",
                str(result.data.get("stderr", "")),
            ]
        )
    if message.tool_name == "Read" and result.data:
        return "\n".join([header, f"path: {result.data.get('path', '')}", "content:", str(result.data.get("content", ""))])
    detail = result.data if result.ok else (result.error.to_dict() if result.error else {})
    return f"{header}\n{json.dumps(detail, ensure_ascii=False, indent=2)}"


def _run_request(
    provider: Provider,
    registry,
    tool_context: ToolContext,
    state: AgentState,
    user_text: str,
    config: LLMConfig,
    mode: AgentMode,
    show_usage: bool,
) -> None:
    options = AgentOptions(mode=mode)
    last_user_count = len(state.messages)
    for event in run_agent_loop(
        provider=provider,
        registry=registry,
        context=tool_context,
        state=state,
        user_text=user_text,
        config=config,
        options=options,
    ):
        if event.kind == "thinking" and not config.thinking.show:
            continue
        if event.kind == "usage" and not show_usage:
            continue
        render_agent_event(event, sys.stdout)
        if event.kind == "done" and event.stop_reason in {"cancelled", "error"} and len(state.messages) > last_user_count:
            if state.messages and state.messages[-1].role == "user":
                state.messages.pop()
