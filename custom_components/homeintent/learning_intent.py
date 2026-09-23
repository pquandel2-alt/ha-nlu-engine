"""Deterministic V11 knowledge-management meanings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class LearningOperation(StrEnum):
    LIST = "list"
    EXPLAIN = "explain"
    FORGET_MODEL = "forget_model"
    RESET = "reset"


@dataclass(frozen=True)
class LearningRequest:
    operation: LearningOperation
    subject_hint: str | None = None


def interpret_learning_request(text: str) -> LearningRequest | None:
    normalized = " ".join(text.casefold().strip().split())
    if re.search(r"\b(?:setz|setze|lösche|loesche|vergiss)\b.*\b(?:alle|alles)\b.*\b(?:\w*lern\w*|modell\w*)", normalized):
        return LearningRequest(LearningOperation.RESET)
    if re.search(r"\b(?:vergiss|lösche|loesche)\b.*\b(?:modell|gelernt|gewohnheit|präferenz|praeferenz)", normalized):
        return LearningRequest(LearningOperation.FORGET_MODEL, _subject(normalized))
    if re.search(r"\bwarum\b.*\b(?:glaubst|denkst|startest|nimmst)\b", normalized):
        return LearningRequest(LearningOperation.EXPLAIN, _subject(normalized))
    if re.search(
        r"\b(?:was|welche)\b.*\b(?:gelernt|gewohnheiten?|modelle|(?:licht|komfort|temperatur)?präferenzen?|(?:licht|komfort|temperatur)?praeferenzen?)\b",
        normalized,
    ):
        return LearningRequest(LearningOperation.LIST, _subject(normalized))
    return None


def _subject(text: str) -> str | None:
    for subject in ("wohnzimmer", "heizung", "garage", "licht", "lampe", "morgenroutine"):
        if subject in text:
            return subject
    return None


__all__ = ("LearningOperation", "LearningRequest", "interpret_learning_request")
