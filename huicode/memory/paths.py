from __future__ import annotations

import os
from pathlib import Path


def huicode_home() -> Path:
    configured = os.environ.get("HUICODE_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".huicode").resolve()


def project_data_dir(workspace: Path) -> Path:
    return (workspace / ".huicode").resolve()


def project_memory_dir(workspace: Path) -> Path:
    return project_data_dir(workspace) / "memory"


def user_memory_dir() -> Path:
    return huicode_home() / "memory"


def project_notes_dir(workspace: Path) -> Path:
    return project_memory_dir(workspace) / "notes"


def user_notes_dir() -> Path:
    return user_memory_dir() / "notes"


def project_index_path(workspace: Path) -> Path:
    return project_memory_dir(workspace) / "index.md"


def user_index_path() -> Path:
    return user_memory_dir() / "index.md"


def session_dir(workspace: Path) -> Path:
    return project_data_dir(workspace) / "sessions"
