from .completion import SlashCommandCompleter
from .builtin import REVIEW_PROMPT, create_builtin_registry
from .dispatcher import CommandDispatcher, InputRouter, RouteKind, RouteResult
from .parser import CommandParser
from .registry import CommandRegistrationError, CommandRegistry
from .runtime import CLICommandRuntime
from .types import (
    CommandAlias,
    CommandResult,
    CommandSpec,
    CommandType,
    ParsedCommand,
    normalize_command_name,
)
from .ui import CommandContext, CommandServices, CommandUI

__all__ = [
    "CommandAlias",
    "CommandContext",
    "CommandDispatcher",
    "CommandParser",
    "CommandRegistrationError",
    "CommandRegistry",
    "CommandResult",
    "CommandServices",
    "CommandSpec",
    "CommandType",
    "CommandUI",
    "InputRouter",
    "CLICommandRuntime",
    "ParsedCommand",
    "RouteKind",
    "RouteResult",
    "SlashCommandCompleter",
    "REVIEW_PROMPT",
    "create_builtin_registry",
    "normalize_command_name",
]
