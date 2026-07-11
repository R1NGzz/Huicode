from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .parser import CommandParser
from .registry import CommandRegistry
from .types import CommandResult, ParsedCommand
from .ui import CommandContext


class RouteKind(str, Enum):
    IGNORED = "ignored"
    MESSAGE = "message"
    COMMAND = "command"


@dataclass(frozen=True)
class RouteResult:
    kind: RouteKind
    command_result: CommandResult | None = None


class CommandDispatcher:
    def __init__(self, registry: CommandRegistry) -> None:
        self.registry = registry

    def dispatch(self, parsed: ParsedCommand, context: CommandContext) -> CommandResult:
        spec = self.registry.resolve(parsed.name)
        if spec is None:
            shown_name = f"/{parsed.name}" if parsed.name else "/"
            message = f"未知命令 {shown_name}。输入 /help 查看可用命令。"
            context.ui.show_message(message, error=True)
            return CommandResult(ok=False)
        try:
            result = spec.handler(parsed, context)
        except Exception as exc:  # noqa: BLE001 - 命令边界必须保持 CLI 可用
            context.ui.show_message(
                f"命令 /{spec.name} 执行失败: {exc}",
                error=True,
            )
            return CommandResult(ok=False)
        if result.message:
            context.ui.show_message(result.message, error=not result.ok)
        if result.exit_requested:
            context.services.request_exit()
        return result


class InputRouter:
    def __init__(
        self,
        registry: CommandRegistry,
        parser: CommandParser | None = None,
        dispatcher: CommandDispatcher | None = None,
    ) -> None:
        self.registry = registry
        self.parser = parser or CommandParser()
        self.dispatcher = dispatcher or CommandDispatcher(registry)

    def route(self, text: str, context: CommandContext) -> RouteResult:
        if not text.strip():
            return RouteResult(RouteKind.IGNORED)
        parsed = self.parser.parse(text)
        if parsed is None:
            context.ui.send_user_message(text.strip())
            return RouteResult(RouteKind.MESSAGE)
        result = self.dispatcher.dispatch(parsed, context)
        return RouteResult(RouteKind.COMMAND, result)
