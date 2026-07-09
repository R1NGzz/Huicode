from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContextState:
    last_input_tokens: int | None = None
    last_estimated_request_tokens: int | None = None
    last_estimated_chars: int | None = None
    summary_failure_count: int = 0
    summary_fuse_open: bool = False
    summary_count: int = 0
    last_summary_tokens_freed: int = 0
    last_compaction_reason: str = ""

    def reset(self) -> None:
        self.last_input_tokens = None
        self.last_estimated_request_tokens = None
        self.last_estimated_chars = None
        self.summary_failure_count = 0
        self.summary_fuse_open = False
        self.summary_count = 0
        self.last_summary_tokens_freed = 0
        self.last_compaction_reason = ""

