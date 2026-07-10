from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from huicode.agent import run_agent_loop
from huicode.agent_events import AgentEvent, AgentMode, AgentOptions, AgentState
from huicode.config import ConfigError, LLMConfig, load_config
from huicode.context import ContextManager
from huicode.memory.manager import MemoryManager
from huicode.mcp import MCPConfigError, MCPManager, load_mcp_config, mcp_config_paths
from huicode.mcp.transport import create_transport
from huicode.permissions import (
    PermissionConfigError,
    PermissionConfirmation,
    PermissionContext,
    load_permission_config,
    permission_config_paths,
)
from huicode.provider_factory import create_provider
from huicode.providers.base import Provider
from huicode.tools.base import ToolContext
from huicode.tools.registry import create_default_registry
from huicode.tui import format_permission_request, render_agent_event

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
    "/permissions",
    "/perm",
    "/compact",
    "/context",
    "/memory",
    "/sessions",
    "/resume",
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


def _run_chat(provider: Provider, config: LLMConfig, mcp_transport_factory=None) -> int:
    workspace = Path.cwd()
    registry = create_default_registry(workspace)
    mcp_manager: MCPManager | None = None
    try:
        mcp_config = load_mcp_config(mcp_config_paths(workspace), inline_mcp=config.mcp)
        mcp_manager = MCPManager(mcp_config, transport_factory=mcp_transport_factory or create_transport)
        mcp_manager.start(registry)
    except MCPConfigError as exc:
        print(f"MCP 配置错误: {exc}")
        return 2
    try:
        permission_paths = permission_config_paths(workspace)
        permission_config = load_permission_config(permission_paths)
    except PermissionConfigError as exc:
        _close_mcp(mcp_manager)
        print(f"权限配置错误: {exc}")
        return 2

    prompt_session = _create_prompt_session()
    permission_context = PermissionContext(
        workspace=workspace,
        mode=permission_config.mode,
        rules=list(permission_config.rules),
        persistent_path=permission_paths.local,
        confirmer=ConsolePermissionConfirmer(prompt_session),
    )
    tool_context = ToolContext(workspace=workspace, permissions=permission_context)
    state = AgentState()
    context_manager = ContextManager(workspace, config.context)
    memory_manager: MemoryManager | None = None
    if config.memory.enabled:
        memory_manager = MemoryManager(workspace, config.memory, config, provider)
        for warning in memory_manager.start(state):
            print(f"记忆提示: {warning}")
    current_mode: AgentMode = "chat"
    show_usage = config.show_usage
    if mcp_manager is not None and mcp_manager.server_count:
        print(
            f"MCP servers={mcp_manager.active_server_count}/{mcp_manager.server_count} "
            f"tools={mcp_manager.tool_count} errors={len(mcp_manager.errors)}"
        )
        for error in mcp_manager.errors:
            print(f"MCP server {error.server} skipped: {error.message}")
    print(f"HuiCode 已连接: {provider.name}:{provider.model}")
    print("输入 /exit 退出，/clear 清空会话记忆，/plan 进入计划模式，/do 执行最近计划，/last 展开最近工具结果。")

    while True:
        try:
            user_text = _read_user_input(prompt_session).strip()
        except EOFError:
            print()
            return _close_resources_and_return(mcp_manager, memory_manager, 0)
        except KeyboardInterrupt:
            print("\n已中断输入。输入 /exit 可退出。")
            continue

        if not user_text:
            continue

        command = user_text.lower()
        if command in {"/exit", "/quit"}:
            return _close_resources_and_return(mcp_manager, memory_manager, 0)
        if command == "/clear":
            state.messages.clear()
            state.last_plan = ""
            state.cancel_requested = False
            state.unknown_tool_count = 0
            state.iterations = 0
            context_manager.reset(state)
            if memory_manager is not None:
                memory_manager.clear_current_session(state)
            current_mode = "chat"
            print("本次会话记忆和计划状态已清空。")
            continue
        if command == "/config":
            print(_format_config_summary(provider, config, state, show_usage, mcp_manager, memory_manager))
            continue
        if command == "/context":
            print(_format_context_summary(config, state))
            continue
        if command == "/memory":
            print(_format_memory_summary(memory_manager, state))
            continue
        if command == "/memory update":
            if memory_manager is None:
                print("记忆系统未启用")
            else:
                report = memory_manager.update_now(state, current_mode if current_mode == "plan" else "chat")
                print(report.message)
            continue
        if command == "/memory rebuild":
            if memory_manager is None:
                print("记忆系统未启用")
            else:
                print(memory_manager.rebuild_index(state))
            continue
        if command == "/sessions":
            print(_format_sessions(memory_manager))
            continue
        if command == "/sessions clean":
            if memory_manager is None:
                print("记忆系统未启用")
            else:
                removed = memory_manager.cleanup_sessions(state)
                print(f"已清理过期会话 {removed} 个")
            continue
        if command == "/resume":
            print(_format_resume_choices(memory_manager))
            continue
        if command.startswith("/resume "):
            if memory_manager is None:
                print("记忆系统未启用")
            else:
                session_id = command.split(maxsplit=1)[1].strip()
                report = memory_manager.resume_session(session_id, state, context_manager, tool_context, config)
                print(_format_resume_report(report))
            continue
        if command == "/compact":
            report = context_manager.manual_compact(
                provider=provider,
                state=state,
                context=tool_context,
                config=config,
                prompt=None,
                tools=[],
            )
            render_agent_event(AgentEvent(kind="context", data=report.to_dict()), sys.stdout)
            continue
        if command == "/verbose":
            show_usage = not show_usage
            print(f"详细用量显示已{'开启' if show_usage else '关闭'}。")
            continue
        if command == "/last" or command.startswith("/last "):
            print(_format_last_tool_results(state, command))
            continue
        if command in {"/permissions", "/perm"}:
            print(_format_permission_summary(permission_context))
            continue
        if command.startswith("/permissions ") or command.startswith("/perm "):
            requested_mode = command.split(maxsplit=1)[1].strip()
            if requested_mode in {"strict", "default", "permissive"}:
                permission_context.mode = requested_mode  # type: ignore[assignment]
                print(f"权限模式已切换为 {requested_mode}")
            else:
                print("用法: /permissions [strict|default|permissive] 或 /perm [strict|default|permissive]")
            continue
        if command == "/plan":
            current_mode = "plan"
            print("已进入 Plan Mode。接下来会只使用读类工具。")
            continue
        if command.startswith("/plan "):
            current_mode = "plan"
            _run_request(provider, registry, tool_context, state, command[6:].strip(), config, "plan", show_usage, memory_manager)
            continue
        if command == "/do":
            if not state.last_plan:
                print("当前还没有最近计划，请先使用 /plan。")
                continue
            current_mode = "chat"
            _run_request(provider, registry, tool_context, state, "请根据最近计划继续执行。", config, "do", show_usage, memory_manager)
            continue
        if command.startswith("/do "):
            current_mode = "chat"
            _run_request(provider, registry, tool_context, state, command[4:].strip(), config, "do", show_usage, memory_manager)
            continue

        mode: AgentMode = "plan" if current_mode == "plan" else "chat"
        _run_request(provider, registry, tool_context, state, user_text, config, mode, show_usage, memory_manager)


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


