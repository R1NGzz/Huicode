from __future__ import annotations

from pathlib import Path

from huicode.providers.base import ToolSpec

from .base import Tool
from .files import EditFileTool, ReadFileTool, WriteFileTool
from .search import FindFilesTool, SearchCodeTool
from .shell import RunCommandTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._aliases: dict[str, str] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def alias(self, alias_name: str, target_name: str) -> None:
        self._aliases[alias_name] = target_name

    def resolve_name(self, name: str) -> str | None:
        if name in self._tools:
            return name
        target_name = self._aliases.get(name)
        if target_name in self._tools:
            return target_name
        return None

    def get(self, name: str) -> Tool | None:
        resolved_name = self.resolve_name(name)
        return self._tools.get(resolved_name) if resolved_name else None

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def is_side_effect(self, name: str) -> bool:
        tool = self.get(name)
        return True if tool is None else bool(tool.side_effect)

    def to_specs(self, allowed_names: set[str] | frozenset[str] | None = None) -> list[ToolSpec]:
        if allowed_names is None:
            tools = self.list()
        else:
            resolved_names = {
                resolved_name
                for name in allowed_names
                if (resolved_name := self.resolve_name(name)) is not None
            }
            tools = [tool for tool in self.list() if tool.name in resolved_names]
        return [ToolSpec(name=tool.name, description=tool.description, parameters=tool.parameters) for tool in tools]


def create_default_registry(workspace: str | Path) -> ToolRegistry:
    _ = Path(workspace)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(FindFilesTool())
    registry.register(SearchCodeTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(RunCommandTool())
    registry.alias("Glob", "Find")
    return registry
