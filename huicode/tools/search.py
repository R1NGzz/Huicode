from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from .base import ToolContext, ToolResult, safe_join_workspace


def _is_probably_text(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:1024]
    except OSError:
        return False
    return b"\x00" not in chunk


def _should_skip_path(workspace: Path, path: Path) -> bool:
    try:
        parts = path.relative_to(workspace).parts
    except ValueError:
        return True
    if any(part in {".git", "__pycache__"} for part in parts):
        return True
    return len(parts) >= 2 and parts[0] == ".huicode" and parts[1] == "tool-results"


class FindFilesTool:
    name = "Find"
    description = "按文件名或相对路径模式查找当前工作目录内的文件。需要列目录、找文件或 glob 时优先使用本工具，不要先调用 Bash。"
    side_effect = False
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "文件名或相对路径 glob 模式，如 *.py 或 huicode/*.py"},
            "limit": {"type": "integer", "description": "最多返回数量"},
        },
        "required": ["pattern"],
    }

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return ToolResult.failure("invalid_request", "参数 pattern 必须是非空字符串")
        limit = min(int(args.get("limit", 50)), 200)
        try:
            safe_join_workspace(context.workspace, ".")
        except ValueError as exc:
            return ToolResult.failure("invalid_request", str(exc))

        matches: list[str] = []
        for path in context.workspace.rglob("*"):
            if not path.is_file():
                continue
            if _should_skip_path(context.workspace, path):
                continue
            rel = path.relative_to(context.workspace).as_posix()
            if fnmatch(rel, pattern) or fnmatch(path.name, pattern):
                matches.append(rel)
                if len(matches) >= limit:
                    break
        return ToolResult.success(
            {"pattern": pattern, "matches": matches, "count": len(matches)},
            f"ok, {len(matches)} files",
        )


class SearchCodeTool:
    name = "Search"
    description = "在当前工作目录内按文本模式搜索代码内容，返回文件、行号和片段。需要 grep、findstr、查引用或搜索文本时优先使用本工具，不要先调用 Bash。"
    side_effect = False
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "要搜索的文本模式"},
            "glob": {"type": "string", "description": "可选文件 glob，如 *.py"},
            "limit": {"type": "integer", "description": "最多返回匹配数量"},
        },
        "required": ["pattern"],
    }

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return ToolResult.failure("invalid_request", "参数 pattern 必须是非空字符串")
        glob = args.get("glob", "*")
        if not isinstance(glob, str) or not glob:
            return ToolResult.failure("invalid_request", "参数 glob 必须是字符串")
        limit = min(int(args.get("limit", 50)), 200)

        matches: list[dict[str, Any]] = []
        for path in context.workspace.rglob("*"):
            if not path.is_file():
                continue
            if _should_skip_path(context.workspace, path):
                continue
            rel = path.relative_to(context.workspace).as_posix()
            if not (fnmatch(rel, glob) or fnmatch(path.name, glob)):
                continue
            if not _is_probably_text(path):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(lines, start=1):
                if pattern in line:
                    matches.append({"path": rel, "line": line_no, "snippet": line.strip()[:240]})
                    if len(matches) >= limit:
                        return ToolResult.success(
                            {"pattern": pattern, "matches": matches, "count": len(matches)},
                            f"ok, {len(matches)} matches",
                        )
        return ToolResult.success(
            {"pattern": pattern, "matches": matches, "count": len(matches)},
            f"ok, {len(matches)} matches",
        )
