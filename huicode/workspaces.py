from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from huicode.config import MemoryConfig
from huicode.memory.index import MemoryIndex
from huicode.memory.instructions import InstructionLoader
from huicode.memory.notes import NoteStore
from huicode.memory.paths import project_index_path


@dataclass(frozen=True)
class WorkspaceContextData:
    instructions: str = ""
    memory_index: str = ""
    warnings: tuple[str, ...] = ()


class WorkspaceContextLoader:
    def __init__(self, settings: MemoryConfig) -> None:
        self.settings = settings
        self._cache: dict[tuple[str, tuple[tuple[str, int, int], ...]], WorkspaceContextData] = {}
        self._lock = threading.Lock()

    def load(self, workspace: Path) -> WorkspaceContextData:
        root = workspace.resolve()
        snapshot = self._snapshot(root)
        key = (str(root), snapshot)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        instructions = InstructionLoader(root, self.settings).load()
        index_path = project_index_path(root)
        memory_index = ""
        if index_path.exists():
            memory_index = MemoryIndex(root, self.settings, NoteStore(root)).load_text()
        data = WorkspaceContextData(instructions.text, memory_index, instructions.warnings)
        with self._lock:
            stale = [item for item in self._cache if item[0] == str(root) and item != key]
            for item in stale:
                self._cache.pop(item, None)
            self._cache[key] = data
        return data

    def clear(self, workspace: Path) -> None:
        root = str(workspace.resolve())
        with self._lock:
            for key in [item for item in self._cache if item[0] == root]:
                self._cache.pop(key, None)

    @staticmethod
    def _snapshot(root: Path) -> tuple[tuple[str, int, int], ...]:
        candidates = [
            root / ".huicode" / "instructions.md",
            root / ".mewcode" / "instructions.md",
            root / "HUICODE.md",
            root / "MEWCODE.md",
            project_index_path(root),
        ]
        result = []
        for path in candidates:
            if path.exists():
                stat = path.stat()
                result.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
        return tuple(result)
