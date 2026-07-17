from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path

from huicode.agent import AgentPromptOverrides, build_agent_prompt, run_agent_loop, select_tools
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
from huicode.hooks import HookConfigError, HookManager, hook_config_paths, load_hook_catalog
from huicode.hooks.events import make_event
from huicode.memory.manager import MemoryManager
from huicode.memory.codec import message_from_json, message_to_json
from huicode.memory.recovery import recover_safe_messages
from huicode.mcp import MCPConfigError, MCPManager, load_mcp_config, mcp_config_paths
from huicode.mcp.transport import create_transport
from huicode.permissions import (
    PermissionConfigError,
    PermissionConfirmation,
    PermissionContext,
    load_permission_config,
    permission_config_paths,
    clone_permission_context,
)
from huicode.provider_factory import create_provider
from huicode.providers.base import Provider
from huicode.skills.catalog import SkillCatalogBuilder, SkillConfigError
from huicode.skills.manager import SkillManager, default_skill_roots
from huicode.skills.runner import SkillRunner
from huicode.skills.tool import SkillTool
from huicode.subagents import (
    AgentCatalog,
    AgentTool,
    SubagentConfigError,
    SubagentManager,
    default_agent_roots,
)
from huicode.subagents.runner import IsolatedSubagentRunner
from huicode.subagents.types import ParentAgentSnapshot, PermissionSnapshot
from huicode.tools.base import FileReadCache, ToolContext
from huicode.tools.registry import create_default_registry
from huicode.teams.manager import TeamManager
from huicode.teams.scoping import ScopedToolRegistry
from huicode.teams.tools import register_team_tools
from huicode.teams.types import TeamRuntimeIdentity
from huicode.teams.storage import TeamStore, append_jsonl, read_jsonl
from huicode.teams.mailbox import MailboxStore, NameRegistry
from huicode.teams.tasks import SharedTaskStore
from huicode.teams.approval import ApprovalGate
from huicode.teams.backends import BackendHandle, MemberLaunchSpec
from huicode.teams.member_runner import TeamMemberRunner
from huicode.teams.tools import TeamMessageTool, TeamPlanRequestTool, TeamTaskTool
from huicode.tui import format_permission_request, render_agent_event
from huicode.workspaces import WorkspaceContextLoader
from huicode.worktrees import WorktreeManager
from huicode.worktrees.cleanup import WorktreeCleanupService

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
    parser.add_argument("--team-worker", default="", help=argparse.SUPPRESS)
    parser.add_argument("--member-id", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        provider = create_provider(config)
    except (ConfigError, OSError, ValueError) as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    if args.team_worker:
        return _run_team_worker(provider, config, Path(args.team_worker), args.member_id)
    return _run_chat(provider, config, config_path=args.config)


def _run_chat(
    provider: Provider,
    config: LLMConfig,
    mcp_transport_factory=None,
    command_registry_factory=None,
    config_path: str = "",
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
    tool_context = ToolContext(
        workspace=workspace,
        permissions=permission_context,
        read_cache=FileReadCache(),
    )
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

    try:
        agent_catalog = AgentCatalog(
            default_agent_roots(workspace),
            tool_registry,
            config.subagents,
        )
        agent_snapshot = agent_catalog.initialize()
    except SubagentConfigError as exc:
        _close_mcp(mcp_manager)
        if memory_manager is not None:
            memory_manager.close()
        print(f"子 Agent 配置错误: {exc}")
        return 2

    try:
        hook_catalog = load_hook_catalog(hook_config_paths(workspace), inline_hooks=config.hooks)
        hook_manager = HookManager(hook_catalog, workspace)
    except HookConfigError as exc:
        _close_mcp(mcp_manager)
        if memory_manager is not None:
            memory_manager.close()
        print(f"Hook 配置错误: {exc}")
        return 2

    worktree_manager = WorktreeManager(workspace, config.worktrees)
    workspace_context_loader = WorkspaceContextLoader(config.memory)
    worktree_cleanup = WorktreeCleanupService(worktree_manager)
    worktree_cleanup.start()

    team_manager: TeamManager | None = None
    team_states: dict[str, AgentState] = {}
    team_saved_counts: dict[str, int] = {}

    def execute_team_assignment(member: str, task_id: str, prompt: str, member_workspace: Path):
        if team_manager is None:
            return False, "Team Manager 不可用", {}
        if member not in team_states:
            restored = AgentState()
            if team_manager.store is not None:
                records, _ = read_jsonl(team_manager.store.paths.member_session(member))
                messages = []
                for record in records:
                    if record.get("type") == "message" and isinstance(record.get("message"), dict):
                        try:
                            messages.append(message_from_json(record["message"]))
                        except Exception:
                            continue
                restored.messages = recover_safe_messages(messages)[0]
            team_states[member] = restored
            team_saved_counts[member] = len(restored.messages)
        member_state = team_states[member]
        member_permission = clone_permission_context(permission_context, member_workspace)
        member_context = ToolContext(
            workspace=member_workspace,
            permissions=member_permission,
            read_cache=FileReadCache(),
        )
        member_registry = ScopedToolRegistry(
            tool_registry,
            TeamRuntimeIdentity("team_member", team_manager.team.id if team_manager.team else None, member),
            approval_gate=team_manager.approvals,
            task_id=task_id,
        )
        text_parts: list[str] = []
        usage: dict[str, object] = {}
        stop_reason = "error"
        role_block = (
            '<huicode_instruction type="team_member" priority="highest">\n'
            f"你是团队 {team_manager.team.name if team_manager.team else ''} 的成员 {member}。\n"
            f"当前共享任务 ID: {task_id}。只在当前独立 Worktree {member_workspace} 内工作。\n"
            "使用 TeamTask 和 TeamMessage 与团队协作；完成后给出清晰结果。\n"
            "</huicode_instruction>"
        )
        for event in run_agent_loop(
            provider=provider,
            registry=member_registry,
            context=member_context,
            state=member_state,
            user_text=prompt,
            config=config,
            options=AgentOptions(max_iterations=50),
            hook_manager=hook_manager,
            context_manager=ContextManager(member_workspace, config.context),
            agent_scope=f"team_member:{member}",
            prompt_overrides=AgentPromptOverrides(role_instruction_blocks=(role_block,)),
        ):
            if event.kind == "text":
                text_parts.append(event.text)
            elif event.kind == "usage":
                usage.update(event.data.get("usage", {}))
            elif event.kind == "done":
                stop_reason = event.stop_reason
        summary = "".join(text_parts).strip() or f"成员停止: {stop_reason}"
        if team_manager.store is not None:
            session_path = team_manager.store.paths.member_session(member)
            for message in member_state.messages[team_saved_counts.get(member, 0):]:
                append_jsonl(session_path, {"type": "message", "message": message_to_json(message), "task_id": task_id})
            team_saved_counts[member] = len(member_state.messages)
        return stop_reason == "final", summary, usage

    if config.teams.enabled:
        team_manager = TeamManager(
            workspace,
            config.teams,
            worktree_manager,
            assignment_executor=execute_team_assignment,
            config_path=str(Path(config_path).resolve()) if config_path else "",
            agent_catalog=agent_catalog,
        )
        register_team_tools(tool_registry, team_manager)

    subagent_runner = IsolatedSubagentRunner(
        provider=provider,
        registry=tool_registry,
        context=tool_context,
        config=config,
        catalog=agent_catalog,
        hook_manager=hook_manager,
        worktree_manager=worktree_manager,
        workspace_context_loader=workspace_context_loader,
    )
    subagent_manager = SubagentManager(
        agent_catalog,
        config.subagents,
        subagent_runner,
    )
    tool_registry.register(AgentTool(subagent_manager), system=True)
    hook_manager.set_subagent_submitter(
        lambda role, task: subagent_manager.submit_defined_background(role, task).id
    )

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
            hook_manager=hook_manager,
            context_manager=context_manager,
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
        hook_manager=hook_manager,
        agent_catalog=agent_catalog,
        subagent_manager=subagent_manager,
        team_manager=team_manager,
        send_user_message=lambda text, mode, show_usage: _run_request(
            provider,
            _team_scoped_registry(tool_registry, team_manager, config),
            tool_context,
            state,
            text,
            config,
            mode,
            show_usage,
            memory_manager,
            skill_manager,
            context_manager,
            hook_manager,
            subagent_manager,
            team_manager,
        ),
    )
    runtime_holder["runtime"] = runtime
    tool_registry.register(
        SkillTool(skill_manager, state.skills, isolated_runner=run_isolated_skill),
        system=True,
    )
    initial_options = AgentOptions()
    initial_prompt = build_agent_prompt(
        context=tool_context,
        registry=tool_registry,
        state=state,
        options=initial_options,
        iteration=1,
        skill_manager=skill_manager,
        hook_manager=hook_manager,
        subagent_manager=subagent_manager,
    )
    initial_tools = select_tools(tool_registry, initial_options, state, skill_manager)
    subagent_manager.capture_parent(
        ParentAgentSnapshot(
            messages=tuple(deepcopy(state.messages)),
            prompt=initial_prompt,
            visible_tools=tuple(tool.name for tool in initial_tools),
            mode="chat",
            permissions=PermissionSnapshot(
                clone_permission_context(permission_context, workspace)
            ),
            project_instructions=state.memory.instructions_text,
        )
    )
    prompt_session = _create_prompt_session(command_registry, runtime)
    confirmer.prompt_session = prompt_session
    if prompt_session is not None:
        runtime.set_refresh_callback(lambda: prompt_session.app.invalidate())
    command_context = CommandContext(runtime, runtime, command_registry)
    router = InputRouter(command_registry)
    hook_manager.start_session(
        make_event(
            "session_start",
            session_id=hook_manager.session_id,
            workspace=workspace,
            mode="chat",
            data={
                "session": {
                    "hook_sources": dict(hook_catalog.source_counts),
                    "effective_hooks": hook_catalog.effective_count,
                }
            },
        ),
        state.hooks,
    )
    notification_stop = threading.Event()
    threading.Thread(
        target=_subagent_notification_pump,
        args=(subagent_manager, prompt_session, notification_stop),
        name="huicode-subagent-notifications",
        daemon=True,
    ).start()
    if team_manager is not None:
        threading.Thread(
            target=_team_notification_pump,
            args=(team_manager, prompt_session, notification_stop),
            name="huicode-team-notifications",
            daemon=True,
        ).start()
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
    agent_sources = ",".join(
        f"{source}={count}" for source, count in sorted(agent_snapshot.source_counts.items())
    ) or "none"
    print(
        f"Agents effective={len(agent_snapshot.definitions)} "
        f"overridden={agent_snapshot.overridden_count} skipped={agent_snapshot.skipped_count} "
        f"sources={agent_sources}"
    )
    for warning in agent_snapshot.warnings:
        print(f"Agent warning: {warning.display()}")
    hook_status = hook_manager.summary()
    hook_sources = ",".join(
        f"{source}={count}" for source, count in sorted(hook_status.source_counts.items())
    ) or "none"
    print(
        f"Hooks effective={hook_status.effective} disabled={hook_status.disabled} "
        f"sources={hook_sources}"
    )
    team_state = "enabled" if team_manager is not None else "disabled"
    print(f"Team {team_state} backend={config.teams.default_backend}")
    print(f"HuiCode 已连接: {provider.name}:{provider.model}")
    print("输入 /help 查看命令；/plan 进入计划模式，/do 返回默认模式。")

    last_reload_error = ""
    while True:
        try:
            user_text = _read_user_input(prompt_session, runtime)
        except EOFError:
            print()
            return _close_resources_and_return(
                mcp_manager,
                memory_manager,
                0,
                hook_manager=hook_manager,
                state=state,
                mode="plan" if runtime.get_mode() == "plan" else "chat",
                reason="eof",
                subagent_manager=subagent_manager,
                notification_stop=notification_stop,
                worktree_cleanup=worktree_cleanup,
                team_manager=team_manager,
            )
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
            return _close_resources_and_return(
                mcp_manager,
                memory_manager,
                0,
                hook_manager=hook_manager,
                state=state,
                mode="plan" if runtime.get_mode() == "plan" else "chat",
                reason="exit",
                subagent_manager=subagent_manager,
                notification_stop=notification_stop,
                worktree_cleanup=worktree_cleanup,
                team_manager=team_manager,
            )


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
    *,
    hook_manager: HookManager | None = None,
    state: AgentState | None = None,
    mode: AgentMode = "chat",
    reason: str = "exit",
    subagent_manager: SubagentManager | None = None,
    notification_stop: threading.Event | None = None,
    worktree_cleanup: WorktreeCleanupService | None = None,
    team_manager: TeamManager | None = None,
) -> int:
    if notification_stop is not None:
        notification_stop.set()
    if worktree_cleanup is not None:
        worktree_cleanup.close()
    if team_manager is not None:
        team_manager.close()
    if subagent_manager is not None:
        subagent_manager.close()
    if hook_manager is not None:
        hook_manager.close(
            make_event(
                "session_end",
                session_id=hook_manager.session_id,
                workspace=hook_manager.workspace,
                mode=mode,
                iteration=state.iterations if state is not None else 0,
                data={"session": {"reason": reason}},
            ),
            state.hooks if state is not None else None,
        )
    if memory_manager is not None:
        memory_manager.close()
    _close_mcp(manager)
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
    context_manager: ContextManager | None = None,
    hook_manager: HookManager | None = None,
    subagent_manager: SubagentManager | None = None,
    team_manager: TeamManager | None = None,
) -> None:
    options = AgentOptions(mode=mode)
    last_user_count = len(state.messages)
    team_block = ()
    if team_manager is not None and team_manager.team is not None:
        team_status = team_manager.status()
        coordinator = config.teams.coordinator_enabled and os.environ.get("HUICODE_COORDINATOR") == "1"
        team_block = (
            '<huicode_instruction type="team_lead" priority="highest">\n'
            f"你是团队 {team_status['team']} 的 Team Lead。成员和任务状态: {team_status}。\n"
            "使用 TeamTask、TeamMessage、TeamPlanDecision 和 TeamIntegrate 组织协作。\n"
            f"Coordinator 模式: {str(coordinator).lower()}。\n"
            "</huicode_instruction>",
        )
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
        context_manager=context_manager,
        hook_manager=hook_manager,
        subagent_manager=subagent_manager,
        prompt_overrides=AgentPromptOverrides(role_instruction_blocks=team_block),
    ):
        if event.kind == "thinking" and not config.thinking.show:
            continue
        if event.kind == "usage" and not show_usage:
            continue
        render_agent_event(event, sys.stdout)
        if event.kind == "done" and event.stop_reason in {"cancelled", "error"} and len(state.messages) > last_user_count:
            if state.messages and state.messages[-1].role == "user":
                state.messages.pop()


