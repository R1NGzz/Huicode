from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from huicode.agent import run_agent_loop
from huicode.agent_events import AgentMode, AgentOptions, AgentState
from huicode.commands import (
    CLICommandRuntime,
    CommandContext,
    CommandRegistrationError,
    InputRouter,
    SlashCommandCompleter,
    create_builtin_registry,
    registry_with_skill_commands,
)
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
from huicode.skills.catalog import SkillCatalogBuilder, SkillConfigError
from huicode.skills.manager import SkillManager, default_skill_roots
from huicode.skills.runner import SkillRunner
from huicode.skills.tool import SkillTool
from huicode.tools.base import ToolContext
from huicode.tools.registry import create_default_registry
from huicode.tui import format_permission_request, render_agent_event

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import DummyCompleter
    from prompt_toolkit.history import InMemoryHistory
except ImportError:  # pragma: no cover - prompt_toolkit 是交互增强，缺失时回退 input()
    PromptSession = None
    DummyCompleter = None
    InMemoryHistory = None


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


def _run_chat(
    provider: Provider,
    config: LLMConfig,
    mcp_transport_factory=None,
    command_registry_factory=None,
) -> int:
    workspace = Path.cwd()
    try:
        base_command_registry = (command_registry_factory or create_builtin_registry)()
    except CommandRegistrationError as exc:
        print(f"命令注册错误: {exc}")
        return 2

    tool_registry = create_default_registry(workspace)
    mcp_manager: MCPManager | None = None
    try:
        mcp_config = load_mcp_config(mcp_config_paths(workspace), inline_mcp=config.mcp)
        mcp_manager = MCPManager(mcp_config, transport_factory=mcp_transport_factory or create_transport)
        mcp_manager.start(tool_registry)
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

    confirmer = ConsolePermissionConfirmer(None)
    permission_context = PermissionContext(
        workspace=workspace,
        mode=permission_config.mode,
        rules=list(permission_config.rules),
        persistent_path=permission_paths.local,
        confirmer=confirmer,
    )
    tool_context = ToolContext(workspace=workspace, permissions=permission_context)
    state = AgentState()
    context_manager = ContextManager(workspace, config.context)
    memory_manager: MemoryManager | None = None
    if config.memory.enabled:
        memory_manager = MemoryManager(workspace, config.memory, config, provider)
        for warning in memory_manager.start(state):
            print(f"记忆提示: {warning}")
    try:
        skill_manager = SkillManager(
            SkillCatalogBuilder(
                default_skill_roots(workspace),
                tool_registry,
                base_command_registry.reserved_names(),
            )
        )
        skill_snapshot = skill_manager.initialize()
        command_registry = registry_with_skill_commands(base_command_registry, skill_snapshot)
    except (SkillConfigError, CommandRegistrationError) as exc:
        _close_mcp(mcp_manager)
        if memory_manager is not None:
            memory_manager.close()
        print(f"Skill 配置错误: {exc}")
        return 2

    runtime_holder = {}

    def run_isolated_skill(name: str, arguments: str):
        runtime_ref = runtime_holder["runtime"]
        mode: AgentMode = "plan" if runtime_ref.get_mode() == "plan" else "chat"
        runner = SkillRunner(
            provider=provider,
            registry=tool_registry,
            context=tool_context,
            config=config,
            manager=skill_manager,
            options=AgentOptions(mode=mode),
        )
        return runner.run(
            name,
            arguments,
            parent_messages=state.messages,
            depth=state.skills.nesting_depth + 1,
        )

    runtime = CLICommandRuntime(
        provider=provider,
        config=config,
        tool_registry=tool_registry,
        tool_context=tool_context,
        state=state,
        context_manager=context_manager,
        permission_context=permission_context,
        memory_manager=memory_manager,
        mcp_manager=mcp_manager,
        skill_manager=skill_manager,
        isolated_skill_runner=run_isolated_skill,
        send_user_message=lambda text, mode, show_usage: _run_request(
            provider,
            tool_registry,
            tool_context,
            state,
            text,
            config,
            mode,
            show_usage,
            memory_manager,
            skill_manager,
        ),
    )
    runtime_holder["runtime"] = runtime
    tool_registry.register(
        SkillTool(skill_manager, state.skills, isolated_runner=run_isolated_skill),
        system=True,
    )
    prompt_session = _create_prompt_session(command_registry, runtime)
    confirmer.prompt_session = prompt_session
    if prompt_session is not None:
        runtime.set_refresh_callback(lambda: prompt_session.app.invalidate())
    command_context = CommandContext(runtime, runtime, command_registry)
    router = InputRouter(command_registry)
    if mcp_manager is not None and mcp_manager.server_count:
        print(
            f"MCP servers={mcp_manager.active_server_count}/{mcp_manager.server_count} "
            f"tools={mcp_manager.tool_count} errors={len(mcp_manager.errors)}"
        )
        for error in mcp_manager.errors:
            print(f"MCP server {error.server} skipped: {error.message}")
    print(
        "Skills "
        f"effective={len(skill_snapshot.definitions)} "
        f"overridden={skill_snapshot.overridden_count} "
        f"skipped={skill_snapshot.skipped_count} "
        f"warnings={len(skill_snapshot.warnings)}"
    )
    for warning in skill_snapshot.warnings:
        print(f"Skill warning: {warning.display()}")
    print(f"HuiCode 已连接: {provider.name}:{provider.model}")
    print("输入 /help 查看命令；/plan 进入计划模式，/do 返回默认模式。")

    last_reload_error = ""
    while True:
        try:
            user_text = _read_user_input(prompt_session, runtime)
        except EOFError:
            print()
            return _close_resources_and_return(mcp_manager, memory_manager, 0)
        except KeyboardInterrupt:
            print("\n已中断输入。输入 /exit 可退出。")
            continue

        if skill_manager.reload_if_changed(state.skills):
            try:
                command_registry = registry_with_skill_commands(
                    base_command_registry,
                    skill_manager.snapshot,
                )
            except CommandRegistrationError as exc:
                state.skills.reload_error = str(exc)
            else:
                command_context.registry = command_registry
                router = InputRouter(command_registry)
                if prompt_session is not None:
                    completer = getattr(prompt_session, "completer", None)
                    if hasattr(completer, "set_registry"):
                        completer.set_registry(command_registry)
                runtime.refresh_status()
        if state.skills.reload_error and state.skills.reload_error != last_reload_error:
            print(f"Skill 热更新失败，继续使用上一有效版本: {state.skills.reload_error}")
            last_reload_error = state.skills.reload_error
        elif not state.skills.reload_error:
            last_reload_error = ""

        router.route(user_text, command_context)
        if runtime.exit_requested:
            return _close_resources_and_return(mcp_manager, memory_manager, 0)


