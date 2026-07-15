from __future__ import annotations

import re
from fnmatch import fnmatchcase
from typing import Literal


MatchOperator = Literal["exact", "glob", "regex"]


def match_value(actual: str, operator: MatchOperator, expected: str) -> bool:
    if operator == "exact":
        return actual == expected
    if operator == "glob":
        return fnmatchcase(actual, expected)
    return re.search(expected, actual) is not None


def match_exact_or_glob(actual: str, expected: str) -> bool:
    return actual == expected or fnmatchcase(actual, expected)
