from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import fields
from pathlib import Path
from typing import Any, TypeVar

from huicode.config import TeamConfig

from .locking import FileLock
from .naming import team_path, validate_name
from .types import PlanApproval, TeamError, TeamEvent, TeamMemberRecord, TeamRecord, record_dict


T = TypeVar("T")


class TeamPaths:
    def __init__(self, root: Path, team_name: str) -> None:
        self.root = team_path(root, team_name)
        self.team = self.root / "team.json"
        self.roster = self.root / "roster.json"
        self.tasks = self.root / "tasks.json"
        self.approvals = self.root / "approvals.json"
        self.events = self.root / "events.jsonl"
        self.integration = self.root / "integration.json"
        self.members = self.root / "members"
        self.mailboxes = self.root / "mailboxes"
        self.locks = self.root / "locks"

    def mailbox(self, member: str) -> Path:
        return self.mailboxes / f"{validate_name(member, '成员名')}.jsonl"

    def member_session(self, member: str) -> Path:
        return self.members / validate_name(member, "成员名") / "session.jsonl"


class TeamStore:
    def __init__(self, root: Path, team_name: str, config: TeamConfig) -> None:
        self.paths = TeamPaths(root, team_name)
        self.config = config

    def initialize(self, team: TeamRecord) -> None:
        if self.paths.root.exists():
            raise TeamError("team_exists", f"团队已存在: {team.name}")
        self.paths.root.mkdir(parents=True)
        self.paths.members.mkdir()
        self.paths.mailboxes.mkdir()
        self.paths.locks.mkdir()
        self.save_team(team)
        atomic_write_json(self.paths.roster, {"version": 1, "members": []})
        atomic_write_json(self.paths.tasks, {"version": 1, "tasks": []})
        atomic_write_json(self.paths.approvals, {"version": 1, "approvals": []})

    def lock(self, name: str) -> FileLock:
        return FileLock(
            self.paths.locks / f"{name}.lock",
            retries=self.config.mailbox_lock_retries,
            retry_ms=self.config.mailbox_lock_retry_ms,
            stale_seconds=self.config.mailbox_stale_lock_seconds,
        )

    def save_team(self, team: TeamRecord) -> None:
        atomic_write_json(self.paths.team, {"version": 1, "team": record_dict(team)})

    def load_team(self) -> TeamRecord:
        data = read_json(self.paths.team)
        return construct(TeamRecord, data.get("team"), "team")

    def load_members(self) -> tuple[TeamMemberRecord, ...]:
        data = read_json(self.paths.roster)
        return tuple(construct(TeamMemberRecord, item, "member") for item in data.get("members", []))

    def save_members(self, members: tuple[TeamMemberRecord, ...] | list[TeamMemberRecord]) -> None:
        atomic_write_json(self.paths.roster, {"version": 1, "members": [record_dict(item) for item in members]})

    def load_approvals(self) -> tuple[PlanApproval, ...]:
        data = read_json(self.paths.approvals)
        return tuple(construct(PlanApproval, item, "approval") for item in data.get("approvals", []))

    def save_approvals(self, approvals: tuple[PlanApproval, ...] | list[PlanApproval]) -> None:
        atomic_write_json(self.paths.approvals, {"version": 1, "approvals": [record_dict(item) for item in approvals]})

    def append_event(self, event: TeamEvent) -> None:
        append_jsonl(self.paths.events, record_dict(event))


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    for attempt in range(6):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 5:
                temp.unlink(missing_ok=True)
                raise
            time.sleep(0.02 * (attempt + 1))


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TeamError("invalid_store", f"团队状态文件无法读取: {path.name}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise TeamError("invalid_store", f"团队状态文件版本无效: {path.name}")
    return data


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(line)
        stream.flush()


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    if not path.exists():
        return [], ()
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("记录不是对象")
            records.append(item)
        except (json.JSONDecodeError, ValueError) as exc:
            warnings.append(f"第 {line_no} 行损坏，已跳过: {exc}")
    return records, tuple(warnings)


def construct(cls: type[T], raw: Any, label: str) -> T:
    if not isinstance(raw, dict):
        raise TeamError("invalid_store", f"{label} 记录必须是对象")
    names = {item.name for item in fields(cls)}
    try:
        values = {name: raw[name] for name in names if name in raw}
        for name in ("dependencies", "recipients", "member_branches", "merged_members"):
            if name in values:
                values[name] = tuple(values[name])
        return cls(**values)
    except (KeyError, TypeError, ValueError) as exc:
        raise TeamError("invalid_store", f"{label} 记录字段无效: {exc}") from exc
