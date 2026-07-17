from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .naming import new_id
from .storage import TeamStore, atomic_write_json, construct, read_json
from .types import TeamError, TeamTaskRecord, record_dict


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class SharedTaskStore:
    def __init__(self, store: TeamStore) -> None:
        self.store = store

    def list(self) -> tuple[TeamTaskRecord, ...]:
        data = read_json(self.store.paths.tasks)
        return tuple(construct(TeamTaskRecord, item, "task") for item in data.get("tasks", []))

    def get(self, task_id: str) -> TeamTaskRecord:
        for task in self.list():
            if task.id == task_id:
                return task
        raise TeamError("unknown_task", f"未知团队任务: {task_id}")

    def create(self, title: str, description: str = "", dependencies: tuple[str, ...] = (), paths: tuple[str, ...] = ()) -> TeamTaskRecord:
        if not title.strip():
            raise TeamError("invalid_task", "任务标题不能为空")
        with self.store.lock("tasks"):
            tasks = list(self.list())
            self._validate_dependencies(tasks, "", dependencies)
            now = _now()
            status = "blocked" if dependencies else "pending"
            task = TeamTaskRecord(new_id("team-task"), title.strip(), description.strip(), status, None, tuple(dependencies), "", 1, now, now, tuple(paths))
            tasks.append(task)
            self._save(tasks)
            return task

    def update(self, task_id: str, *, expected_version: int, assignee: str | None = None, status: str | None = None, result_summary: str | None = None, dependencies: tuple[str, ...] | None = None) -> TeamTaskRecord:
        with self.store.lock("tasks"):
            tasks = list(self.list())
            index = next((i for i, item in enumerate(tasks) if item.id == task_id), -1)
            if index < 0:
                raise TeamError("unknown_task", f"未知团队任务: {task_id}")
            current = tasks[index]
            if current.version != expected_version:
                raise TeamError("task_conflict", "任务已被其他成员更新", {"current_version": current.version})
            deps = current.dependencies if dependencies is None else tuple(dependencies)
            self._validate_dependencies(tasks, task_id, deps)
            next_status = current.status if status is None else status
            if next_status not in {"pending", "blocked", "in_progress", "completed", "failed"}:
                raise TeamError("invalid_task_status", f"非法任务状态: {next_status}")
            if next_status == "in_progress" and not self._dependencies_complete(tasks, deps):
                raise TeamError("task_blocked", "任务依赖尚未完成")
            updated = replace(current, assignee=assignee if assignee is not None else current.assignee, status=next_status, result_summary=current.result_summary if result_summary is None else result_summary, dependencies=deps, version=current.version + 1, updated_at=_now())
            tasks[index] = updated
            tasks = self._refresh_blocked(tasks)
            self._save(tasks)
            return next(item for item in tasks if item.id == task_id)

    def claim(self, task_id: str, member: str, expected_version: int) -> TeamTaskRecord:
        return self.update(task_id, expected_version=expected_version, assignee=member, status="in_progress")

    def assign(self, task_id: str, member: str) -> TeamTaskRecord:
        current = self.get(task_id)
        if current.status not in {"pending", "blocked"}:
            raise TeamError("task_not_assignable", f"任务当前状态不能分配: {current.status}")
        return self.update(task_id, expected_version=current.version, assignee=member)

    def delete(self, task_id: str, expected_version: int) -> None:
        with self.store.lock("tasks"):
            tasks = list(self.list())
            target = next((item for item in tasks if item.id == task_id), None)
            if target is None:
                raise TeamError("unknown_task", f"未知团队任务: {task_id}")
            if target.version != expected_version:
                raise TeamError("task_conflict", "任务已被其他成员更新")
            if target.status == "in_progress" or any(task_id in item.dependencies for item in tasks):
                raise TeamError("task_protected", "执行中或被依赖的任务不能删除")
            self._save([item for item in tasks if item.id != task_id])

    def _save(self, tasks: list[TeamTaskRecord]) -> None:
        atomic_write_json(self.store.paths.tasks, {"version": 1, "tasks": [record_dict(item) for item in tasks]})

    def _validate_dependencies(self, tasks: list[TeamTaskRecord], task_id: str, dependencies: tuple[str, ...]) -> None:
        ids = {item.id for item in tasks}
        if task_id and task_id in dependencies:
            raise TeamError("invalid_dependency", "任务不能依赖自身")
        missing = [item for item in dependencies if item not in ids]
        if missing:
            raise TeamError("invalid_dependency", f"依赖任务不存在: {', '.join(missing)}")
        graph = {item.id: item.dependencies for item in tasks}
        if task_id:
            graph[task_id] = dependencies
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(node: str) -> None:
            if node in visiting:
                raise TeamError("dependency_cycle", "任务依赖形成循环")
            if node in visited:
                return
            visiting.add(node)
            for child in graph.get(node, ()):
                visit(child)
            visiting.remove(node)
            visited.add(node)
        for node in graph:
            visit(node)

    @staticmethod
    def _dependencies_complete(tasks: list[TeamTaskRecord], dependencies: tuple[str, ...]) -> bool:
        statuses = {item.id: item.status for item in tasks}
        return all(statuses.get(item) == "completed" for item in dependencies)

    def _refresh_blocked(self, tasks: list[TeamTaskRecord]) -> list[TeamTaskRecord]:
        result = []
        for task in tasks:
            if task.status in {"pending", "blocked"}:
                status = "pending" if self._dependencies_complete(tasks, task.dependencies) else "blocked"
                if status != task.status:
                    task = replace(task, status=status, version=task.version + 1, updated_at=_now())
            result.append(task)
        return result
