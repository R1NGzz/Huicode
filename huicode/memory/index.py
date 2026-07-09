from __future__ import annotations

from pathlib import Path

from huicode.config import MemoryConfig
from huicode.memory.notes import NoteStore
from huicode.memory.paths import project_index_path
from huicode.memory.scrub import scrub_secrets
from huicode.memory.types import MemoryIndexResult, MemoryNote


CATEGORY_TITLES = {
    "project_knowledge": "Project Knowledge",
    "preference": "User Preferences",
    "correction": "Corrections",
    "reference": "References",
}


class MemoryIndex:
    def __init__(self, workspace: Path, settings: MemoryConfig, store: NoteStore | None = None) -> None:
        self.workspace = workspace
        self.settings = settings
        self.store = store or NoteStore(workspace)
        self.path = project_index_path(workspace)

    def rebuild(self) -> MemoryIndexResult:
        notes = self.store.list_notes()
        text, clipped = self._render(notes)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")
        return MemoryIndexResult(
            path=self.path,
            lines=len(text.splitlines()),
            bytes=len(text.encode("utf-8")),
            note_count=len(notes),
            clipped=clipped,
        )

    def load_text(self) -> str:
        if not self.path.exists():
            self.rebuild()
        try:
            return scrub_secrets(self.path.read_text(encoding="utf-8"))
        except OSError:
            return ""

    def _render(self, notes: list[MemoryNote]) -> tuple[str, bool]:
        lines = ["# HuiCode Memory Index", ""]
        clipped = False
        grouped: dict[str, list[MemoryNote]] = {}
        for note in notes:
            grouped.setdefault(note.category, []).append(note)
        for category in ("project_knowledge", "preference", "correction", "reference"):
            category_notes = grouped.get(category, [])
            if not category_notes:
                continue
            lines.extend([f"## {CATEGORY_TITLES[category]}", ""])
            for note in category_notes:
                source = _source_hint(note, self.workspace)
                summary = _clip(scrub_secrets(note.summary or note.body), 180)
                title = _clip(scrub_secrets(note.title), 80)
                candidate = f"- [{note.note_id}] {title}: {summary} (source: {source})"
                trial = lines + [candidate, ""]
                if len(trial) > self.settings.index_max_lines or len("\n".join(trial).encode("utf-8")) > self.settings.index_max_bytes:
                    clipped = True
                    continue
                lines.append(candidate)
            lines.append("")
        if len(lines) == 2:
            lines.extend(["暂无长期记忆。", ""])
        text = "\n".join(lines).rstrip() + "\n"
        return text, clipped


def _source_hint(note: MemoryNote, workspace: Path) -> str:
    if note.path is None:
        return note.note_id
    try:
        return note.path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return f"~/.huicode/memory/notes/{note.path.name}"


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