def _create_prompt_session(command_registry, runtime):  # noqa: ANN001
    if PromptSession is None or InMemoryHistory is None or not sys.stdin.isatty():
        return None
    try:
        return PromptSession(
            history=InMemoryHistory(),
            completer=SlashCommandCompleter(command_registry),
            complete_while_typing=True,
            bottom_toolbar=runtime.toolbar_text,
        )
    except Exception:
        return None


def _read_user_input(prompt_session, runtime: CLICommandRuntime) -> str:
    if prompt_session is None:
        return input(runtime.input_prompt())
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
        previous_completer = self.prompt_session.completer
        previous_complete_while_typing = self.prompt_session.complete_while_typing
        try:
            return self.prompt_session.prompt(
                prompt,
                completer=DummyCompleter() if DummyCompleter is not None else None,
                complete_while_typing=False,
            )
        finally:
            self.prompt_session.completer = previous_completer
            self.prompt_session.complete_while_typing = previous_complete_while_typing


def _close_mcp(manager: MCPManager | None) -> None:
    if manager is None:
        return
    manager.close()


def _close_resources_and_return(
    manager: MCPManager | None,
    memory_manager: MemoryManager | None,
    code: int,
) -> int:
    _close_mcp(manager)
    if memory_manager is not None:
        memory_manager.close()
    return code


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
    skill_manager: SkillManager | None = None,
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
        skill_manager=skill_manager,
    ):
        if event.kind == "thinking" and not config.thinking.show:
            continue
        if event.kind == "usage" and not show_usage:
            continue
        render_agent_event(event, sys.stdout)
        if event.kind == "done" and event.stop_reason in {"cancelled", "error"} and len(state.messages) > last_user_count:
            if state.messages and state.messages[-1].role == "user":
                state.messages.pop()
