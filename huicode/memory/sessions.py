from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

from huicode.config import MemoryConfig
from huicode.memory.codec import message_from_json, message_to_json
from huicode.memory.paths import session_dir
from huicode.memory.recovery import recover_safe_messages
from huicode.memory.types import RecoveredSession, SessionSummary
from huicode.providers.base import ConversationMessage


class SessionRecorder:
    def __init__(self, session_id: str, path: Path) -> None:
        self.session_id = session_id
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO = self.path.open("a", encoding="utf-8")

    def append_message(self, message: ConversationMessage) -> None:
        self._write(
            {
                "type": "message",
                "session_id": self.session_id,
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                "message": message_to_json(message),
            }
        )

    def append_event(self, event: str, payload: dict[str, object] | None = None) -> None:
        self._write(
            {
                "type": "event",
                "event": event,
                "session_id": self.session_id,
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                "payload": payload or {},
            }
        )

    def close(self) -> None:
        self._file.close()

    def _write(self, record: dict[str, object]) -> None:
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()


class SessionStore:
    def __init__(self, workspace: Path, settings: MemoryConfig) -> None:
        self.workspace = workspace
        self.settings = settings
        self.root = session_dir(workspace)

    def new_session_id(self) -> str:
        return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"

    def open(self, session_id: str | None = None) -> SessionRecorder:
        session_id = session_id or self.new_session_id()
        return SessionRecorder(session_id, self.root / f"{session_id}.jsonl")

    def list_sessions(self) -> list[SessionSummary]:
        if not self.root.exists():
            return []
        summaries = [self._scan_summary(path) for path in self.root.glob("*.jsonl")]
        return sorted(summaries, key=lambda item: item.updated_at, reverse=True)

    def recover(self, session_id: str, now: datetime | None = None) -> RecoveredSession:
        now = now or datetime.now().astimezone()
        path = self.root / f"{session_id}.jsonl"
        messages: list[ConversationMessage] = []
        warnings: list[str] = []
        skipped = 0
        last_ts: datetime | None = None
        if not path.exists():
            return RecoveredSession(session_id, [], (f"会话不存在: {session_id}",), skipped_bad_lines=0)
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get("type") != "message":
                    continue
                messages.append(message_from_json(dict(record.get("message") or {})))
                parsed_ts = _parse_datetime(str(record.get("ts") or ""))
                if parsed_ts:
                    last_ts = parsed_ts
            except Exception as exc:
                skipped += 1
                warnings.append(f"第 {line_no} 行损坏，已跳过: {exc}")
        safe_messages, truncated, reason = recover_safe_messages(messages)
        if truncated:
            warnings.append(reason)
        time_gap_inserted = False
        if last_ts is not None and now - last_ts > timedelta(hours=self.settings.stale_session_notice_hours):
            safe_messages.append(_time_gap_message(last_ts, now))
            time_gap_inserted = True
        return RecoveredSession(
            session_id=session_id,
            messages=safe_messages,
            warnings=tuple(warnings),
            truncated=truncated,
            skipped_bad_lines=skipped,
            time_gap_inserted=time_gap_inserted,
        )

    def cleanup_expired(self, active_session_id: str, now: datetime | None = None) -> int:
        now = now or datetime.now().astimezone()
        if not self.root.exists():
            return 0
        removed = 0
        cutoff = now - timedelta(days=self.settings.session_retention_days)
        for path in self.root.glob("*.jsonl"):
            session_id = path.stem
            if session_id == active_session_id:
                continue
            summary = self._scan_summary(path)
            updated = _parse_datetime(summary.updated_at) if summary.updated_at else None
            if updated is None:
                updated = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
            if updated < cutoff:
                path.unlink()
                removed += 1
        return removed

    def _scan_summary(self, path: Path) -> SessionSummary:
        message_count = 0
        title = ""
        updated_at = ""
        warnings: list[str] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return SessionSummary(path.stem, path, "", 0, "", (f"读取失败: {exc}",))
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get("type") != "message":
                    continue
                message = message_from_json(dict(record.get("message") or {}))
                message_count += 1
                if not title and message.role == "user":
                    title = message.content.strip().replace("\n", " ")[:40]
                if record.get("ts"):
                    updated_at = str(record.get("ts"))
            except Exception as exc:
                warnings.append(f"第 {line_no} 行损坏: {exc}")
        return SessionSummary(path.stem, path, title or "(无标题)", message_count, updated_at, tuple(warnings))


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _time_gap_message(last_ts: datetime, now: datetime) -> ConversationMessage:
    return ConversationMessage(
        role="user",
        content=(
            '<huicode_context type="session_time_gap" scope="restored_session">\n'
            f"本会话从 {last_ts.isoformat(timespec='seconds')} 恢复，当前时间是 {now.isoformat(timespec='seconds')}。\n"
            "请注意期间项目文件和外部状态可能已经变化，需要事实细节时重新读取或验证。\n"
            "</huicode_context>"
        ),
    )
