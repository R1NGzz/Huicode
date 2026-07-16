from __future__ import annotations

import threading
import time
from pathlib import Path

from .manifest import MANIFEST_RELATIVE_PATH, read_manifest
from .types import WorktreeCleanupRecord, WorktreeError, WorktreeHandle


class WorktreeCleanupService:
    def __init__(self, manager) -> None:  # noqa: ANN001
        self.manager = manager
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.records: list[WorktreeCleanupRecord] = []

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="huicode-worktree-cleanup", daemon=True)
        self._thread.start()

    def scan_once(self) -> tuple[WorktreeCleanupRecord, ...]:
        records: list[WorktreeCleanupRecord] = []
        tasks = self.manager.root / "tasks"
        if not tasks.exists():
            return ()
        cutoff = time.time() - self.manager.config.stale_after_days * 86400
        backend = self.manager._backend()
        for manifest in tasks.rglob(str(MANIFEST_RELATIVE_PATH).replace("\\", "/")):
            worktree = manifest.parent.parent
            try:
                resolved = worktree.resolve()
                resolved.relative_to(self.manager.root.resolve())
                identity = read_manifest(resolved)
                if identity.path != resolved:
                    raise WorktreeError("manifest_mismatch", "清单路径与候选目录不匹配")
                if identity.repository_id != backend.repository_id:
                    raise WorktreeError("repository_mismatch", "清单不属于当前仓库")
                if identity.terminal_status in {"failed", "cancelled"}:
                    records.append(
                        WorktreeCleanupRecord(
                            resolved,
                            "retained",
                            identity.retained_reason or f"任务状态为 {identity.terminal_status}",
                        )
                    )
                    continue
                if identity.created_at >= cutoff:
                    records.append(WorktreeCleanupRecord(resolved, "skipped", "尚未过期"))
                    continue
                disposition = self.manager.remove(WorktreeHandle(identity, recovered=True))
                records.append(WorktreeCleanupRecord(resolved, disposition.state, disposition.reason))
            except Exception as exc:  # noqa: BLE001
                records.append(WorktreeCleanupRecord(worktree, "error", str(exc)))
        self.records.extend(records)
        return tuple(records)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception as exc:  # noqa: BLE001
                self.records.append(WorktreeCleanupRecord(Path("."), "error", str(exc)))
            if self._stop.wait(self.manager.config.cleanup_interval_seconds):
                return