class ConsolePermissionConfirmer:
    def __init__(self, prompt_session) -> None:
        self.prompt_session = prompt_session

    def confirm(self, request) -> PermissionConfirmation:
        print(format_permission_request(request))
        answer = self._read_permission_input().strip().lower()
        mapping = {
            "d": "deny",
            "deny": "deny",
            "n": "deny",
            "no": "deny",
            "o": "once",
            "once": "once",
            "s": "session",
            "session": "session",
            "a": "always",
            "always": "always",
            "y": "once",
            "yes": "once",
        }
        return PermissionConfirmation(mapping.get(answer, "deny"))  # type: ignore[arg-type]

    def _read_permission_input(self) -> str:
        prompt = "Permission [d/o/s/a, enter=deny]> "
        if self.prompt_session is None:
            return input(prompt)
        return self.prompt_session.prompt(prompt)


def _format_config_summary(
    provider: Provider,
    config: LLMConfig,
    state: AgentState,
    show_usage: bool | None = None,
    mcp_manager: MCPManager | None = None,
    memory_manager: MemoryManager | None = None,
) -> str:
    summary = f"protocol={provider.name} model={provider.model} base_url={config.base_url}"
    if config.headers:
        summary += f" headers={','.join(sorted(config.headers))}"
    if show_usage is not None:
        summary += f" show_usage={str(show_usage).lower()}"
    summary += (
        f" context_window={config.context.window_tokens}"
        f" context_summary_count={state.context.summary_count}"
        f" context_fuse={str(state.context.summary_fuse_open).lower()}"
    )
    if mcp_manager is not None:
        summary += (
            f" mcp_servers={mcp_manager.active_server_count}/{mcp_manager.server_count}"
            f" mcp_tools={mcp_manager.tool_count}"
            f" mcp_errors={len(mcp_manager.errors)}"
        )
    if memory_manager is not None:
        status = memory_manager.status(state)
        summary += (
            f" memory_enabled={str(status.enabled).lower()}"
            f" memory_session={status.session_id}"
            f" memory_index_bytes={status.index_bytes}"
            f" memory_pending={status.pending_updates}"
        )
    return summary


