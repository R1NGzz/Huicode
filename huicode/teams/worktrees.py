from __future__ import annotations

import hashlib
from dataclasses import dataclass

from huicode.worktrees import WorktreeHandle, WorktreeManager

from .naming import validate_name


@dataclass(frozen=True)
class TeamWorktree:
    handle: WorktreeHandle

    @property
    def path(self):  # noqa: ANN201
        return self.handle.path

    @property
    def branch(self) -> str:
        return self.handle.branch


class TeamWorktreeService:
    def __init__(self, manager: WorktreeManager) -> None:
        self.manager = manager

    def prepare_member(self, team_id: str, member_id: str, member_name: str) -> TeamWorktree:
        safe = validate_name(member_name, "成员名")
        task_id = _task_id(f"member:{team_id}:{member_id}")
        handle = self.manager.prepare(task_id, f"teams/{safe}")
        self.manager.enter(handle)
        return TeamWorktree(handle)

    def prepare_integration(self, team_id: str, attempt_id: str) -> TeamWorktree:
        handle = self.manager.prepare(_task_id(f"integration:{team_id}:{attempt_id}"), f"teams/integration/{team_id[:20]}")
        self.manager.enter(handle)
        return TeamWorktree(handle)

    def close(self, worktree: TeamWorktree) -> None:
        self.manager.exit(worktree.handle)

    def delete(self, worktree: TeamWorktree):  # noqa: ANN201
        self.manager.exit(worktree.handle)
        return self.manager.remove(worktree.handle)


def _task_id(value: str) -> str:
    return "task-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
