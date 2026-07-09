from __future__ import annotations

from datetime import datetime
from pathlib import Path

from huicode.memory.paths import project_notes_dir, user_notes_dir
from huicode.memory.scrub import scrub_secrets
from huicode.memory.types import MemoryCategory, MemoryNote, MemoryScope


VALID_CATEGORIES: set[str] = {"preference", "correction", "project_knowledge", "reference"}
VALID_SCOPES: set[str] = {"user", "project"}


class NoteStore:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def list_notes(self, scope: MemoryScope | None = None) -> list[MemoryNote]:
        notes: list[MemoryNote] = []
        scopes: tuple[MemoryScope, ...]
        scopes = (scope,) if scope else ("project", "user")
        for item_scope in scopes:
            root = self._notes_dir(item_scope)
            if not root.exists():
                continue
            for path in root.glob("*.md"):
                note = _read_note(path)
                if note is not None and note.scope == item_scope:
                    notes.append(note)
        return sorted(notes, key=lambda note: note.updated_at, reverse=True)

    def create_note(self, note: MemoryNote) -> Path:
        _validate_note(note)
        root = self._notes_dir(note.scope)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{note.note_id}.md"
        _write_note(path, note)
        return path

    def update_note(self, note_id: str, changes: dict[str, str]) -> Path | None:
        existing = next((note for note in self.list_notes() if note.note_id == note_id), None)
        if existing is None or existing.path is None:
            return None
        updated = MemoryNote(
            note_id=existing.note_id,
            scope=existing.scope,
            category=existing.category,
            title=changes.get("title", existing.title),
            summary=changes.get("summary", existing.summary),
            body=changes.get("body", existing.body),
            source_session=changes.get("source_session", existing.source_session),
            created_at=existing.created_at,
            updated_at=changes.get("updated_at", _now()),
            path=existing.path,
        )
        _write_note(existing.path, updated)
        return existing.path

    def delete_note(self, note_id: str) -> bool:
        for note in self.list_notes():
            if note.note_id == note_id and note.path is not None:
                note.path.unlink(missing_ok=True)
                return True
        return False

    def _notes_dir(self, scope: MemoryScope) -> Path:
        return project_notes_dir(self.workspace) if scope == "project" else user_notes_dir()


def _read_note(path: Path) -> MemoryNote | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = _split_frontmatter(text)
    try:
        return MemoryNote(
            note_id=meta["id"],
            scope=meta["scope"],  # type: ignore[arg-type]
            category=meta["category"],  # type: ignore[arg-type]
            title=meta.get("title", ""),
            summary=meta.get("summary", ""),
            body=body.strip(),
            source_session=meta.get("source_session", ""),
            created_at=meta.get("created_at", ""),
            updated_at=meta.get("updated_at", ""),
            path=path,
        )
    except KeyError:
        return None


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    raw = text[4:end].strip()
    body = text[end + 4 :]
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, body


def _write_note(path: Path, note: MemoryNote) -> None:
    _validate_note(note)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = scrub_secrets(note.summary)
    body = scrub_secrets(note.body)
    title = scrub_secrets(note.title)
    content = "\n".join(
        [
            "---",
            f"id: {note.note_id}",
            f"scope: {note.scope}",
            f"category: {note.category}",
            f"title: {title}",
            f"summary: {summary}",
            f"source_session: {note.source_session}",
            f"created_at: {note.created_at or _now()}",
            f"updated_at: {note.updated_at or _now()}",
            "---",
            "",
            body,
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _validate_note(note: MemoryNote) -> None:
    if note.scope not in VALID_SCOPES:
        raise ValueError(f"非法记忆 scope: {note.scope}")
    if note.category not in VALID_CATEGORIES:
        raise ValueError(f"非法记忆分类: {note.category}")
    if not note.note_id:
        raise ValueError("记忆 note_id 不能为空")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
