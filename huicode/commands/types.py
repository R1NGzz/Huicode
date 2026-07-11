from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .ui import CommandContext


_COMMAND_NAME_RE = re.compile(r"^[a-z0-9_-]+$")


class CommandType(str, Enum):
    LOCAL = "local"
    STATE = "state"
    PROMPT = "prompt"


@dataclass(frozen=True)
class CommandAlias:
    name: str
    hidden: bool = False


@dataclass(frozen=True)
class ParsedCommand:
    raw: str
    name: str
    arguments: str = ""


@dataclass(frozen=True)
class CommandResult:
    ok: bool = True
    exit_requested: bool = False
    message: str = ""


CommandHandler = Callable[[ParsedCommand, "CommandContext"], CommandResult]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    usage: str
    command_type: CommandType
    handler: CommandHandler
    aliases: tuple[CommandAlias, ...] = ()
    argument_hint: str = ""
    hidden: bool = False


def normalize_command_name(name: str) -> str:
    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("命令名不能为空")
    if normalized.startswith("/"):
        raise ValueError(f"命令名不能包含斜杠: {name}")
    if not _COMMAND_NAME_RE.fullmatch(normalized):
        raise ValueError(f"命令名只能包含字母、数字、连字符和下划线: {name}")
    return normalized
