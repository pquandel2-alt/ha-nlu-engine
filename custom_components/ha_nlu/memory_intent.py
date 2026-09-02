"""Structured memory-management meanings derived from LanguageDocument."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .entities import EntitySnapshot, normalize_for_compare
from .nlu.language_frontend import LanguageDocument


class MemoryOperation(StrEnum):
    REMEMBER_PREFERENCE = "remember_preference"
    FORGET_ROUTINES = "forget_routines"
    LIST = "list"
    RESET = "reset"


@dataclass(frozen=True)
class MemoryIntent:
    operation: MemoryOperation
    content: dict[str, object]
    target_entity_id: str | None = None
    ambiguous_entity_ids: tuple[str, ...] = ()


_PERCENT_RE = re.compile(r"\b(\d{1,3})\s*(?:prozent|%)\b")


def interpret_memory_intent(
    document: LanguageDocument, entities: list[EntitySnapshot]
) -> MemoryIntent | None:
    """Interpret only explicit memory verbs after the shared frontend."""
    text = normalize_for_compare(document.normalized_text)
    if re.search(r"\b(?:vergiss|loesche)\s+alles\s+ueber\s+meine\s+(?:persoenlichen\s+)?routinen\b", text):
        return MemoryIntent(MemoryOperation.FORGET_ROUTINES, {})
    if re.search(r"\b(?:vergiss|loesche)\s+(?:wirklich\s+)?alles\b", text):
        return MemoryIntent(MemoryOperation.RESET, {})
    if re.search(r"\b(?:was|welche)\b.*\b(?:gespeichert|gemerkt|erinnerungen|fakten)\b", text):
        return MemoryIntent(MemoryOperation.LIST, {})
    if not re.search(r"\b(?:merk|merke)\s+(?:dir\s+)?(?:dauerhaft\s+)?", text):
        return None
    if not re.search(r"\b(?:bevorzuge|moechte|will)\b", text):
        return None
    percent_match = _PERCENT_RE.search(text)
    if percent_match is None:
        return MemoryIntent(
            MemoryOperation.REMEMBER_PREFERENCE,
            {"activity": "unspecified", "missing": "value"},
        )
    percent = int(percent_match.group(1))
    if not 0 <= percent <= 100:
        return MemoryIntent(
            MemoryOperation.REMEMBER_PREFERENCE,
            {"activity": "unspecified", "invalid": "value"},
        )
    matches = [
        entity
        for entity in entities
        if normalize_for_compare(entity.friendly_name) in text
        or any(normalize_for_compare(alias) in text for alias in entity.aliases)
    ]
    target = matches[0].entity_id if len(matches) == 1 else None
    activity = "television" if re.search(r"\b(?:fernsehen|filmabend|tv)\b", text) else "unspecified"
    return MemoryIntent(
        MemoryOperation.REMEMBER_PREFERENCE,
        {"activity": activity, "brightness_percent": percent},
        target,
        tuple(entity.entity_id for entity in matches) if len(matches) > 1 else (),
    )
