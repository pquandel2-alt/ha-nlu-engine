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

from hassil import Intents, RangeSlotList, RangeType, TextSlotList, WildcardSlotList, recognize

from .areas import AreaResolveStatus, resolve_area_name
from .entities import EntitySnapshot, ResolveStatus, resolve_entities_by_domain, resolve_entity
from .nlu.frame import AreaReference, SemanticFrame, TargetReference
from .service_call import INTENTS, PERCENT_INTENTS, QUERY_INTENTS, ServiceCallPlan

INTENTS_DIR = Path(__file__).parent / "intents" / "de"
QUANTIFIERS_DIR = INTENTS_DIR / "quantifiers"
PERCENTAGE_DIR = INTENTS_DIR / "percentage"

# Sentences containing "Prozent" are routed to a third, separately-compiled
# grammar (see _match_percentage) for the same reason as the quantifier
# grammar above: the existing {name}-wildcard close-cover sentence
# ("fahre {name} runter") would otherwise structurally swallow
# "Rolllade im Büro auf 30 Prozent" as {name}.
_PERCENT_RE = re.compile(r"\bprozent\b", re.IGNORECASE)

# Real users type "30%"/"30 %" in the Assist chat UI, not the word "Prozent" -
# neither the router regex above nor the percentage grammar's fixed literal
# text "Prozent" recognizes the symbol. Normalizing it to the word form
# before any matching happens keeps hassil's grammar (and RangeSlotList,
# which has no built-in "%"-symbol parsing - RangeType.PERCENTAGE is just a
# label) as the single source of truth for the sentence shape.
_PERCENT_SYMBOL_RE = re.compile(r"(\d)\s*%")


def _normalize_percent_symbol(text: str) -> str:
    return _PERCENT_SYMBOL_RE.sub(r"\1 Prozent", text)

# Sentences containing "alle"/"beide[n/r]" are routed to a separate,
# separately-compiled Intents grammar (see _match_quantifier) rather than
# mixed into the {name}-wildcard grammar above - hassil's recognize() would
# otherwise structurally match both grammars for the same sentence and
# silently pick whichever comes first in file/sentence order.
_QUANTIFIER_RE = re.compile(r"\b(alle|beide[nr]?)\b", re.IGNORECASE)

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
# _match_quantifier can apply the "beide" == exactly 2 hits rule directly.
_QUANTIFIER_SLOT_LIST = TextSlotList.from_tuples(
    [("alle", "all"), ("beide", "both"), ("beiden", "both"), ("beider", "both")],
    name="quantifier",
)

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
    plan: ServiceCallPlan | None
    response_text: str
    # SemanticFrame representation of the same match, built alongside the
    # existing plan/response_text - not yet consumed anywhere (see plan
    # Phase 1: "Parser darf zunaechst nur ein Frame erzeugen, noch kein
    # ServiceCall"). ServiceCallPlan generation still goes through the
    # pre-existing INTENTS/PERCENT_INTENTS/QUERY_INTENTS specs unchanged.
    frame: SemanticFrame | None = None


class NluEngine:
    """Loads all intent YAML files once at construction; ``match()`` is
    stateless per call (entities are passed in fresh each time since HA
    entity state changes between conversation turns)."""

    def __init__(
        self,
        intents_dir: Path = INTENTS_DIR,
        quantifiers_dir: Path = QUANTIFIERS_DIR,
        percentage_dir: Path = PERCENTAGE_DIR,
    ) -> None:
        yaml_files = sorted(intents_dir.glob("*.yaml"))
        if not yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {intents_dir}")
        self._intents: Intents = Intents.from_files(yaml_files)

        quantifier_yaml_files = sorted(quantifiers_dir.glob("*.yaml"))
        if not quantifier_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {quantifiers_dir}")
        self._quantifier_intents: Intents = Intents.from_files(quantifier_yaml_files)

        percentage_yaml_files = sorted(percentage_dir.glob("*.yaml"))
        if not percentage_yaml_files:
            raise FileNotFoundError(f"No intent YAML files found in {percentage_dir}")
        self._percentage_intents: Intents = Intents.from_files(percentage_yaml_files)

    def match(self, text: str, entities: list[EntitySnapshot]) -> MatchResult | None:
        text = _normalize_percent_symbol(text)
        if _PERCENT_RE.search(text):
            return self._match_percentage(text, entities)
        if _QUANTIFIER_RE.search(text):
            return self._match_quantifier(text, entities)
        return self._match_single(text, entities)

    def _match_single(self, text: str, entities: list[EntitySnapshot]) -> MatchResult | None:
        slot_lists = {"name": WildcardSlotList(name="name")}
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        name_slot = result.entities.get("name")
        if name_slot is None:
            return None

        name = _strip_locative_prepositions(str(name_slot.value))
        resolved = resolve_entity(name, entities)
        if resolved.status is not ResolveStatus.OK or resolved.entity is None:
            return None

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=name, entity_id=resolved.entity.entity_id, domain=resolved.entity.domain),
            area=None,
            source_text=text,
        )

        query_spec = QUERY_INTENTS.get(result.intent.name)
        if query_spec is not None:
            if resolved.entity.domain not in query_spec.allowed_domains:
                return None
            return MatchResult(plan=None, response_text=query_spec.response([resolved.entity]), frame=frame)

        spec = INTENTS.get(result.intent.name)
        if spec is None:
            return None
        if resolved.entity.domain not in spec.allowed_domains:
            return None

        return MatchResult(
            plan=spec.build([resolved.entity]),
            response_text=spec.response([resolved.entity]),
            frame=frame,
        )

    def _match_quantifier(self, text: str, entities: list[EntitySnapshot]) -> MatchResult | None:
        slot_lists = {
            "domain": _DOMAIN_SLOT_LIST,
            "area": WildcardSlotList(name="area"),
            "quantifier": _QUANTIFIER_SLOT_LIST,
        }
        result = recognize(text, self._quantifier_intents, slot_lists=slot_lists, language="de")
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
        area_slot = result.entities.get("area")
        if area_slot is not None:
            area_name = _strip_locative_prepositions(str(area_slot.value))
            if area_name:
                area_resolved = resolve_area_name(area_name, entities)
                if area_resolved.status is not AreaResolveStatus.OK:
                    return None  # unknown/ambiguous room - never guess
                area_id = area_resolved.area_id

        matches = resolve_entities_by_domain(domain, entities, area_id=area_id)
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
        return MatchResult(plan=spec.build(matches), response_text=spec.response(matches), frame=frame)

    def _match_percentage(self, text: str, entities: list[EntitySnapshot]) -> MatchResult | None:
        slot_lists = {
            "name": WildcardSlotList(name="name"),
            "percent": RangeSlotList(name="percent", start=0, stop=100, step=1, type=RangeType.PERCENTAGE),
        }
        result = recognize(text, self._percentage_intents, slot_lists=slot_lists, language="de")
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
        resolved = resolve_entity(name, entities)
        if resolved.status is not ResolveStatus.OK or resolved.entity is None:
            return None

        # Which service call applies is decided by the resolved entity's
        # actual domain, not by the verb used - see PERCENT_INTENTS docstring.
        spec = PERCENT_INTENTS.get(resolved.entity.domain)
        if spec is None:
            return None

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=name, entity_id=resolved.entity.entity_id, domain=resolved.entity.domain),
            area=None,
            parameters={"percent": percent},
            source_text=text,
        )
        return MatchResult(
            plan=spec.build([resolved.entity], percent),
            response_text=spec.response([resolved.entity], percent),
            frame=frame,
        )