def _subagent_notification_pump(
    manager: SubagentManager,
    prompt_session,
    stop_event: threading.Event,
) -> None:  # noqa: ANN001
    while not stop_event.wait(0.1):
        for notice in manager.drain_notifications():
            role = notice.role or "fork"
            message = (
                f"\nHuiCode> 子 Agent {notice.task_id} [{notice.type}/{role}] "
                f"{notice.status} ({notice.duration_seconds:.2f}s)\n  {notice.summary}"
            )
            if notice.worktree_path:
                message += (
                    f"\n  worktree: {notice.worktree_state} "
                    f"{notice.worktree_branch} {notice.worktree_path}"
                )
            if prompt_session is not None:
                try:
                    from prompt_toolkit.application import run_in_terminal

                    run_in_terminal(lambda text=message: print(text))
                    continue
                except Exception:
                    pass
            print(message)


def _team_scoped_registry(registry, manager: TeamManager | None, config: LLMConfig):  # noqa: ANN001, ANN201
    if manager is None:
        return registry
    if manager.team is None:
        identity = TeamRuntimeIdentity("main")
    else:
        coordinator = config.teams.coordinator_enabled and os.environ.get("HUICODE_COORDINATOR") == "1"
        identity = TeamRuntimeIdentity("team_lead", manager.team.id, coordinator=coordinator)
    return ScopedToolRegistry(registry, identity)


