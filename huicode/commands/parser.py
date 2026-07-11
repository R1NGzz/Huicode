from __future__ import annotations

import re

from .types import ParsedCommand


class CommandParser:
    def parse(self, text: str) -> ParsedCommand | None:
        stripped = text.strip()
        if not stripped or not stripped.startswith("/"):
            return None
        match = re.match(r"^(\S+)(?:\s+(.*))?$", stripped, flags=re.DOTALL)
        if match is None:
            return None
        token = match.group(1)
        arguments = (match.group(2) or "").rstrip()
        return ParsedCommand(raw=text, name=token[1:].lower(), arguments=arguments)
