"""Dependency-free, token-based temporal meaning extraction."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Sequence

from .german_structure import StructuralToken


class TemporalKind(Enum):
    NOW = auto()
    RELATIVE_DELAY = auto()
    DURATION = auto()
    ABSOLUTE_TIME = auto()
    DATE = auto()
    WEEKDAY = auto()
    BEFORE = auto()
    AFTER = auto()
    UNTIL = auto()
    WHILE = auto()
    SINCE = auto()
    SUN_EVENT = auto()


@dataclass(frozen=True)
class TemporalExpression:
    kind: TemporalKind
    token_start: int
    token_end: int
    value: str
    seconds: int | None = None


_NUMBERS = {
    "ein": 1, "eine": 1, "einer": 1, "zwei": 2, "drei": 3,
    "vier": 4, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8,
    "neun": 9, "zehn": 10, "fuenfzehn": 15, "zwanzig": 20,
    "dreissig": 30, "sechzig": 60,
}
_UNIT_SECONDS = {
    "sekunde": 1, "sekunden": 1, "minute": 60, "minuten": 60,
    "stunde": 3600, "stunden": 3600, "tag": 86400, "tage": 86400,
}
_RELATIONS = {
    "vor": TemporalKind.BEFORE,
    "bevor": TemporalKind.BEFORE,
    "nach": TemporalKind.AFTER,
    "nachdem": TemporalKind.AFTER,
    "bis": TemporalKind.UNTIL,
    "waehrend": TemporalKind.WHILE,
    "solange": TemporalKind.WHILE,
    "seit": TemporalKind.SINCE,
}
_WEEKDAYS = frozenset({
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag",
    "samstag", "sonntag",
})
_DATES = frozenset({"heute", "morgen", "uebermorgen", "gestern"})
_SUN_EVENTS = frozenset({"sonnenaufgang", "sonnenuntergang"})


def _number(word: str) -> int | None:
    if word.isdigit():
        return int(word)
    return _NUMBERS.get(word)


def analyse_temporal_semantics(
    tokens: Sequence[StructuralToken],
) -> tuple[TemporalExpression, ...]:
    """Extract composable time relations without interpreting execution support."""
    words = tuple(token.canonical for token in tokens)
    found: list[TemporalExpression] = []
    for index, word in enumerate(words):
        if word in {"jetzt", "sofort"}:
            found.append(TemporalExpression(TemporalKind.NOW, index, index + 1, word))
        if word in _DATES:
            found.append(TemporalExpression(TemporalKind.DATE, index, index + 1, word))
        if word in _WEEKDAYS:
            found.append(TemporalExpression(TemporalKind.WEEKDAY, index, index + 1, word))
        if word in _SUN_EVENTS:
            found.append(TemporalExpression(TemporalKind.SUN_EVENT, index, index + 1, word))
        relation = _RELATIONS.get(word)
        if relation is not None:
            found.append(TemporalExpression(relation, index, index + 1, word))
        if index + 2 < len(words):
            amount = _number(words[index + 1])
            multiplier = _UNIT_SECONDS.get(words[index + 2])
            if amount is not None and multiplier is not None:
                kind = {
                    "in": TemporalKind.RELATIVE_DELAY,
                    "fuer": TemporalKind.DURATION,
                    "seit": TemporalKind.SINCE,
                }.get(word)
                if kind is not None:
                    found.append(TemporalExpression(
                        kind, index, index + 3,
                        " ".join(words[index:index + 3]),
                        amount * multiplier,
                    ))
        if word == "um" and index + 2 < len(words):
            hour = _number(words[index + 1])
            if hour is not None and words[index + 2] == "uhr" and 0 <= hour <= 23:
                found.append(TemporalExpression(
                    TemporalKind.ABSOLUTE_TIME, index, index + 3, f"{hour:02d}:00"
                ))
    # Prefer the richer duration/since span over its one-token relation.
    return tuple(
        item for item in found
        if not any(
            other is not item
            and other.token_start == item.token_start
            and other.token_end > item.token_end
            for other in found
        )
    )
