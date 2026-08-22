"""Order-independent semantic analysis for direct device-group commands.

Hassil remains the fast path for established sentence families.  This
module is the compositional fallback: it identifies the independently
meaningful parts of a group request (device domain, amount, location and
action) without requiring those parts to occur in one enumerated order.
Only a complete, unambiguous combination produces a ParseResult.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..areas import AreaResolveStatus, resolve_area_name
from ..entities import EntitySnapshot
from ..floors import FloorResolveStatus, resolve_floor_name
from .constraint_resolver import Constraints, resolve_candidates
from .frame import AreaReference, Quantifier, SemanticFrame, TargetReference
from .parser import ParseResult


@dataclass(frozen=True)
class GroupMeaning:
    """Semantic slots extracted from a freely ordered group command."""

    intent: str
    domain: str
    quantifier: str
    quantifier_value: int | None
    location_text: str | None
    area_id: str | None
    floor_id: str | None


_DOMAIN_PATTERNS = {
    "light": re.compile(r"\b(?:licht(?:er)?|lamp(?:e|en))\b", re.IGNORECASE),
    "switch": re.compile(r"\b(?:schalter|steckdos(?:e|en))\b", re.IGNORECASE),
    "cover": re.compile(
        r"\b(?:rol{2,3}[aä]den|rollos?)\b", re.IGNORECASE
    ),
    "fan": re.compile(r"\bventilator(?:en)?\b", re.IGNORECASE),
}

_CLEAR_PLURAL_PATTERNS = {
    "light": re.compile(r"\b(?:lichter|lampen)\b", re.IGNORECASE),
    "switch": re.compile(r"\bsteckdosen\b", re.IGNORECASE),
    "cover": re.compile(r"\b(?:rollläden|rolläden|rollos)\b", re.IGNORECASE),
    "fan": re.compile(r"\bventilatoren\b", re.IGNORECASE),
}

_COUNT_WORDS = {
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fünf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
}
_COUNT_RE = re.compile(
    r"\b(" + "|".join(_COUNT_WORDS) + r"|[2-9]|10)\b", re.IGNORECASE
)
_ALL_RE = re.compile(r"\b(?:alle|nur)\b", re.IGNORECASE)
_BOTH_RE = re.compile(r"\bbeide(?:n|r)?\b", re.IGNORECASE)
_LOCATIVE_RE = re.compile(r"\b(?:in der|in dem|im|am|beim)\b", re.IGNORECASE)

_COVER_VERB_RE = re.compile(
    r"\b(?:fahr|fahre|fahren|hochfahren|runterfahren|herunterfahren|"
    r"öffne|öffnen|schließe|schließen|mach|mache)\b",
    re.IGNORECASE,
)
_COVER_OPEN_RE = re.compile(r"\b(?:hoch|hochfahren|öffne|öffnen|auf)\b", re.IGNORECASE)
_COVER_CLOSE_RE = re.compile(
    r"\b(?:runter|herunter|runterfahren|herunterfahren|schließe|schließen|zu)\b",
    re.IGNORECASE,
)
_POWER_VERB_RE = re.compile(
    r"\b(?:mach|mache|anmachen|ausmachen|schalte|einschalten|ausschalten|"
    r"dreh|drehe|lass|toggle)\b",
    re.IGNORECASE,
)
_POWER_ON_RE = re.compile(r"\b(?:an|ein|anmachen|einschalten)\b", re.IGNORECASE)
_POWER_OFF_RE = re.compile(r"\b(?:aus|ausmachen|ausschalten)\b", re.IGNORECASE)
_POWER_TOGGLE_RE = re.compile(r"\b(?:um|toggle)\b", re.IGNORECASE)


def resolve_group_location(
    name: str, entities: list[EntitySnapshot]
) -> tuple[str | None, str | None] | None:
    """Resolve a group scope as ``(area_id, floor_id)``, floor first."""
    floor = resolve_floor_name(name, entities)
    if floor.status is FloorResolveStatus.OK:
        return None, floor.floor_id

    area = resolve_area_name(name, entities)
    if area.status is AreaResolveStatus.OK:
        return area.area_id, None
    return None


def _domain(text: str) -> tuple[str, re.Match[str]] | None:
    found = [
        (domain, match)
        for domain, pattern in _DOMAIN_PATTERNS.items()
        if (match := pattern.search(text)) is not None
    ]
    return found[0] if len(found) == 1 else None


def _quantifier(
    text: str, domain: str, domain_match: re.Match[str]
) -> tuple[str, int | None] | None:
    if _BOTH_RE.search(text):
        return "both", None
    if _ALL_RE.search(text):
        return "all", None
    count = _COUNT_RE.search(text)
    if count is not None:
        raw = count.group(1).lower()
        return "count", _COUNT_WORDS.get(raw, int(raw) if raw.isdigit() else None)

    # Plural device wording itself expresses an all-group.  "Rollladen" and
    # "Schalter" are number-ambiguous in German, so for those the plural
    # article immediately before the detected domain is required.
    if _CLEAR_PLURAL_PATTERNS[domain].search(text):
        return "all", None
    prefix = text[: domain_match.start()]
    if re.search(r"\bdie\s*$", prefix, re.IGNORECASE):
        return "all", None
    return None


def _intent(text: str, domain: str) -> str | None:
    if domain == "cover":
        if _COVER_VERB_RE.search(text) is None:
            return None
        opens = _COVER_OPEN_RE.search(text) is not None
        closes = _COVER_CLOSE_RE.search(text) is not None
        if opens == closes:
            return None
        return "HassOpenCover" if opens else "HassCloseCover"

    if _POWER_VERB_RE.search(text) is None:
        return None
    toggles = _POWER_TOGGLE_RE.search(text) is not None
    turns_on = _POWER_ON_RE.search(text) is not None
    turns_off = _POWER_OFF_RE.search(text) is not None
    if sum((toggles, turns_on, turns_off)) != 1:
        return None
    if toggles:
        return "HassToggle"
    return "HassTurnOn" if turns_on else "HassTurnOff"


def _location(
    text: str, entities: list[EntitySnapshot]
) -> tuple[str | None, str | None, str | None] | None:
    if _LOCATIVE_RE.search(text) is None:
        return None, None, None

    names: set[str] = set()
    for entity in entities:
        if entity.area_name:
            names.add(entity.area_name)
        names.update(alias for alias in entity.area_aliases if alias)
        if entity.floor_name:
            names.add(entity.floor_name)

    mentioned = [
        name
        for name in sorted(names, key=len, reverse=True)
        if re.search(
            rf"\b(?:in der|in dem|im|am|beim)\s+{re.escape(name)}\b",
            text,
            re.IGNORECASE,
        )
    ]
    if not mentioned:
        return None

    # A longer registry name contains a shorter one ("Büro 2"/"Büro").
    # Longest-match selection handles that without guessing. Two genuinely
    # separate mentioned locations remain ambiguous and are refused.
    longest = len(mentioned[0])
    selected = [name for name in mentioned if len(name) == longest]
    resolved = {resolve_group_location(name, entities) for name in selected}
    resolved.discard(None)
    if len(resolved) != 1:
        return None
    area_id, floor_id = resolved.pop()
    return selected[0], area_id, floor_id


def parse_flexible_group_command(
    text: str, entities: list[EntitySnapshot]
) -> ParseResult | None:
    """Compose a safe group command from freely ordered semantic slots."""
    if re.search(r"\baußer\b", text, re.IGNORECASE):
        return None  # exclusions stay on the stricter established grammar

    domain_result = _domain(text)
    if domain_result is None:
        return None
    domain, domain_match = domain_result

    quantifier_result = _quantifier(text, domain, domain_match)
    intent = _intent(text, domain)
    location = _location(text, entities)
    if quantifier_result is None or intent is None or location is None:
        return None

    quantifier, quantifier_value = quantifier_result
    location_text, area_id, floor_id = location
    matches = resolve_candidates(
        entities,
        Constraints(domain=domain, area_id=area_id, floor_id=floor_id),
    )
    if not matches:
        return None
    if quantifier == "both" and len(matches) != 2:
        return None
    if quantifier == "count" and len(matches) != quantifier_value:
        return None

    return ParseResult(
        frame=SemanticFrame(
            intent=intent,
            target=TargetReference(text=domain, domain=domain),
            area=(
                AreaReference(text=location_text, area_id=area_id)
                if area_id is not None
                else None
            ),
            quantifier=Quantifier(kind=quantifier, value=quantifier_value),
            source_text=text,
        ),
        resolved_entities=matches,
    )