def _team_notification_pump(manager: TeamManager, prompt_session, stop_event: threading.Event) -> None:  # noqa: ANN001
    while not stop_event.wait(0.1):
        for event in manager.drain_events():
            message = f"\nHuiCode> Team[{event.team}] {event.kind}: {event.message}"
            if prompt_session is not None:
                try:
                    from prompt_toolkit.application import run_in_terminal
                    run_in_terminal(lambda text=message: print(text))
                    continue
                except Exception:
                    pass
            print(message)


def _run_team_worker(provider: Provider, config: LLMConfig, team_path: Path, member_id: str) -> int:
    """独立终端成员入口；通信和状态完全通过团队目录完成。"""
    try:
        resolved = team_path.resolve()
        store = TeamStore(resolved.parent, resolved.name, config.teams)
        team = store.load_team()
        member = next((item for item in store.load_members() if item.id == member_id), None)
        if member is None:
            raise ValueError(f"团队中不存在成员 ID: {member_id}")
        workspace = Path(member.worktree_path).resolve()
        if not workspace.exists():
            raise ValueError(f"成员 Worktree 不存在: {workspace}")
    except Exception as exc:
        print(f"Team Worker 启动失败: {exc}", file=sys.stderr)
        return 2

    registry_names = NameRegistry(("lead", *(item.name for item in store.load_members())))
    mailbox = MailboxStore(store, registry_names)
    tasks = SharedTaskStore(store)
    approvals = ApprovalGate(store, mailbox)

    class WorkerFacade:
        def __init__(self) -> None:
            self.approvals = approvals
        def _require_tasks(self): return tasks  # noqa: ANN202
        def _require_mailbox(self): return mailbox  # noqa: ANN202
        def send_message(self, sender, recipients, body): return mailbox.send(sender, recipients, body)  # noqa: ANN001, ANN202

    facade = WorkerFacade()
    registry = create_default_registry(workspace)
    registry.register(TeamTaskTool(facade))  # type: ignore[arg-type]
    registry.register(TeamMessageTool(facade))  # type: ignore[arg-type]
    registry.register(TeamPlanRequestTool(facade))  # type: ignore[arg-type]
    scoped = ScopedToolRegistry(registry, TeamRuntimeIdentity("team_member", team.id, member.name), approval_gate=approvals)
    permission_paths = permission_config_paths(workspace)
    permission_config = load_permission_config(permission_paths)
    permission = PermissionContext(workspace=workspace, mode=permission_config.mode, rules=list(permission_config.rules), persistent_path=permission_paths.local, confirmer=ConsolePermissionConfirmer(None))
    state = AgentState()
    records, _ = read_jsonl(store.paths.member_session(member.name))
    messages = []
    for record in records:
        if record.get("type") == "message" and isinstance(record.get("message"), dict):
            try:
                messages.append(message_from_json(record["message"]))
            except Exception:
                continue
    state.messages = recover_safe_messages(messages)[0]
    saved_count = len(state.messages)

    def execute(member_name: str, task_id: str, prompt: str, member_workspace: Path):
        nonlocal saved_count
        scoped.task_id = task_id
        text_parts: list[str] = []
        usage: dict[str, object] = {}
        stop_reason = "error"
        block = (
            '<huicode_instruction type="team_member" priority="highest">\n'
            f"你是团队 {team.name} 的成员 {member_name}，任务 ID 为 {task_id}。\n"
            f"只在独立 Worktree {member_workspace} 中工作，并通过 TeamTask/TeamMessage 协作。\n"
            "</huicode_instruction>"
        )
        for event in run_agent_loop(provider, scoped, ToolContext(member_workspace, permissions=permission, read_cache=FileReadCache()), state, prompt, config, AgentOptions(max_iterations=50), context_manager=ContextManager(member_workspace, config.context), agent_scope=f"team_member:{member_name}", prompt_overrides=AgentPromptOverrides(role_instruction_blocks=(block,))):
            if event.kind == "text": text_parts.append(event.text)
            elif event.kind == "usage": usage.update(event.data.get("usage", {}))
            elif event.kind == "done": stop_reason = event.stop_reason
        for message in state.messages[saved_count:]:
            append_jsonl(store.paths.member_session(member.name), {"type": "message", "message": message_to_json(message), "task_id": task_id})
        saved_count = len(state.messages)
        return stop_reason == "final", "".join(text_parts).strip() or f"成员停止: {stop_reason}", usage

    runner = TeamMemberRunner(mailbox, tasks, execute, approval_gate=approvals, approval_required=lambda _: member.approval_required, poll_ms=config.teams.member_idle_poll_ms)
    print(f"HuiCode Team Worker: {team.name}/{member.name} backend={member.actual_backend} worktree={workspace}")
    try:
        runner.run(MemberLaunchSpec(str(resolved), member.id, member.name, str(workspace)), BackendHandle(member.actual_backend, member.id))
    except KeyboardInterrupt:
        return 130
    return 0
