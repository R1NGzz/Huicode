from __future__ import annotations

from typing import Any, Mapping

from huicode.matching import match_value

from .types import HookCondition, HookPredicate


_MISSING = object()


def match_condition(condition: HookCondition | None, payload: Mapping[str, Any]) -> bool:
    if condition is None:
        return True
    matches = [_match_predicate(predicate, payload) for predicate in condition.predicates]
    return all(matches) if condition.mode == "all" else any(matches)


def read_field(payload: Mapping[str, Any], field: str) -> Any:
    current: Any = payload
    for part in field.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _match_predicate(predicate: HookPredicate, payload: Mapping[str, Any]) -> bool:
    actual = read_field(payload, predicate.field)
    if actual is _MISSING:
        return predicate.negate
    matched = match_value(_stringify(actual), predicate.operator, predicate.value)
    return not matched if predicate.negate else matched


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)
