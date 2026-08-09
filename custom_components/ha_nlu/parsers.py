"""Concrete IntentParser implementations (v2 plan, Phase 2 - "Intent-System
vereinheitlichen"). Each parser wraps one of the three separately-compiled
hassil grammars (see engine.py's module docstring for why they must stay
separate) and turns a recognized sentence into a ``ParseResult`` -
sentence-matching + entity/area resolution stays here, so ``engine.py``
itself only has to route text to the right parser and turn the result into
a ``ServiceCallPlan``.
"""

from __future__ import annotations

import re

from hassil import Intents, RangeSlotList, RangeType, TextSlotList, WildcardSlotList, recognize

from .areas import AreaResolveStatus, resolve_area_name
from .entities import ResolveStatus, resolve_entities_by_domain, resolve_entity
from .nlu.frame import AreaReference, SemanticFrame, TargetReference
from .nlu.parser import ParseContext, ParseResult
from .service_call import INTENTS, PERCENT_INTENTS, QUERY_INTENTS

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


# German word -> canonical HA domain, including the "Rolladen" (one l)
# misspelling seen in real user speech.
_DOMAIN_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("Licht", "light"), ("Lichter", "light"), ("Lampe", "light"), ("Lampen", "light"),
        ("Schalter", "switch"), ("Steckdose", "switch"), ("Steckdosen", "switch"),
        ("Rollladen", "cover"), ("Rollläden", "cover"), ("Rolladen", "cover"), ("Rolläden", "cover"),
        ("Rollo", "cover"), ("Rollos", "cover"),
        ("Ventilator", "fan"), ("Ventilatoren", "fan"),
    ],
    name="domain",
)

# Maps straight to "all"/"both" (rather than the raw German word) so
# QuantifierParser can apply the "beide" == exactly 2 hits rule directly.
_QUANTIFIER_SLOT_LIST = TextSlotList.from_tuples(
    [("alle", "all"), ("beide", "both"), ("beiden", "both"), ("beider", "both")],
    name="quantifier",
)


class SingleTargetParser:
    """Wraps the ``{name}``-wildcard grammar (turn on/off/toggle, open/close
    cover, sensor queries) - one specific entity, resolved by name."""

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | None:
        slot_lists = {"name": WildcardSlotList(name="name")}
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        name_slot = result.entities.get("name")
        if name_slot is None:
            return None

        name = _strip_locative_prepositions(str(name_slot.value))
        resolved = resolve_entity(name, context.entities)
        if resolved.status is not ResolveStatus.OK or resolved.entity is None:
            return None

        query_spec = QUERY_INTENTS.get(result.intent.name)
        if query_spec is not None:
            if resolved.entity.domain not in query_spec.allowed_domains:
                return None
        else:
            spec = INTENTS.get(result.intent.name)
            if spec is None or resolved.entity.domain not in spec.allowed_domains:
                return None

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=name, entity_id=resolved.entity.entity_id, domain=resolved.entity.domain),
            area=None,
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=[resolved.entity])


class QuantifierParser:
    """Wraps the {domain}/{area}/{quantifier} grammar ("alle"/"beide[n/r]")."""

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | None:
        slot_lists = {
            "domain": _DOMAIN_SLOT_LIST,
            "area": WildcardSlotList(name="area"),
            "quantifier": _QUANTIFIER_SLOT_LIST,
        }
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        spec = INTENTS.get(result.intent.name)
        if spec is None:
            return None

        domain_slot = result.entities.get("domain")
        if domain_slot is None:
            return None
        domain = str(domain_slot.value)
        if domain not in spec.allowed_domains:
            return None

        quantifier_slot = result.entities.get("quantifier")
        if quantifier_slot is None:
            return None
        quantifier = str(quantifier_slot.value)

        area_id = None
        area_name = None
        area_slot = result.entities.get("area")
        if area_slot is not None:
            area_name = _strip_locative_prepositions(str(area_slot.value))
            if area_name:
                area_resolved = resolve_area_name(area_name, context.entities)
                if area_resolved.status is not AreaResolveStatus.OK:
                    return None  # unknown/ambiguous room - never guess
                area_id = area_resolved.area_id
            else:
                area_name = None

        matches = resolve_entities_by_domain(domain, context.entities, area_id=area_id)
        if not matches:
            return None
        if quantifier == "both" and len(matches) != 2:
            return None  # "beide" requires exactly 2 hits - otherwise not understood

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=domain, domain=domain),
            area=AreaReference(text=area_name, area_id=area_id) if area_id is not None else None,
            parameters={"quantifier": quantifier},
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=matches)


class PercentageParser:
    """Wraps the {name}/{percent} grammar (cover position / light brightness)."""

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | None:
        slot_lists = {
            "name": WildcardSlotList(name="name"),
            "percent": RangeSlotList(name="percent", start=0, stop=100, step=1, type=RangeType.PERCENTAGE),
        }
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        name_slot = result.entities.get("name")
        percent_slot = result.entities.get("percent")
        if name_slot is None or percent_slot is None:
            return None

        percent = int(percent_slot.value)
        if not 0 <= percent <= 100:
            return None  # RangeSlotList already guarantees this structurally; kept as an explicit guard

        name = _strip_locative_prepositions(str(name_slot.value))
        resolved = resolve_entity(name, context.entities)
        if resolved.status is not ResolveStatus.OK or resolved.entity is None:
            return None

        # Which service call applies is decided by the resolved entity's
        # actual domain, not by the verb used - see PERCENT_INTENTS docstring.
        if PERCENT_INTENTS.get(resolved.entity.domain) is None:
            return None

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=name, entity_id=resolved.entity.entity_id, domain=resolved.entity.domain),
            area=None,
            parameters={"percent": percent},
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=[resolved.entity])
