"""Deterministic, bounded similarity primitives for registry names.

This module deliberately knows nothing about Home Assistant entities.  It is
shared by direct resolution and the confirm-before-action ASR correction path
so both use identical distance limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class NameSimilarity:
    distance: int
    ratio: float

    @property
    def accepted(self) -> bool:
        limit = 1 if self.longest_length <= 6 else 2
        return self.distance <= limit and self.ratio >= 0.72

    longest_length: int = 0


def edit_distance(left: str, right: str) -> int:
    """Return deterministic Levenshtein distance."""
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


def bounded_name_similarity(left: str, right: str) -> NameSimilarity:
    """Score two normalized name strings under the shared conservative gate."""
    return NameSimilarity(
        distance=edit_distance(left, right),
        ratio=SequenceMatcher(None, left, right).ratio(),
        longest_length=max(len(left), len(right)),
    )
