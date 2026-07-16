from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from .types import WorktreeError


_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9_-]{1,48}$")
MAX_LOGICAL_LENGTH = 120
MAX_DEPTH = 4


def validate_logical_name(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or len(value) > MAX_LOGICAL_LENGTH:
        raise WorktreeError("invalid_name", "Worktree 名称为空或超过 120 个字符")
    if "\\" in value or ":" in value or value.startswith("/"):
        raise WorktreeError("invalid_name", "Worktree 名称不能是绝对路径、盘符或包含反斜杠")
    if any(ord(char) < 32 for char in value):
        raise WorktreeError("invalid_name", "Worktree 名称不能包含控制字符")
    parts = PurePosixPath(value).parts
    raw_parts = value.split("/")
    if len(parts) > MAX_DEPTH or len(parts) != len(raw_parts):
        raise WorktreeError("invalid_name", "Worktree 名称嵌套过深或包含空路径段")
    if any(part in {"", ".", ".."} or not _SEGMENT_RE.fullmatch(part) for part in raw_parts):
        raise WorktreeError("invalid_name", "Worktree 名称包含非法路径段")
    return tuple(raw_parts)


def resolve_root(workspace: Path, configured: str) -> Path:
    raw = Path(configured)
    if raw.is_absolute() or raw.drive:
        raise WorktreeError("invalid_root", "Worktree 根目录必须是仓库内相对路径")
    root = (workspace.resolve() / raw).resolve()
    _ensure_inside(root, workspace.resolve(), "Worktree 根目录越过仓库边界")
    if root == workspace.resolve():
        raise WorktreeError("invalid_root", "Worktree 根目录不能等于仓库根目录")
    return root


def task_path(root: Path, logical_name: str, task_id: str) -> Path:
    parts = validate_logical_name(logical_name)
    if not re.fullmatch(r"task-[a-f0-9]{8}", task_id):
        raise WorktreeError("invalid_task_id", "Worktree 任务 ID 格式无效")
    path = (root / "tasks" / Path(*parts) / task_id).resolve()
    _ensure_inside(path, root.resolve(), "Worktree 任务路径越过专用根目录")
    return path


def branch_name(logical_name: str, task_id: str) -> str:
    parts = validate_logical_name(logical_name)
    return "huicode/worktree/" + "-".join(parts).lower() + f"-{task_id[5:]}"


def _ensure_inside(path: Path, boundary: Path, message: str) -> None:
    try:
        path.relative_to(boundary)
    except ValueError as exc:
        raise WorktreeError("path_escape", message) from exc
