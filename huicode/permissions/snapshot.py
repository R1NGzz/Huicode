from __future__ import annotations

from pathlib import Path

from .base import PermissionContext, PermissionMode, PermissionRule


_STRICTNESS: dict[PermissionMode, int] = {"permissive": 0, "default": 1, "strict": 2}


def stricter_mode(left: PermissionMode, right: PermissionMode) -> PermissionMode:
    return left if _STRICTNESS[left] >= _STRICTNESS[right] else right


def clone_permission_context(
    parent: PermissionContext | None,
    workspace: Path,
    *,
    requested_mode: PermissionMode | None = None,
) -> PermissionContext:
    if parent is None:
        mode: PermissionMode = requested_mode or "default"
        rules: list[PermissionRule] = []
        session_rules: list[PermissionRule] = []
    else:
        mode = parent.mode
        if requested_mode is not None:
            mode = stricter_mode(mode, requested_mode)
        rules = list(parent.rules)
        session_rules = list(parent.session_rules)
    return PermissionContext(
        workspace=workspace.resolve(),
        mode=mode,
        rules=rules,
        session_rules=session_rules,
        confirmer=None,
        persistent_path=None,
    )
