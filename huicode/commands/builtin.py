from __future__ import annotations

from .registry import CommandRegistry
from .types import CommandResult, CommandSpec, CommandType, ParsedCommand
from .ui import CommandContext


def create_builtin_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register_many(
        (
            _spec("help", "查看命令帮助", "/help [command]", CommandType.LOCAL, _help, "[command]"),
            _spec("compact", "手动压缩上下文", "/compact", CommandType.LOCAL, _compact),
            _spec("clear", "清空当前工作上下文", "/clear", CommandType.STATE, _clear),
            _spec("plan", "进入计划模式", "/plan", CommandType.STATE, _plan),
            _spec("do", "返回默认执行模式", "/do", CommandType.STATE, _do),
            _spec(
                "session",
                "管理会话存档",
                "/session [resume <session-id>|clean]",
                CommandType.LOCAL,
                _session,
                "[resume <session-id>|clean]",
            ),
            _spec(
                "memory",
                "查看或整理长期记忆",
                "/memory [update|rebuild]",
                CommandType.LOCAL,
                _memory,
                "[update|rebuild]",
            ),
            _spec(
                "permission",
                "查看或切换权限模式",
                "/permission [strict|default|permissive]",
                CommandType.STATE,
                _permission,
                "[strict|default|permissive]",
            ),
            _spec("status", "查看 HuiCode 运行状态", "/status", CommandType.LOCAL, _status),
        )
    )
    registry.register_many(
        (
            _hidden("sessions", "/sessions [clean]", _legacy_sessions),
            _hidden("resume", "/resume [session-id]", _legacy_resume),
            _hidden("permissions", "/permissions [mode]", _legacy_permission),
            _hidden("perm", "/perm [mode]", _legacy_permission),
            _hidden("config", "/config", _legacy_status),
            _hidden("context", "/context", _legacy_context),
            _hidden("verbose", "/verbose", _legacy_verbose),
            _hidden("last", "/last [count]", _legacy_last),
            _hidden("exit", "/exit", _exit),
            _hidden("quit", "/quit", _exit),
        )
    )
    return registry


def _spec(
    name: str,
    description: str,
    usage: str,
    command_type: CommandType,
    handler,
    argument_hint: str = "",
) -> CommandSpec:
    return CommandSpec(
        name=name,
        aliases=(),
        description=description,
        usage=usage,
        command_type=command_type,
        handler=handler,
        argument_hint=argument_hint,
    )


def _hidden(name: str, usage: str, handler) -> CommandSpec:  # noqa: ANN001
    return CommandSpec(
        name=name,
        aliases=(),
        description="兼容命令",
        usage=usage,
        command_type=CommandType.LOCAL,
        handler=handler,
        hidden=True,
    )


def _reject_arguments(parsed: ParsedCommand, usage: str) -> CommandResult | None:
    if parsed.arguments:
        return CommandResult(ok=False, message=f"用法: {usage}")
    return None


