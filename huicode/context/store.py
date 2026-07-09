from __future__ import annotations

import json
import re
from pathlib import Path

from huicode.context.estimator import TokenEstimator
from huicode.context.types import SpillRecord
from huicode.providers.base import ToolCall
from huicode.tools.base import ToolResult


class ToolResultStore:
    def __init__(self, workspace: Path, estimator: TokenEstimator | None = None) -> None:
        self.workspace = workspace
        self.estimator = estimator or TokenEstimator()

    def spill(self, call: ToolCall, result: ToolResult, iteration: int, reason: str) -> SpillRecord:
        serialized = json.dumps(result.to_model_dict(), ensure_ascii=False, indent=2)
        relative_path = Path(".huicode") / "tool-results" / f"turn-{iteration:03d}-{_safe_filename(call.id)}.json"
        spill_path = self.workspace / relative_path
        spill_path.parent.mkdir(parents=True, exist_ok=True)
        spill_path.write_text(serialized, encoding="utf-8")
        preview = _preview_text(serialized)
        compact_chars = len(preview) + len(relative_path.as_posix())
        return SpillRecord(
            path=relative_path.as_posix(),
            original_chars=len(serialized),
            compact_chars=compact_chars,
            tokens_freed=max(0, self.estimator.estimate_text(serialized) - self.estimator.estimate_text(preview)),
            preview=preview,
            reason=reason,
        )


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return safe or "tool-result"


def _preview_text(text: str, limit: int = 400) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"

