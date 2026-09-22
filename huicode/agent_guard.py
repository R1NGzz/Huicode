from __future__ import annotations

import re
from pathlib import PurePosixPath


_SOURCE_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".go",
        ".h",
        ".hpp",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".scala",
        ".sh",
        ".swift",
        ".ts",
        ".tsx",
    }
)
_TEST_DIRECTORY_NAMES = frozenset({"test", "tests", "__tests__", "spec", "specs"})
_INTERNAL_DIRECTORY_NAMES = frozenset({".claude", ".git", ".huicode"})
_TEST_FILE_RE = re.compile(
    r"(?:^test(?:[._-]|$)|(?:^|[._-])test$|(?:^|[._-])spec$|^conftest$)",
    re.IGNORECASE,
)

_TEST_COMMAND_PATTERNS = (
    re.compile(r"\bpytest\b", re.IGNORECASE),
    re.compile(r"\b(?:unittest|tox|nox)\b", re.IGNORECASE),
    re.compile(r"\b(?:go\s+test|cargo\s+test|npm\s+test|pnpm\s+test|yarn\s+test)\b", re.IGNORECASE),
    re.compile(r"\b(?:mvn\s+test|gradle\s+test|phpunit|rspec)\b", re.IGNORECASE),
)
_CHECK_COMMAND_PATTERNS = (
    re.compile(r"\bpython(?:\d+(?:\.\d+)?)?\s+-m\s+(?:py_compile|compileall)\b", re.IGNORECASE),
    re.compile(r"\b(?:node\s+--check|tsc\s+--noEmit|cargo\s+check|go\s+vet)\b", re.IGNORECASE),
)
_IMPORT_CHECK_RE = re.compile(r"\bpython(?:\d+(?:\.\d+)?)?\s+-c\b.*\bimport\b", re.IGNORECASE | re.DOTALL)
_SMOKE_CHECK_RE = re.compile(r"\b(?:smoke|repro(?:duction)?|validate|verification|verify)\b", re.IGNORECASE)


def normalized_path(path: object) -> str:
    """Normalize a model-provided workspace path for policy matching."""
    text = str(path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def is_test_path(path: object) -> bool:
    normalized = normalized_path(path)
    if not normalized:
        return False
    parts = [part for part in normalized.split("/") if part]
    if any(part.lower() in _TEST_DIRECTORY_NAMES for part in parts[:-1]):
        return True
    filename = parts[-1].lower()
    if filename in {"test", "conftest.py", "conftest.go"}:
        return True
    stem = PurePosixPath(filename).stem
    return bool(_TEST_FILE_RE.search(stem))


def is_internal_path(path: object) -> bool:
    normalized = normalized_path(path)
    return any(part.lower() in _INTERNAL_DIRECTORY_NAMES for part in normalized.split("/"))


def is_production_source_path(path: object) -> bool:
    normalized = normalized_path(path)
    if not normalized or is_internal_path(normalized) or is_test_path(normalized):
        return False
    filename = normalized.rsplit("/", 1)[-1].lower()
    if filename in {"task.txt", ".huicode-permissions.local.yaml"}:
        return False
    return PurePosixPath(filename).suffix.lower() in _SOURCE_SUFFIXES


def is_verification_command(command: object) -> bool:
    """Return whether a shell command is a recognizable code verification."""
    text = str(command or "").strip()
    if not text:
        return False
    if any(pattern.search(text) for pattern in _TEST_COMMAND_PATTERNS):
        return True
    if any(pattern.search(text) for pattern in _CHECK_COMMAND_PATTERNS):
        return True
    if _IMPORT_CHECK_RE.search(text):
        return True
    if _SMOKE_CHECK_RE.search(text) and not re.search(r"\bgit\s+check", text, re.IGNORECASE):
        return True
    return False


def edit_match_details(content: str, old_text: str, *, limit: int = 8) -> list[dict[str, object]]:
    """Return compact line/context locations for repeated Edit matches."""
    details: list[dict[str, object]] = []
    for index, match in enumerate(re.finditer(re.escape(old_text), content), start=1):
        if index > limit:
            break
        line_number = content.count("\n", 0, match.start()) + 1
        line_start = content.rfind("\n", 0, match.start()) + 1
        line_end = content.find("\n", match.end())
        if line_end == -1:
            line_end = len(content)
        line = content[line_start:line_end].strip()
        details.append({"match": index, "line": line_number, "context": line[:240]})
    return details