def _help(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    target = parsed.arguments.strip().lstrip("/")
    if target:
        spec = context.registry.resolve(target)
        if spec is None or spec.hidden:
            return CommandResult(ok=False, message=f"没有可见命令 /{target}。输入 /help 查看可用命令。")
        aliases = [f"/{alias.name}" for alias in spec.aliases if not alias.hidden]
        lines = [spec.usage, spec.description, f"类型: {_type_label(spec.command_type)}"]
        if aliases:
            lines.append(f"别名: {', '.join(aliases)}")
        if spec.argument_hint:
            lines.append(f"参数: {spec.argument_hint}")
        lines.append(f"示例: {spec.usage}")
        return CommandResult(message="\n".join(lines))

    groups = (
        (CommandType.LOCAL, "本地命令"),
        (CommandType.STATE, "状态命令"),
        (CommandType.PROMPT, "提示词命令"),
        (CommandType.SKILL, "Skill 命令"),
    )
    lines: list[str] = []
    visible = context.registry.visible_commands()
    for command_type, title in groups:
        commands = [spec for spec in visible if spec.command_type == command_type]
        if not commands:
            continue
        if lines:
            lines.append("")
        lines.append(title)
        for spec in commands:
            lines.append(f"  {spec.usage:<46} {spec.description}")
    return CommandResult(message="\n".join(lines))


def _compact(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    invalid = _reject_arguments(parsed, "/compact")
    return invalid or CommandResult(message=context.services.compact())


def _clear(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    invalid = _reject_arguments(parsed, "/clear")
    return invalid or CommandResult(message=context.services.clear())


def _plan(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    invalid = _reject_arguments(parsed, "/plan")
    if invalid:
        return invalid
    context.ui.set_mode("plan")
    context.ui.refresh_status()
    return CommandResult(message="已进入 [PLAN]，后续普通输入只使用读类工具。")


def _do(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    invalid = _reject_arguments(parsed, "/do")
    if invalid:
        return invalid
    context.ui.set_mode("default")
    context.ui.refresh_status()
    return CommandResult(message="已返回 [DEFAULT]。")


def _session(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    arguments = parsed.arguments.strip()
    lowered = arguments.lower()
    if not arguments or lowered == "clean":
        return CommandResult(message=context.services.session(lowered))
    parts = arguments.split(maxsplit=1)
    if len(parts) == 2 and parts[0].lower() == "resume" and parts[1].strip():
        return CommandResult(message=context.services.session(f"resume {parts[1].strip()}"))
    return CommandResult(ok=False, message="用法: /session [resume <session-id>|clean]")


def _memory(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    arguments = parsed.arguments.strip().lower()
    if arguments not in {"", "update", "rebuild"}:
        return CommandResult(ok=False, message="用法: /memory [update|rebuild]")
    return CommandResult(message=context.services.memory(arguments))


def _permission(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    arguments = parsed.arguments.strip().lower()
    if arguments not in {"", "strict", "default", "permissive"}:
        return CommandResult(ok=False, message="用法: /permission [strict|default|permissive]")
    message = context.services.permission(arguments)
    if arguments:
        context.ui.refresh_status()
    return CommandResult(message=message)


def _status(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    invalid = _reject_arguments(parsed, "/status")
    return invalid or CommandResult(message=context.services.status())


def _legacy_sessions(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    return _session(
        ParsedCommand(parsed.raw, "session", parsed.arguments),
        context,
    )


def _legacy_resume(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    arguments = parsed.arguments.strip()
    if not arguments:
        return CommandResult(message=context.services.session(""))
    if len(arguments.split()) != 1:
        return CommandResult(ok=False, message="用法: /resume <session-id>")
    return CommandResult(message=context.services.session(f"resume {arguments}"))


def _legacy_permission(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    return _permission(
        ParsedCommand(parsed.raw, "permission", parsed.arguments),
        context,
    )


def _legacy_status(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    invalid = _reject_arguments(parsed, f"/{parsed.name}")
    return invalid or CommandResult(message=context.services.status())


def _legacy_context(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    invalid = _reject_arguments(parsed, "/context")
    return invalid or CommandResult(message=context.services.context_status())


def _legacy_verbose(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    invalid = _reject_arguments(parsed, "/verbose")
    return invalid or CommandResult(message=context.services.toggle_verbose())


def _legacy_last(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    return CommandResult(message=context.services.last(parsed.arguments))


def _exit(parsed: ParsedCommand, context: CommandContext) -> CommandResult:
    invalid = _reject_arguments(parsed, f"/{parsed.name}")
    return invalid or CommandResult(exit_requested=True)


def _type_label(command_type: CommandType) -> str:
    return {
        CommandType.LOCAL: "本地",
        CommandType.STATE: "状态",
        CommandType.PROMPT: "提示词",
        CommandType.SKILL: "Skill",
    }[command_type]
