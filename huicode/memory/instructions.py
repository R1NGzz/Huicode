from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from huicode.config import MemoryConfig
from huicode.memory.paths import huicode_home
from huicode.memory.scrub import scrub_secrets
from huicode.memory.types import InstructionLoadResult


Scope = Literal["project", "user"]


@dataclass(frozen=True)
class InstructionSource:
    path: Path
    scope: Scope
    priority: int
    boundary: Path


class InstructionLoader:
    def __init__(self, workspace: Path, settings: MemoryConfig) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings
        self.home = huicode_home()

    def load(self) -> InstructionLoadResult:
        loaded: list[str] = []
        loaded_paths: list[str] = []
        warnings: list[str] = []
        visited: set[Path] = set()
        for source in self._sources():
            if not source.path.exists():
                continue
            text = self._read_source(source, 0, visited, warnings)
            if not text.strip():
                continue
            loaded.append(f"<!-- source: {source.path} -->\n{text.strip()}")
            loaded_paths.append(str(source.path))
        if not loaded:
            return InstructionLoadResult("", tuple(loaded_paths), tuple(warnings))
        body = "\n\n".join(loaded)
        return InstructionLoadResult(
            text=(
                '<huicode_context type="project_instructions" scope="memory">\n'
                f"{scrub_secrets(body)}\n"
                "</huicode_context>"
            ),
            loaded_paths=tuple(loaded_paths),
            warnings=tuple(warnings),
        )

    def _sources(self) -> list[InstructionSource]:
        project_boundary = self.workspace
        home_boundary = self.home
        return [
            InstructionSource(self.workspace / ".huicode" / "instructions.md", "project", 100, project_boundary),
            InstructionSource(self.workspace / ".mewcode" / "instructions.md", "project", 90, project_boundary),
            InstructionSource(self.workspace / "HUICODE.md", "project", 80, project_boundary),
            InstructionSource(self.workspace / "MEWCODE.md", "project", 70, project_boundary),
            InstructionSource(self.home / "instructions.md", "user", 20, home_boundary),
            InstructionSource(Path.home() / ".mewcode" / "instructions.md", "user", 10, Path.home().resolve() / ".mewcode"),
        ]

    def _read_source(
        self,
        source: InstructionSource,
        depth: int,
        visited: set[Path],
        warnings: list[str],
    ) -> str:
        try:
            resolved = source.path.resolve()
        except OSError as exc:
            warnings.append(f"指令文件无法解析: {source.path}: {exc}")
            return ""
        if resolved in visited:
            warnings.append(f"指令 include 出现循环: {source.path}")
            return ""
        if depth > self.settings.instruction_include_depth:
            warnings.append(f"指令 include 超过最大深度: {source.path}")
            return ""
        if not _is_inside(resolved, source.boundary):
            warnings.append(f"指令 include 越过边界，已跳过: {source.path}")
            return ""
        if not resolved.exists():
            warnings.append(f"指令 include 文件不存在: {source.path}")
            return ""
        visited.add(resolved)
        try:
            lines = resolved.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            warnings.append(f"指令文件读取失败: {source.path}: {exc}")
            return ""
        output: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("@include "):
                include_name = stripped[len("@include ") :].strip().strip('"').strip("'")
                include_path = (resolved.parent / include_name).resolve()
                include_source = InstructionSource(include_path, source.scope, source.priority, source.boundary)
                output.append(self._read_source(include_source, depth + 1, visited, warnings))
            else:
                output.append(line)
        return "\n".join(part for part in output if part is not None)


def _is_inside(path: Path, boundary: Path) -> bool:
    try:
        path.relative_to(boundary.resolve())
        return True
    except ValueError:
        return False
