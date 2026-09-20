"""Explicit, confirmed and locally persisted spoken entity aliases."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .customization import parse_custom_aliases
from .entities import EntitySnapshot, normalize_for_compare
from .nlu.entity_resolution import ResolutionStatus, resolve_entity_scored


@dataclass(frozen=True)
class AliasLearningDraft:
    alias: str
    entity_id: str
    entity_name: str


_PATTERNS = (
    re.compile(r"^\s*mit\s+(?P<alias>.+?)\s+meine\s+ich\s+(?P<target>.+?)\s*[.!?]*$", re.I),
    re.compile(r"^\s*nenn(?:e)?\s+(?P<target>.+?)\s+(?:kuenftig|künftig|ab\s+jetzt)\s+(?P<alias>.+?)\s*[.!?]*$", re.I),
    re.compile(r"^\s*(?P<alias>.+?)\s+(?:bedeutet|ist\s+mein\s+name\s+fuer|ist\s+mein\s+name\s+für)\s+(?P<target>.+?)\s*[.!?]*$", re.I),
)


def parse_alias_learning(
    text: str, entities: list[EntitySnapshot]
) -> AliasLearningDraft | None:
    """Parse only explicit teaching language with one existing target."""
    match = next((match for pattern in _PATTERNS if (match := pattern.match(text))), None)
    if match is None:
        return None
    alias = match.group("alias").strip(" \"„“'.!?")
    target = match.group("target").strip(" \"„“'.!?")
    if (
        len(alias) < 2 or len(alias) > 80 or "=" in alias or "\n" in alias
        or normalize_for_compare(alias) == normalize_for_compare(target)
    ):
        return None
    resolved = resolve_entity_scored(target, entities)
    if resolved.status is not ResolutionStatus.RESOLVED or resolved.entity is None:
        return None
    # Never shadow another selected entity's canonical name or alias.
    collision = resolve_entity_scored(alias, entities)
    if (
        collision.status is ResolutionStatus.RESOLVED
        and collision.entity is not None
        and collision.entity.entity_id != resolved.entity.entity_id
    ) or collision.status is ResolutionStatus.AMBIGUOUS:
        return None
    return AliasLearningDraft(alias, resolved.entity.entity_id, resolved.entity.friendly_name)


def append_alias_rule(existing: object, draft: AliasLearningDraft) -> str:
    """Append one validated rule idempotently; reject cross-entity conflicts."""
    current = str(existing or "").strip()
    parsed = parse_custom_aliases(current)
    alias_key = draft.alias.casefold()
    for entity_id, aliases in parsed.items():
        if any(alias.casefold() == alias_key for alias in aliases):
            if entity_id != draft.entity_id:
                raise ValueError(f"Der Alias „{draft.alias}“ gehört bereits zu {entity_id}.")
            return current
    line = f"{draft.alias} = {draft.entity_id}"
    return f"{current}\n{line}" if current else line
