"""Deterministic NLU matching: hassil for sentence structure, ``entities``
for name resolution. No fuzzy scoring anywhere in the pipeline.

A hit requires all three to hold:
  1. hassil ``recognize()`` matches a sentence template for a known intent.
  2. The captured ``{name}`` resolves unambiguously to exactly one entity
     (``entities.resolve_entity`` - exact match, or unambiguous contains-match).
  3. The resolved entity's domain is allowed for the matched intent.

Anything else (no template match, ambiguous/unknown name, wrong domain)
returns ``None`` - the caller (``conversation.py``) turns that into a fixed
"not understood" response. There is no LLM fallback and no confidence score;
this is intentional (see plan: predictability over coverage).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from hassil import Intents, WildcardSlotList, recognize

from .entities import EntitySnapshot, ResolveStatus, resolve_entity
from .service_call import INTENTS, ServiceCallPlan

INTENTS_DIR = Path(__file__).parent / "intents" / "de"

# The {name} wildcard captures everything between the fixed template words,
# so "fahre die Rollade im Büro hoch" captures "Rollade im Büro" verbatim -
# including the preposition. Real HA friendly names are almost never a
# grammatically exact match ("Rolllade Büro", not "Rolllade im Büro"), so
# without stripping these the captured text falls through to a fragile
# contains-match (or misses an exact match it should have hit). Stripping
# is safe: none of these words plausibly appear as part of a real entity
# name, only as connective glue in a spoken sentence.
_LOCATIVE_PREPOSITIONS = re.compile(r"\b(in der|in dem|im|am|beim)\b", re.IGNORECASE)


def _strip_locative_prepositions(name: str) -> str:
    without_prepositions = _LOCATIVE_PREPOSITIONS.sub(" ", name)
    return re.sub(r"\s+", " ", without_prepositions).strip()


@dataclass(frozen=True)
class MatchResult:
    plan: ServiceCallPlan
    response_text: str


class NluEngine:
    """Loads all intent YAML files once at construction; ``match()`` is
    stateless per call (entities are passed in fresh each time since HA
    entity state changes between conversation turns)."""

    def __init__(self, intents_dir: Path = INTENTS_DIR) -> None:
        yaml_files = sorted(intents_dir.glob("*.yaml"))
        if not yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {intents_dir}")
        self._intents: Intents = Intents.from_files(yaml_files)

    def match(self, text: str, entities: list[EntitySnapshot]) -> MatchResult | None:
        slot_lists = {"name": WildcardSlotList(name="name")}
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        spec = INTENTS.get(result.intent.name)
        if spec is None:
            return None

        name_slot = result.entities.get("name")
        if name_slot is None:
            return None

        name = _strip_locative_prepositions(str(name_slot.value))
        resolved = resolve_entity(name, entities)
        if resolved.status is not ResolveStatus.OK or resolved.entity is None:
            return None
        if resolved.entity.domain not in spec.allowed_domains:
            return None

        return MatchResult(
            plan=spec.build(resolved.entity),
            response_text=spec.response(resolved.entity),
        )
