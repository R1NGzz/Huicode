from __future__ import annotations

try:
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.document import Document
except ImportError:  # pragma: no cover - CLI 会回退 input()
    Completer = object  # type: ignore[assignment,misc]
    Completion = None
    Document = object  # type: ignore[assignment,misc]

from .registry import CommandRegistry


class SlashCommandCompleter(Completer):  # type: ignore[misc]
    def __init__(self, registry: CommandRegistry) -> None:
        self.registry = registry

    def get_completions(self, document: Document, complete_event):  # noqa: ANN001
        if Completion is None:
            return
        text = document.text_before_cursor
        if not text.startswith("/") or any(char.isspace() for char in text):
            return
        prefix = text[1:].lower()
        for name, spec in self.registry.completion_entries():
            if not name.startswith(prefix):
                continue
            meta = spec.description
            if spec.argument_hint:
                meta = f"{meta} {spec.argument_hint}"
            yield Completion(
                f"/{name}",
                start_position=-len(text),
                display=f"/{name}",
                display_meta=meta,
            )
