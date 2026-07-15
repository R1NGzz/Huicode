from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .events import sanitize_payload


class HookLogger:
    def __init__(self, workspace: Path, max_record_bytes: int = 16 * 1024) -> None:
        self.path = workspace / ".huicode" / "logs" / "hooks.jsonl"
        self.max_record_bytes = max_record_bytes
        self.write_failures = 0
        self._lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        try:
            safe = sanitize_payload(record, max_string=2048, max_items=40)
            encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) > self.max_record_bytes:
                safe = {
                    "timestamp": safe.get("timestamp", ""),
                    "rule_id": safe.get("rule_id", ""),
                    "event": safe.get("event", ""),
                    "action": safe.get("action", ""),
                    "status": safe.get("status", "failed"),
                    "summary": "日志记录超过上限，详细内容已截断",
                }
                encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("ab") as stream:
                    stream.write(encoded + b"\n")
        except Exception:  # noqa: BLE001 - Hook 日志失败不能击穿主流程
            with self._lock:
                self.write_failures += 1
