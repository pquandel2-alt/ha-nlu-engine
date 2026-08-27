"""Bounded ASR-error correction that always asks before executing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .entities import EntitySnapshot, normalize_for_compare


@dataclass(frozen=True)
class PhoneticSuggestion:
    corrected_text: str
    entity: EntitySnapshot
    corrected_term: str


def _distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row, char_left in enumerate(left, 1):
        current = [row]
        for column, char_right in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (char_left != char_right),
            ))
        previous = current
    return previous[-1]


def phonetic_suggestions(
    text: str, entities: list[EntitySnapshot]
) -> tuple[PhoneticSuggestion, ...]:
    """Replace one likely misheard entity-name word, never command words."""
    words = list(re.finditer(r"[A-Za-zÄÖÜäöüß]{4,}", text))
    suggestions: dict[tuple[str, str], PhoneticSuggestion] = {}
    for entity in entities:
        candidate_words: set[str] = set()
        for name in (entity.friendly_name, *entity.aliases):
            candidate_words.update(
                word for word in normalize_for_compare(name).split() if len(word) >= 4
            )
        for match in words:
            spoken = normalize_for_compare(match.group())
            for candidate in candidate_words:
                if spoken == candidate:
                    continue
                distance = _distance(spoken, candidate)
                ratio = SequenceMatcher(None, spoken, candidate).ratio()
                limit = 1 if max(len(spoken), len(candidate)) <= 6 else 2
                if distance > limit or ratio < 0.72:
                    continue
                corrected = text[:match.start()] + candidate + text[match.end():]
                suggestions[(corrected.casefold(), entity.entity_id)] = PhoneticSuggestion(
                    corrected, entity, candidate
                )
    return tuple(suggestions.values())[:16]
