from __future__ import annotations

from huicode.agent_events import AgentMode
from huicode.tools.registry import ToolRegistry

from .types import AgentDefinition
from .types import SubagentTask


GLOBAL_FORBIDDEN_TOOLS = frozenset({"Agent", "Skill"})


def resolve_subagent_tool_names(
    registry: ToolRegistry,
    parent_visible: tuple[str, ...] | list[str] | set[str],
    *,
    kind: str,
    definition: AgentDefinition | None,
    background: bool,
    background_allowed: tuple[str, ...],
    mode: AgentMode,
    read_only_names: frozenset[str] = frozenset({"Read", "Find", "Search", "Glob"}),
) -> frozenset[str]:
    visible, _ = registry.normalize_names(set(parent_visible))
    forbidden, _ = registry.normalize_names(set(GLOBAL_FORBIDDEN_TOOLS))
    visible.difference_update(forbidden)
    if kind == "defined" and definition is not None:
        allowed, _ = registry.normalize_names(set(definition.allowed_tools))
        denied, _ = registry.normalize_names(set(definition.denied_tools))
        visible.intersection_update(allowed)
        visible.difference_update(denied)
    if background:
        allowed, _ = registry.normalize_names(set(background_allowed))
        visible.intersection_update(allowed)
    if mode == "plan":
        read_only, _ = registry.normalize_names(set(read_only_names))
        visible.intersection_update(read_only)
    return frozenset(visible)


def filtered_registry(registry: ToolRegistry, names: frozenset[str]) -> ToolRegistry:
    return registry.clone(only=names)


class TaskAwareToolRegistry:
    """按任务前后台状态动态收窄工具，不复制或修改共享工具对象。"""

    def __init__(
        self,
        registry: ToolRegistry,
        task: SubagentTask,
        parent_visible: tuple[str, ...],
        *,
        kind: str,
        definition: AgentDefinition | None,
        background_allowed: tuple[str, ...],
        mode: AgentMode,
        read_only_names: frozenset[str],
    ) -> None:
        self.registry = registry
        self.task = task
        self.parent_visible = parent_visible
        self.kind = kind
        self.definition = definition
        self.background_allowed = background_allowed
        self.mode = mode
        self.read_only_names = read_only_names

    def _names(self) -> frozenset[str]:
        return resolve_subagent_tool_names(
            self.registry,
            self.parent_visible,
            kind=self.kind,
            definition=self.definition,
            background=self.task.background_event.is_set(),
            background_allowed=self.background_allowed,
            mode=self.mode,
            read_only_names=self.read_only_names,
        )

    def resolve_name(self, name: str) -> str | None:
        resolved = self.registry.resolve_name(name)
        return resolved if resolved in self._names() else None

    def get(self, name: str):  # noqa: ANN201
        resolved = self.resolve_name(name)
        return self.registry.get(resolved) if resolved is not None else None

    def list(self):  # noqa: ANN201
        names = self._names()
        return [tool for tool in self.registry.list() if tool.name in names]

    def system_tool_names(self) -> frozenset[str]:
        return self.registry.system_tool_names() & self._names()

    def ordinary_tool_names(self) -> frozenset[str]:
        return self.registry.ordinary_tool_names() & self._names()

    def normalize_names(self, names: set[str] | frozenset[str]) -> tuple[set[str], set[str]]:
        resolved: set[str] = set()
        missing: set[str] = set()
        for name in names:
            target = self.resolve_name(name)
            if target is None:
                missing.add(name)
            else:
                resolved.add(target)
        return resolved, missing

    def is_side_effect(self, name: str) -> bool:
        tool = self.get(name)
        return True if tool is None else bool(tool.side_effect)

    def to_specs(self, allowed_names=None, *, include_system=True):  # noqa: ANN001, ANN201
        current = set(self._names())
        if allowed_names is not None:
            requested, _ = self.registry.normalize_names(set(allowed_names))
            current.intersection_update(requested)
        del include_system
        return self.registry.to_specs(current, include_system=False)
