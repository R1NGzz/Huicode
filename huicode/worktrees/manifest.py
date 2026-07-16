from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from .types import WorktreeError, WorktreeIdentity


MANIFEST_VERSION = 1
MANIFEST_RELATIVE_PATH = Path(".huicode") / "worktree.json"


def manifest_path(worktree: Path) -> Path:
    return worktree / MANIFEST_RELATIVE_PATH


def write_manifest(identity: WorktreeIdentity) -> None:
    path = manifest_path(identity.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    payload = {
        "version": MANIFEST_VERSION,
        "repository_id": identity.repository_id,
        "task_id": identity.task_id,
        "logical_name": identity.logical_name,
        "base_commit": identity.base_commit,
        "branch": identity.branch,
        "path": str(identity.path.resolve()),
        "created_at": identity.created_at,
        "terminal_status": identity.terminal_status,
        "retained_reason": identity.retained_reason,
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_manifest(worktree: Path) -> WorktreeIdentity:
    path = manifest_path(worktree)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorktreeError("manifest_missing", "已有目录缺少 HuiCode Worktree 管理清单") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorktreeError("manifest_invalid", f"Worktree 管理清单无法读取: {exc}") from exc
    required = {
        "version": int,
        "repository_id": str,
        "task_id": str,
        "logical_name": str,
        "base_commit": str,
        "branch": str,
        "path": str,
        "created_at": (int, float),
    }
    if not isinstance(raw, dict) or any(
        key not in raw or not _matches_type(raw[key], expected)
        for key, expected in required.items()
    ):
        raise WorktreeError("manifest_invalid", "Worktree 管理清单字段缺失或类型错误")
    if raw["version"] != MANIFEST_VERSION:
        raise WorktreeError("manifest_version", "Worktree 管理清单版本不受支持")
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", raw["base_commit"]):
        raise WorktreeError("manifest_invalid", "Worktree 管理清单的基线提交格式无效")
    if not math.isfinite(float(raw["created_at"])):
        raise WorktreeError("manifest_invalid", "Worktree 管理清单的创建时间无效")
    terminal_status = raw.get("terminal_status", "")
    retained_reason = raw.get("retained_reason", "")
    if terminal_status not in {"", "completed", "failed", "cancelled"}:
        raise WorktreeError("manifest_invalid", "Worktree 管理清单的任务终态无效")
    if not isinstance(retained_reason, str):
        raise WorktreeError("manifest_invalid", "Worktree 管理清单的保留原因格式无效")
    return WorktreeIdentity(
        repository_id=raw["repository_id"],
        task_id=raw["task_id"],
        logical_name=raw["logical_name"],
        base_commit=raw["base_commit"],
        branch=raw["branch"],
        path=Path(raw["path"]).resolve(),
        created_at=float(raw["created_at"]),
        terminal_status=terminal_status,
        retained_reason=retained_reason,
    )


def require_matching_manifest(expected: WorktreeIdentity) -> WorktreeIdentity:
    actual = read_manifest(expected.path)
    fields = (
        "repository_id",
        "task_id",
        "logical_name",
        "base_commit",
        "branch",
        "path",
    )
    mismatched = [name for name in fields if getattr(actual, name) != getattr(expected, name)]
    if mismatched:
        raise WorktreeError(
            "manifest_mismatch",
            "Worktree 管理清单不匹配: " + ", ".join(mismatched),
        )
    return actual


def _matches_type(value, expected) -> bool:  # noqa: ANN001, ANN202
    if isinstance(value, bool) and (expected is int or int in (expected if isinstance(expected, tuple) else ())):
        return False
    return isinstance(value, expected)
