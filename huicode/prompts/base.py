from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


PromptMode = Literal["chat", "plan", "do"]


@dataclass(frozen=True)
class PromptModule:
    name: str
    content: str
    stable: bool = True
    cacheable: bool = True


@dataclass(frozen=True)
class PromptInjectionPolicy:
    repeat_every: int = 4


@dataclass(frozen=True)
class CacheUsage:
    creation_input_tokens: int = 0
    read_input_tokens: int = 0
    cached_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        result: dict[str, int] = {}
        if self.creation_input_tokens:
            result["creation_input_tokens"] = self.creation_input_tokens
        if self.read_input_tokens:
            result["read_input_tokens"] = self.read_input_tokens
        if self.cached_tokens:
            result["cached_tokens"] = self.cached_tokens
        return result


@dataclass(frozen=True)
class PromptContext:
    workspace: Path
    platform: str
    shell: str
    now: str
    mode: PromptMode
    iteration: int
    max_iterations: int
    available_tools: tuple[str, ...] = ()
    read_only_tool_names: tuple[str, ...] = ()
    last_plan: str = ""
    custom_instructions: str = ""
    active_skills: tuple[str, ...] = ()
    long_term_memory: str = ""


@dataclass(frozen=True)
class PromptBundle:
    stable_modules: tuple[PromptModule, ...] = ()
    dynamic_modules: tuple[PromptModule, ...] = ()
    supplemental_modules: tuple[PromptModule, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def module_names(self) -> list[str]:
        modules = self.stable_modules + self.dynamic_modules + self.supplemental_modules
        return [module.name for module in modules]

    def stable_text(self) -> str:
        return render_prompt_modules(self.stable_modules)

    def dynamic_text(self) -> str:
        return render_prompt_modules(self.dynamic_modules)

    def supplemental_text(self) -> str:
        return render_prompt_modules(self.supplemental_modules)

    def system_texts(self) -> list[str]:
        return [
            text
            for text in [self.stable_text(), self.dynamic_text(), self.supplemental_text()]
            if text
        ]


def render_prompt_modules(modules: tuple[PromptModule, ...] | list[PromptModule]) -> str:
    return "\n\n".join(module.content.strip() for module in modules if module.content.strip())
