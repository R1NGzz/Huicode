from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_workspace_path(workspace: Path, path: str | Path) -> Path:
    root = workspace.resolve()
    raw = Path(path)
    target = raw if raw.is_absolute() else root / raw
    resolved = target.resolve(strict=False)
    if not is_within_workspace(root, resolved):
        raise ValueError(f"路径超出工作目录: {path}")
    return resolved


def is_within_workspace(workspace: Path, target: Path) -> bool:
    root = workspace.resolve()
    resolved = target.resolve(strict=False)
    return resolved == root or root in resolved.parents


def extract_tool_paths(tool_name: str, args: dict[str, Any]) -> list[str]:
    name = "Find" if tool_name == "Glob" else tool_name
    paths: list[str] = []
    if name in {"Read", "Write", "Edit"}:
        value = args.get("path")
        if isinstance(value, str) and value:
            paths.append(value)
    elif name == "Find":
        value = args.get("pattern")
        if isinstance(value, str) and _path_like(value):
            paths.append(value)
    elif name == "Search":
        value = args.get("glob")
        if isinstance(value, str) and _path_like(value):
            paths.append(value)
    return paths


def _path_like(value: str) -> bool:
    return (
        value.startswith("..")
        or value.startswith("/")
        or value.startswith("\\")
        or ":" in value
        or "/" in value
        or "\\" in value
    )

