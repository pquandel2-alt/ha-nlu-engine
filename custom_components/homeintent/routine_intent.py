"""Closed natural-language meanings for explicit routine feedback."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .entities import normalize_for_compare
from .nlu.language_frontend import LanguageDocument
from .situation import RoutineFeedback


@dataclass(frozen=True)
class RoutineFeedbackIntent:
    feedback: RoutineFeedback


_REFERENCE = r"(?:das|dies|dieser\s+hinweis|diese\s+(?:routine|meldung))"
_PATTERNS: tuple[tuple[RoutineFeedback, re.Pattern[str]], ...] = (
    (RoutineFeedback.IGNORE, re.compile(
        rf"^\s*{_REFERENCE}\s+(?:kuenftig\s+)?(?:ignorieren|nie\s+wieder)(?:\s+bitte)?\s*$"
    )),
    (RoutineFeedback.LATER, re.compile(
        rf"^\s*(?:frag\w*\s+)?{_REFERENCE}\s+(?:spaeter|noch\s+einmal\s+spaeter)(?:\s+bitte)?\s*$"
    )),
    (RoutineFeedback.HELPFUL, re.compile(
        rf"^\s*{_REFERENCE}\s+(?:war|ist)\s+hilfreich\s*$"
    )),
    (RoutineFeedback.UNNECESSARY, re.compile(
        rf"^\s*{_REFERENCE}\s+(?:war|ist)\s+(?:unnoetig|nicht\s+hilfreich)\s*$"
    )),
    (RoutineFeedback.WRONG, re.compile(
        rf"^\s*{_REFERENCE}\s+(?:war|ist)\s+falsch\s*$"
    )),
)


def interpret_routine_feedback(
    document: LanguageDocument,
) -> RoutineFeedbackIntent | None:
    """Interpret an explicit referential feedback sentence, never bare praise."""
    text = normalize_for_compare(document.normalized_text)
    for feedback, pattern in _PATTERNS:
        if pattern.fullmatch(text):
            return RoutineFeedbackIntent(feedback)
    return None


__all__ = ("RoutineFeedbackIntent", "interpret_routine_feedback")
