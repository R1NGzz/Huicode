from __future__ import annotations

import re

from huicode.permissions.base import PermissionDecision


DANGEROUS_COMMAND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(^|[;&|]\s*)rm\s+(-[^\s]*r[^\s]*f|-rf|-fr)\s+(/|\*|[A-Za-z]:\\)"), "recursive force delete"),
    (re.compile(r"(?i)\bgit\s+reset\s+--hard\b"), "git hard reset"),
    (re.compile(r"(?i)\bgit\s+clean\s+-[^\s]*[fdx][^\s]*\b"), "git clean destructive"),
    (re.compile(r"(?i)\b(format|mkfs(?:\.[A-Za-z0-9]+)?)\b"), "disk format"),
    (re.compile(r"(?i)\bdiskpart\b"), "disk partition tool"),
    (re.compile(r"(?i)\bchmod\s+-R\s+777\b"), "recursive broad permission change"),
    (re.compile(r"(?i)\btakeown\s+/f\b.*\s+/r\b"), "recursive ownership change"),
    (re.compile(r"(?i)\bdel\s+/(?:s|q|f)[^\r\n]*(C:\\Windows|C:\\Users|%SystemRoot%)"), "system directory delete"),
    (re.compile(r"(?i)\brmdir\s+/(?:s|q)[^\r\n]*(C:\\Windows|C:\\Users|%SystemRoot%)"), "system directory delete"),
)


def check_dangerous_command(command: str) -> PermissionDecision | None:
    for pattern, reason in DANGEROUS_COMMAND_PATTERNS:
        if pattern.search(command):
            return PermissionDecision(
                allowed=False,
                reason=f"危险命令被黑名单拦截: {reason}",
                source="blacklist",
                risk="high",
            )
    return None

