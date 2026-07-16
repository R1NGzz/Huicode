from __future__ import annotations

import re
import uuid
from pathlib import Path

from .types import TeamError


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def validate_name(value: str, kind: str = "名称") -> str:
    name = value.strip()
    if name != value or not _SAFE_NAME.fullmatch(name) or name.lower() in _WINDOWS_RESERVED:
        raise TeamError("invalid_name", f"{kind}只允许 1-48 位字母、数字、下划线和短横线，且必须以字母或数字开头")
    return name.lower()


def team_path(root: Path, name: str) -> Path:
    safe = validate_name(name, "团队名")
    resolved_root = root.expanduser().resolve()
    path = (resolved_root / safe).resolve()
    try:
        path.relative_to(resolved_root)
    except ValueError as exc:
        raise TeamError("path_escape", "团队目录越过用户级 Team 根目录") from exc
    return path


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