def _close_mcp(manager: MCPManager | None) -> None:
    if manager is None:
        return
    manager.close()


def _close_mcp_and_return(manager: MCPManager | None, code: int) -> int:
    _close_mcp(manager)
    return code


def _close_resources_and_return(
    manager: MCPManager | None,
    memory_manager: MemoryManager | None,
    code: int,
) -> int:
    _close_mcp(manager)
    if memory_manager is not None:
        memory_manager.close()
    return code


def _format_permission_summary(context: PermissionContext) -> str:
    sources: dict[str, int] = {}
    for rule in context.session_rules + context.rules:
        sources[rule.source] = sources.get(rule.source, 0) + 1
    source_text = ", ".join(f"{source}={count}" for source, count in sorted(sources.items())) or "none"
    return f"permissions mode={context.mode} rules={len(context.session_rules) + len(context.rules)} sources={source_text}"


def _format_context_summary(config: LLMConfig, state: AgentState) -> str:
    return (
        f"context enabled={str(config.context.enabled).lower()}"
        f" window={config.context.window_tokens}"
        f" auto_margin={config.context.auto_margin_tokens}"
        f" manual_margin={config.context.manual_margin_tokens}"
        f" last_input_tokens={state.context.last_input_tokens}"
        f" last_estimated_request_tokens={state.context.last_estimated_request_tokens}"
        f" summary_count={state.context.summary_count}"
        f" failure_count={state.context.summary_failure_count}"
        f" fuse={str(state.context.summary_fuse_open).lower()}"
    )


def _format_memory_summary(memory_manager: MemoryManager | None, state: AgentState) -> str:
    if memory_manager is None:
        return "memory enabled=false"
    status = memory_manager.status(state)
    warnings = "; ".join(status.warnings) if status.warnings else "none"
    error = status.last_error or "none"
    return (
        f"memory enabled={str(status.enabled).lower()}"
        f" session={status.session_id}"
        f" project_notes={status.project_notes}"
        f" user_notes={status.user_notes}"
        f" index_lines={status.index_lines}"
        f" index_bytes={status.index_bytes}"
        f" pending={status.pending_updates}"
        f" last_update={status.last_update_at or 'none'}"
        f" last_error={error}"
        f" warnings={warnings}"
    )


def _format_sessions(memory_manager: MemoryManager | None) -> str:
    if memory_manager is None:
        return "记忆系统未启用"
    sessions = memory_manager.list_sessions()
    if not sessions:
        return "暂无会话存档"
    lines = ["sessions:"]
    for session in sessions[:20]:
        warning_text = f" warnings={len(session.warnings)}" if session.warnings else ""
        lines.append(
            f"- {session.session_id} messages={session.message_count} updated={session.updated_at or 'unknown'}"
            f" title={session.title}{warning_text}"
        )
    return "\n".join(lines)


def _format_resume_choices(memory_manager: MemoryManager | None) -> str:
    sessions_text = _format_sessions(memory_manager)
    if memory_manager is None:
        return sessions_text
    return f"{sessions_text}\n使用 /resume <session-id> 恢复指定会话。"


def _format_resume_report(report) -> str:
    lines = [report.message]
    if report.ok:
        lines.append(
            " ".join(
                [
                    f"restored={report.restored_messages}",
                    f"bad_lines={report.skipped_bad_lines}",
                    f"truncated={str(report.truncated).lower()}",
                    f"time_gap={str(report.time_gap_inserted).lower()}",
                    f"compacted={str(report.compacted).lower()}",
                ]
            )
        )
    for warning in report.warnings:
        lines.append(f"warning: {warning}")
    return "\n".join(lines)


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
    memory_manager: MemoryManager | None = None,
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
        memory=memory_manager,
    ):
        if event.kind == "thinking" and not config.thinking.show:
            continue
        if event.kind == "usage" and not show_usage:
            continue
        render_agent_event(event, sys.stdout)
        if event.kind == "done" and event.stop_reason in {"cancelled", "error"} and len(state.messages) > last_user_count:
            if state.messages and state.messages[-1].role == "user":
                state.messages.pop()
