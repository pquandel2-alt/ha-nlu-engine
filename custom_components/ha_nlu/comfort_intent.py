"""Ground a vague comfort request in confirmed, structured preferences."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .entities import EntitySnapshot
from .house_graph import FactProvenance
from .memory import MemoryKind, MemoryRecord
from .nlu.language_frontend import LanguageDocument
from .service_call import ServiceCallPlan


_COMFORT_RE = re.compile(
    r"\b(?:mach|mache|macht)\b.*\b(?:gemuetlich|gemütlich)(?:er)?\b"
)


@dataclass(frozen=True)
class ComfortSuggestion:
    """One policy-neutral proposal; execution still needs confirmation."""

    plan: ServiceCallPlan
    target_name: str
    explanation: str


def is_comfort_request(document: LanguageDocument) -> bool:
    return bool(_COMFORT_RE.search(document.normalized_text.casefold()))


def select_comfort_suggestion(
    records: Iterable[MemoryRecord],
    entities: Iterable[EntitySnapshot],
    *,
    area_id: str | None,
) -> ComfortSuggestion | None:
    """Return a suggestion only when exactly one confirmed preference fits."""
    by_id = {entity.entity_id: entity for entity in entities}
    suggestions: list[ComfortSuggestion] = []
    for record in records:
        if (
            record.kind is not MemoryKind.PREFERENCE
            or record.provenance is not FactProvenance.CONFIRMED_MEMORY
        ):
            continue
        entity_id = record.content.get("entity_id")
        brightness = record.content.get("brightness_percent")
        if not isinstance(entity_id, str) or not isinstance(brightness, int):
            continue
        entity = by_id.get(entity_id)
        if (
            entity is None
            or entity.domain != "light"
            or "BRIGHTNESS" not in entity.capabilities
            or not 1 <= brightness <= 100
            or (area_id is not None and entity.area_id != area_id)
        ):
            continue
        activity = record.content.get("activity")
        activity_name = "Fernsehen" if activity == "television" else activity
        context = f" für {activity_name}" if isinstance(activity_name, str) else ""
        suggestions.append(
            ComfortSuggestion(
                ServiceCallPlan(
                    "light", "turn_on", entity.entity_id, {"brightness_pct": brightness}
                ),
                entity.friendly_name,
                f"bestätigte persönliche Präferenz{context}",
            )
        )
    return suggestions[0] if len(suggestions) == 1 else None
