from __future__ import annotations

from typing import Any

from .base import ToolContext, ToolResult, safe_join_workspace


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"参数 {key} 必须是非空字符串")
    return value


def _require_text(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise ValueError(f"参数 {key} 必须是字符串")
    return value


class ReadFileTool:
    name = "Read"
    description = "读取当前工作目录内的 UTF-8 文本文件。"
    side_effect = False
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "要读取的相对文件路径"}},
        "required": ["path"],
    }

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            path_arg = _require_str(args, "path")
            path = safe_join_workspace(context.workspace, path_arg)
            if not path.is_file():
                return ToolResult.failure("not_found", f"文件不存在: {path_arg}", {"path": path_arg})
            content = path.read_text(encoding="utf-8")
            lines = content.count("\n") + (1 if content else 0)
            return ToolResult.success(
                {"path": path_arg, "content": content, "lines": lines, "chars": len(content)},
                f"ok, {lines} lines, {len(content)} chars",
            )
        except UnicodeDecodeError as exc:
            return ToolResult.failure("decode_error", "文件不是有效的 UTF-8 文本", {"error": str(exc)})
        except ValueError as exc:
            return ToolResult.failure("invalid_request", str(exc))
        except OSError as exc:
            return ToolResult.failure("io_error", f"读取文件失败: {exc}")


class WriteFileTool:
    name = "Write"
    description = "在当前工作目录内写入 UTF-8 文本文件，会创建父目录。"
    side_effect = True
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要写入的相对文件路径"},
            "content": {"type": "string", "description": "要写入的完整文件内容"},
        },
        "required": ["path", "content"],
    }

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            path_arg = _require_str(args, "path")
            content = _require_text(args, "content")
            path = safe_join_workspace(context.workspace, path_arg)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult.success(
                {"path": path_arg, "bytes": len(content.encode("utf-8")), "chars": len(content)},
                f"ok, wrote {len(content)} chars",
            )
        except ValueError as exc:
            return ToolResult.failure("invalid_request", str(exc))
        except OSError as exc:
            return ToolResult.failure("io_error", f"写入文件失败: {exc}")


class EditFileTool:
    name = "Edit"
    description = "在当前工作目录内按原文唯一匹配替换文本。"
    side_effect = True
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要修改的相对文件路径"},
            "old_text": {"type": "string", "description": "要替换的原文，必须唯一出现"},
            "new_text": {"type": "string", "description": "替换后的新文本"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            path_arg = _require_str(args, "path")
            old_text = _require_str(args, "old_text")
            new_text = _require_text(args, "new_text")
            path = safe_join_workspace(context.workspace, path_arg)
            if not path.is_file():
                return ToolResult.failure("not_found", f"文件不存在: {path_arg}", {"path": path_arg})
            content = path.read_text(encoding="utf-8")
            count = content.count(old_text)
            if count == 0:
                return ToolResult.failure(
                    "not_found",
                    "原文在文件中没有匹配，未修改文件",
                    {"path": path_arg, "old_text": old_text},
                )
            if count > 1:
                return ToolResult.failure(
                    "multiple_matches",
                    f"原文在文件中匹配 {count} 次，未修改文件",
                    {"path": path_arg, "matches": count},
                )
            updated = content.replace(old_text, new_text, 1)
            path.write_text(updated, encoding="utf-8")
            return ToolResult.success(
                {"path": path_arg, "replacements": 1, "chars": len(updated)},
                "ok, replaced 1 occurrence",
            )
        except UnicodeDecodeError as exc:
            return ToolResult.failure("decode_error", "文件不是有效的 UTF-8 文本", {"error": str(exc)})
        except ValueError as exc:
            return ToolResult.failure("invalid_request", str(exc))
        except OSError as exc:
            return ToolResult.failure("io_error", f"修改文件失败: {exc}")
