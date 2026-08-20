"""Concrete IntentParser implementations (v2 plan, Phase 2 - "Intent-System
vereinheitlichen"). Each parser wraps one of the six separately-compiled
hassil grammars (see engine.py's module docstring for why they must stay
separate) and turns a recognized sentence into a ``ParseResult`` -
sentence-matching + entity/area resolution stays here, so ``engine.py``
itself only has to route text to the right parser and turn the result into
a ``ServiceCallPlan``.
"""

from __future__ import annotations

import re
from typing import Callable

from hassil import Intents, RangeSlotList, RangeType, WildcardSlotList, recognize

from .areas import AreaResolutionStatus, AreaResolveStatus, AreaSnapshot, resolve_area_name, resolve_area_scored
from .automation_summary import AutomationSummary
from .entities import (
    EntitySnapshot,
    ResolutionStatus,
    ResolveStatus,
    resolve_entity,
    resolve_entity_scored,
)
from .floors import FloorResolveStatus, resolve_floor_by_level_keyword, resolve_floor_name
from .nlu.constraint_resolver import Constraints, resolve_candidates
from .nlu.frame import AreaReference, Comparison, Quantifier, SemanticFrame, TargetReference, TemporalExpression
from .nlu.lexicon import (
    _COLOR_SLOT_LIST,
    _COLOR_TEMP_SLOT_LIST,
    _COMPARATOR_SLOT_LIST,
    _COMPARISON_DOMAIN_SLOT_LIST,
    _COUNT_SLOT_LIST,
    _DEVICE_CLASS_SLOT_LIST,
    _DOMAIN_SLOT_LIST,
    _LEVEL_SLOT_LIST,
    _QUANTIFIER_SLOT_LIST,
    _STATE_ADJ_SLOT_LIST,
    _STATE_SLOT_LIST,
    _TEMPORAL_KIND_SLOT_LIST,
    _TEMPORAL_RELATIVE_SLOT_LIST,
    _TEMPORAL_UNIT_SLOT_LIST,
)
from .nlu.command import SemanticCommand
from .nlu.parser import AmbiguousReference, ClarificationRequest, ParseContext, ParseResult
from .nlu.query_command import QueryCommand, QueryFilter, QueryResultStatus, QueryScope, QueryTarget, QueryTargetKind
from .world_model import WorldModel
from .nlu.query_executor import QueryExecutor
from .nlu.semantic_state import SemanticState
from .service_call import (
    ACTION_OPPOSITES,
    CLIMATE_EXTENDED_INTENTS,
    FAN_EXTENDED_INTENTS,
    INTENTS,
    LIGHT_EXTENDED_INTENTS,
    PERCENT_INTENTS,
    QUERY_INTENTS,
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


# Closed-vocabulary TextSlotList definitions (domain/quantifier/count/level/
# color/color_temp/comparator/comparison_domain/temporal_*/device_class/
# state/state_adj words) now live in nlu/lexicon.py (V6.3, "Semantic
# Lexicon") - see that module's docstring for the extraction rationale and
# each list's own inline documentation. Imported above under their original
# names so every parser/sentence below keeps working unchanged.

# User decision (AskUserQuestion, v2 plan Phase 14): "heller"/"dunkler"
# without an explicit {percent} slot default to 10% per command.
_DEFAULT_DIMMING_STEP_PERCENT = 10

# Comparison operator -> a Python callable, shared by both the {percent} and
# {temperature} branches of ComparisonQueryParser (the operator's meaning
# doesn't depend on which unit it's comparing).
_COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    "gte": lambda current, threshold: current >= threshold,
    "lte": lambda current, threshold: current <= threshold,
    "gt": lambda current, threshold: current > threshold,
    "lt": lambda current, threshold: current < threshold,
}


def _current_percent(entity: EntitySnapshot) -> float | None:
    """The entity's current value on a 0-100 scale, for the {percent} branch
    of a comparison query - light brightness (raw HA "brightness" attribute,
    0-255, same conversion _speak_brightness in service_call.py already
    performs) or cover position (raw HA "current_position" attribute,
    already 0-100 - same attribute nlu/capabilities.py reads for
    Capability.POSITION). Returns ``None`` when the entity doesn't report the
    attribute at all (e.g. an on/off-only light) - never guessed, just
    excluded from the match set by the caller.
    """
    if entity.domain == "light":
        brightness = entity.attributes.get("brightness")
        return brightness / 255 * 100 if brightness is not None else None
    if entity.domain == "cover":
        position = entity.attributes.get("current_position")
        return float(position) if position is not None else None
    return None


def _current_temperature(entity: EntitySnapshot) -> float | None:
    """The climate entity's current *room* temperature, for the
    {temperature} branch - the raw HA "current_temperature" attribute, not
    "temperature" (that one's the target setpoint, already read elsewhere by
    Capability.TEMPERATURE/HassClimateIncreaseTemperature - a different
    signal, see nlu/capabilities.py)."""
    current = entity.attributes.get("current_temperature")
    return float(current) if current is not None else None


class SingleTargetParser:
    """Wraps the ``{name}``-wildcard grammar (turn on/off/toggle, open/close
    cover, sensor queries) - one specific entity, resolved by name."""

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | ClarificationRequest | None:
        slot_lists = {"name": WildcardSlotList(name="name")}
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        name_slot = result.entities.get("name")
        if name_slot is None:
            return None

        name = _strip_locative_prepositions(str(name_slot.value))
        resolved = resolve_entity(name, context.entities)
        if resolved.status is ResolveStatus.AMBIGUOUS:
            # Only the 5 basic action intents (v2 plan Phase 25,
            # "Clarification") get a follow-up question - QUERY_INTENTS
            # (sensor reads) keep today's NOT_FOUND-equivalent behaviour,
            # since finishing a query needs no further parameters and an
            # ambiguous sensor name is rare enough that the extra round-trip
            # isn't worth the added branch; INTENTS.get() also doubles as
            # the "is this even a known intent" guard the non-ambiguous path
            # below performs via ``spec``.
            if INTENTS.get(result.intent.name) is not None:
                return ClarificationRequest(
                    pending_intent=result.intent.name, pending_target=name, candidates=resolved.candidates,
                )
            return None
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


class ContextFollowupParser:
    """Wraps a small, name-less grammar for elliptical follow-up commands
    that omit their target entirely ("Etwas heller.") - v2 plan Phase 26,
    "Context". Structurally distinct from every other grammar here (no
    {name} wildcard at all, just fixed sentences), so it's safe to try
    unconditionally rather than needing a keyword-routing regex like
    PercentageParser/LightExtendedParser/etc. in engine.py - the caller
    (``NluEngine.match_followup()``) decides *when* to try it (only with a
    stored ``ConversationContext``), not *whether the text could collide*.

    Deliberately entity-resolution-free: unlike every other parser, this one
    doesn't take a ``ParseContext`` and can't resolve a target itself - the
    caller supplies the previous turn's entity. Returns the bare intent name
    rather than a ``ParseResult``, since building the ``SemanticFrame``
    requires context this parser doesn't have.
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str) -> str | None:
        result = recognize(text, self._intents, language="de")
        if result is None or result.intent is None:
            return None
        return result.intent.name


class QuantifierParser:
    """Wraps the {domain}/{area}/{level}/{quantifier}/{count}/{name} grammar
    ("alle"/"beide[n/r]"/"nur"/count words/exclusion). {level} ("oben"/
    "unten") is v2 plan Phase 28, "Hierarchische Orte". {count}/{name} and
    the "nur" quantifier value are v2 plan Phase 29, "Natural Quantifiers" -
    the plan's own examples: "die beiden Lampen" (existing "both" quantifier,
    now reachable with an optional "die" prefix - see the quantifier YAMLs),
    "die drei Lichter" ({count} slot, generalizes "beide"'s exact-count rule
    to arbitrary N), "alle außer der Küchenlampe" ({name} exclusion clause),
    "nur die Wohnzimmerlampen" ("nur" added to _QUANTIFIER_SLOT_LIST,
    mapping to "all" - see that slot list's docstring for why there's no
    separate "only" kind).

    Three ways a sentence can express *how many*, mutually exclusive by
    sentence template (a sentence uses at most one of these slots):
      1. ``{quantifier}`` slot present -> "all"/"both" (or "all" via "nur").
      2. ``{count}`` slot present -> "count", with ``Quantifier.value`` set
         to the parsed number; ``len(matches)`` must equal it exactly, same
         "never guess" rule "beide" already established for count=2.
      3. Neither slot present -> the exclusion sentences ("alle {domain} an
         außer [dem|der|den] {name}") hardcode the literal "alle" in the
         YAML rather than using the {quantifier} slot (so "außer ..." can
         follow it without the quantifier grammar getting in the way) -
         defaults to "all" here.

    ``{name}``, when present, is the entity excluded from the match set
    ("außer der Küchenlampe"). Resolved with the same ``resolve_entity()``
    used for singular targets elsewhere, and the domain/area-filtered
    ``matches`` must already contain it - an exclusion target that doesn't
    resolve unambiguously, or that resolves to an entity outside the
    filtered set (wrong domain/room), refuses the whole command rather than
    silently matching everyone (that would misreport what got excluded).

    Area resolution has a floor fallback: if the captured {area} text
    doesn't resolve to a known room (``AreaResolveStatus.NOT_FOUND``), it's
    tried again as a floor name (e.g. "im Erdgeschoss") before giving up -
    same grammar slot, no separate {floor} sentence set needed, since a
    floor name occupies exactly the same "[in der|im|...] X" position a room
    name does. An *ambiguous* area match is never silently retried as a
    floor - that would risk masking a real ambiguity the user should be
    asked about (moot today, since AMBIGUOUS_ENTITY-style clarification
    isn't wired for quantifier commands, but keeps the fallback narrowly
    scoped to its one justified case: "this word is not a room").
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | None:
        slot_lists = {
            "domain": _DOMAIN_SLOT_LIST,
            "area": WildcardSlotList(name="area"),
            "level": _LEVEL_SLOT_LIST,
            "quantifier": _QUANTIFIER_SLOT_LIST,
            "count": _COUNT_SLOT_LIST,
            "name": WildcardSlotList(name="name"),
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
        count_slot = result.entities.get("count")
        quantifier_value: int | None = None
        if quantifier_slot is not None:
            quantifier = str(quantifier_slot.value)
        elif count_slot is not None:
            quantifier = "count"
            quantifier_value = int(count_slot.value)
        else:
            # Exclusion sentences hardcode the literal "alle" instead of
            # using the {quantifier} slot - see the class docstring.
            quantifier = "all"

        area_id = None
        area_name = None
        floor_id = None
        area_slot = result.entities.get("area")
        if area_slot is not None:
            area_name = _strip_locative_prepositions(str(area_slot.value))
            if area_name:
                area_resolved = resolve_area_name(area_name, context.entities)
                if area_resolved.status is AreaResolveStatus.OK:
                    area_id = area_resolved.area_id
                elif area_resolved.status is AreaResolveStatus.NOT_FOUND:
                    floor_resolved = resolve_floor_name(area_name, context.entities)
                    if floor_resolved.status is not FloorResolveStatus.OK:
                        return None  # neither a known room nor a known floor - never guess
                    floor_id = floor_resolved.floor_id
                else:
                    return None  # ambiguous room name - never guess
            else:
                area_name = None

        level_slot = result.entities.get("level")
        if level_slot is not None:
            level_resolved = resolve_floor_by_level_keyword(str(level_slot.value), context.entities)
            if level_resolved.status is not FloorResolveStatus.OK:
                return None  # no single oben/unten floor among today's entities - never guess
            floor_id = level_resolved.floor_id

        matches = resolve_candidates(
            context.entities, Constraints(domain=domain, area_id=area_id, floor_id=floor_id)
        )

        name_slot = result.entities.get("name")
        if name_slot is not None:
            exclude_name = _strip_locative_prepositions(str(name_slot.value))
            excluded = resolve_entity(exclude_name, context.entities)
            if excluded.status is not ResolveStatus.OK or excluded.entity is None:
                return None  # exclusion target doesn't resolve unambiguously - never guess
            if excluded.entity not in matches:
                return None  # not part of the filtered match set - refuse, don't silently no-op
            matches = [e for e in matches if e.entity_id != excluded.entity.entity_id]

        if not matches:
            return None
        if quantifier == "both" and len(matches) != 2:
            return None  # "beide" requires exactly 2 hits - otherwise not understood
        if quantifier == "count" and len(matches) != quantifier_value:
            return None  # "die drei Lichter" requires exactly 3 hits - same rule, generalized

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=domain, domain=domain),
            area=AreaReference(text=area_name, area_id=area_id) if area_id is not None else None,
            quantifier=Quantifier(kind=quantifier, value=quantifier_value),
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=matches)


class PercentageParser:
    """Wraps the {name}/{percent} grammar (cover position / light brightness).

    {comparator} (HomeIntent plan V4.6, "Comparisons", setpoint-synonym half
    per user decision 2026-08-11) is an optional slot on the same sentences -
    "stelle die Lampe auf mindestens 50 Prozent" still sets the target to
    exactly ``percent`` (the comparator doesn't change *what* gets set, only
    records *how* the user phrased it, in ``parameters["comparison"]`` for
    observability/future use)."""

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | None:
        slot_lists = {
            "name": WildcardSlotList(name="name"),
            "percent": RangeSlotList(name="percent", start=0, stop=100, step=1, type=RangeType.PERCENTAGE),
            "comparator": _COMPARATOR_SLOT_LIST,
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

        parameters: dict[str, object] = {"percent": percent}
        comparator_slot = result.entities.get("comparator")
        if comparator_slot is not None:
            parameters["comparison"] = Comparison(operator=str(comparator_slot.value), value=percent)

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=name, entity_id=resolved.entity.entity_id, domain=resolved.entity.domain),
            area=None,
            parameters=parameters,
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=[resolved.entity])


class FanExtendedParser:
    """Wraps the {name}/{level} grammar (fan speed set/increase/decrease) -
    the 5th separately-compiled hassil grammar (v2 plan Phase 16). {level}
    is anchored by the literal "auf Stufe" before it (not directly adjacent
    to {name}), avoiding the unanchored-WildcardSlotList-next-to-
    RangeSlotList bug documented for LightExtendedParser/PercentageParser -
    empirically verified against hassil==3.11.0 before this grammar was
    written.
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | None:
        slot_lists = {
            "name": WildcardSlotList(name="name"),
            "level": RangeSlotList(name="level", start=1, stop=10, step=1, type=RangeType.NUMBER),
        }
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

        # All 3 intents only ever target the fan domain (see
        # FAN_EXTENDED_INTENTS's docstring) - no per-intent allowed_domains
        # lookup needed, unlike INTENTS/PERCENT_INTENTS.
        if result.intent.name not in FAN_EXTENDED_INTENTS or resolved.entity.domain != "fan":
            return None

        if result.intent.name == "HassFanSetSpeed":
            level_slot = result.entities.get("level")
            if level_slot is None:
                return None
            parameters: dict[str, object] = {"level": int(level_slot.value)}
        else:  # HassFanIncreaseSpeed / HassFanDecreaseSpeed - no parameters
            parameters = {}

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=name, entity_id=resolved.entity.entity_id, domain=resolved.entity.domain),
            area=None,
            parameters=parameters,
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=[resolved.entity])


class ClimateExtendedParser:
    """Wraps the {name}/{temperature} grammar (climate set/increase/decrease
    temperature) - the 6th separately-compiled hassil grammar (v2 plan Phase
    17). {temperature} is anchored by the literal "auf ... Grad" around it
    (not directly adjacent to {name}), same anchoring precedent
    FanExtendedParser's {level} slot already established - empirically
    verified against hassil==3.11.0 before this grammar was written.

    {comparator} (HomeIntent plan V4.6, "Comparisons", setpoint-synonym half)
    is an optional slot on ``HassClimateSetTemperature``'s sentences only -
    same "records how it was phrased, doesn't change the target" behaviour
    as PercentageParser's own {comparator} handling.
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | None:
        slot_lists = {
            "name": WildcardSlotList(name="name"),
            "temperature": RangeSlotList(name="temperature", start=5, stop=30, step=1, type=RangeType.NUMBER),
            "comparator": _COMPARATOR_SLOT_LIST,
        }
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

        # All 3 intents only ever target the climate domain (see
        # CLIMATE_EXTENDED_INTENTS's docstring) - no per-intent allowed_domains
        # lookup needed, unlike INTENTS/PERCENT_INTENTS.
        if result.intent.name not in CLIMATE_EXTENDED_INTENTS or resolved.entity.domain != "climate":
            return None

        if result.intent.name == "HassClimateSetTemperature":
            temperature_slot = result.entities.get("temperature")
            if temperature_slot is None:
                return None
            temperature = int(temperature_slot.value)
            parameters: dict[str, object] = {"temperature": temperature}
            comparator_slot = result.entities.get("comparator")
            if comparator_slot is not None:
                parameters["comparison"] = Comparison(operator=str(comparator_slot.value), value=temperature)
        else:  # HassClimateIncreaseTemperature / HassClimateDecreaseTemperature - no parameters
            parameters = {}

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=name, entity_id=resolved.entity.entity_id, domain=resolved.entity.domain),
            area=None,
            parameters=parameters,
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=[resolved.entity])


class LightExtendedParser:
    """Wraps the {name}/{percent}/{color}/{color_temp} grammar (brightness
    adjust, colour, colour temperature) - the 4th separately-compiled hassil
    grammar (v2 plan Phase 14). Kept apart from PercentageParser's {name}/
    {percent} grammar because these sentences use "heller"/"dunkler"/colour
    words rather than an absolute "auf X Prozent" target, and apart from the
    plain {name} grammar because an unanchored {color}/{color_temp} slot
    directly adjacent to {name} (e.g. "mach das Licht rot") is a different
    sentence shape - empirically verified against hassil==3.11.0 not to
    collide with the "an"/"aus" turn-on/off sentences.
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | None:
        slot_lists = {
            "name": WildcardSlotList(name="name"),
            "percent": RangeSlotList(name="percent", start=0, stop=100, step=1, type=RangeType.PERCENTAGE),
            "color": _COLOR_SLOT_LIST,
            "color_temp": _COLOR_TEMP_SLOT_LIST,
        }
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

        # All 4 intents only ever target the light domain (see
        # LIGHT_EXTENDED_INTENTS's docstring) - no per-intent allowed_domains
        # lookup needed, unlike INTENTS/PERCENT_INTENTS.
        if result.intent.name not in LIGHT_EXTENDED_INTENTS or resolved.entity.domain != "light":
            return None

        if result.intent.name in ("HassLightBrighten", "HassLightDim"):
            percent_slot = result.entities.get("percent")
            step = int(percent_slot.value) if percent_slot is not None else _DEFAULT_DIMMING_STEP_PERCENT
            parameters: dict[str, object] = {"step_percent": step}
        elif result.intent.name == "HassLightSetColor":
            color_slot = result.entities.get("color")
            if color_slot is None:
                return None
            parameters = {"color_name": str(color_slot.value)}
        else:  # HassLightSetColorTemp
            color_temp_slot = result.entities.get("color_temp")
            if color_temp_slot is None:
                return None
            parameters = {"color_temp_kelvin": int(color_temp_slot.value)}

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=name, entity_id=resolved.entity.entity_id, domain=resolved.entity.domain),
            area=None,
            parameters=parameters,
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=[resolved.entity])


class ComparisonQueryParser:
    """Wraps the {domain}/{comparator}/{percent}/{temperature}/{area}
    grammar ("welche Lichter sind mindestens 50 Prozent", "welche Räume sind
    unter 20 Grad") - the 9th separately-compiled hassil grammar, HomeIntent
    plan V4.6's query-filter half (user decision 2026-08-11: needed alongside
    the setpoint-synonym half PercentageParser/ClimateExtendedParser now
    carry). Unlike every other query intent (``QUERY_INTENTS``' only other
    entry, ``HassGetState``, always resolves to exactly one entity),
    this is the first multi-entity query - it keeps only the entities whose
    *current* value satisfies the comparison, same "resolve then filter"
    shape ``QuantifierParser`` already established for "alle X im Y".

    Two mutually exclusive branches by which value slot is present ({percent}
    or {temperature} - a sentence uses exactly one, never both):
      - {percent}: current value read via ``_current_percent`` (light
        brightness 0-255->0-100, cover position already 0-100) - only valid
        for ``domain in ("light", "cover")``.
      - {temperature}: current value read via ``_current_temperature`` (the
        climate entity's *current room* temperature, not its target setpoint)
        - only valid for ``domain == "climate"``.
    A domain/value-slot mismatch ("welche Lichter sind unter 20 Grad" - a
    light has no Grad value) has no defined meaning and returns ``None``
    rather than guessing what was meant.

    Entities that don't report the needed attribute at all (e.g. an
    on/off-only light has no "brightness") are silently excluded from the
    match set, not treated as a comparison failure or a hard error - same
    "skip what can't be evaluated" behaviour capabilities.py already applies
    elsewhere. An empty result set after filtering returns ``None`` (nothing
    to report), same as ``QuantifierParser``'s "no matches" case.

    ``frame.quantifier`` is always set to ``Quantifier(kind="all")`` (even
    for a single-entity result) - required so ``validate_command()``'s check
    #3 doesn't misfire on a multi-entity match, same precedent
    ``ReferenceParser`` already established for its own multi-entity
    branches.
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | None:
        slot_lists = {
            "domain": _COMPARISON_DOMAIN_SLOT_LIST,
            "comparator": _COMPARATOR_SLOT_LIST,
            "percent": RangeSlotList(name="percent", start=0, stop=100, step=1, type=RangeType.PERCENTAGE),
            "temperature": RangeSlotList(name="temperature", start=0, stop=40, step=1, type=RangeType.NUMBER),
            "area": WildcardSlotList(name="area"),
        }
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        spec = QUERY_INTENTS.get(result.intent.name)
        if spec is None:
            return None

        domain_slot = result.entities.get("domain")
        comparator_slot = result.entities.get("comparator")
        if domain_slot is None or comparator_slot is None:
            return None
        domain = str(domain_slot.value)
        if domain not in spec.allowed_domains:
            return None
        comparator = str(comparator_slot.value)

        percent_slot = result.entities.get("percent")
        temperature_slot = result.entities.get("temperature")
        if percent_slot is not None and domain in ("light", "cover"):
            threshold = float(percent_slot.value)
            current_value = _current_percent
        elif temperature_slot is not None and domain == "climate":
            threshold = float(temperature_slot.value)
            current_value = _current_temperature
        else:
            return None  # value slot doesn't match the domain - no defined meaning, never guess

        area_id = None
        area_name = None
        floor_id = None
        area_slot = result.entities.get("area")
        if area_slot is not None:
            area_name = _strip_locative_prepositions(str(area_slot.value))
            if area_name:
                area_resolved = resolve_area_name(area_name, context.entities)
                if area_resolved.status is AreaResolveStatus.OK:
                    area_id = area_resolved.area_id
                elif area_resolved.status is AreaResolveStatus.NOT_FOUND:
                    floor_resolved = resolve_floor_name(area_name, context.entities)
                    if floor_resolved.status is not FloorResolveStatus.OK:
                        return None  # neither a known room nor a known floor - never guess
                    floor_id = floor_resolved.floor_id
                else:
                    return None  # ambiguous room name - never guess
            else:
                area_name = None

        candidates = resolve_candidates(
            context.entities, Constraints(domain=domain, area_id=area_id, floor_id=floor_id)
        )
        compare = _COMPARATORS[comparator]
        matches = [e for e in candidates if (v := current_value(e)) is not None and compare(v, threshold)]
        if not matches:
            return None

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=domain, domain=domain),
            area=AreaReference(text=area_name, area_id=area_id) if area_id is not None else None,
            quantifier=Quantifier(kind="all"),
            parameters={"comparison": Comparison(operator=comparator, value=threshold)},
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=matches)


# _TEMPORAL_KIND_SLOT_LIST/_TEMPORAL_UNIT_SLOT_LIST/_TEMPORAL_RELATIVE_SLOT_LIST
# now live in nlu/lexicon.py (V6.3, "Semantic Lexicon") - imported above.


class TemporalParser:
    """Wraps the {name}/{temporal_kind}/{amount}/{unit}/{relative}/{hour}
    grammar ("mach das Licht in fünf Minuten aus", "... für eine Stunde an",
    "... morgen früh an", "... um 20 Uhr an") - the 10th separately-compiled
    hassil grammar, HomeIntent plan V4.7, "Temporal Expressions".

    Reuses the existing ``HassTurnOn``/``HassTurnOff`` intent names (not a
    new intent) so the resulting ``ServiceCallPlan`` is byte-for-byte the
    same one an equivalent plain "mach {name} an/aus" would produce -
    ``engine.py``'s ``_build_match_result`` needs zero changes, its existing
    final ``INTENTS.get(frame.intent)`` branch already handles this. The
    parsed ``TemporalExpression`` is only stashed in
    ``frame.parameters["temporal"]`` for a later execution layer to read -
    per the plan's own scoping ("Zunächst nur parsen und validieren"), this
    parser never delays/schedules anything itself.

    Single-entity only ("das Licht", matching the plan's own examples) - an
    ambiguous or unresolved {name} returns ``None`` with no clarification
    round-trip, same scope-limiting choice ``ComparisonQueryParser``/
    ``ContextFollowupParser`` already made for their own narrower grammars.
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | None:
        slot_lists = {
            "name": WildcardSlotList(name="name"),
            "temporal_kind": _TEMPORAL_KIND_SLOT_LIST,
            "amount": RangeSlotList(name="amount", start=1, stop=59, step=1, type=RangeType.NUMBER),
            "unit": _TEMPORAL_UNIT_SLOT_LIST,
            "relative": _TEMPORAL_RELATIVE_SLOT_LIST,
            "hour": RangeSlotList(name="hour", start=0, stop=23, step=1, type=RangeType.NUMBER),
        }
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
        resolved = resolve_entity(name, context.entities)
        if resolved.status is not ResolveStatus.OK or resolved.entity is None:
            return None  # not found or ambiguous - never guess, no clarification round-trip here
        if resolved.entity.domain not in spec.allowed_domains:
            return None

        temporal = self._build_temporal(result.entities)
        if temporal is None:
            return None

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=name, entity_id=resolved.entity.entity_id, domain=resolved.entity.domain),
            area=None,
            parameters={"temporal": temporal},
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=[resolved.entity])

    @staticmethod
    def _build_temporal(slots: dict) -> TemporalExpression | None:
        kind_slot = slots.get("temporal_kind")
        amount_slot = slots.get("amount")
        unit_slot = slots.get("unit")
        if kind_slot is not None and amount_slot is not None and unit_slot is not None:
            amount = int(amount_slot.value)
            minutes = amount * 60 if unit_slot.value == "hours" else amount
            return TemporalExpression(kind=str(kind_slot.value), minutes=minutes)

        relative_slot = slots.get("relative")
        if relative_slot is not None:
            return TemporalExpression(kind="relative_time", relative=str(relative_slot.value))

        hour_slot = slots.get("hour")
        if hour_slot is not None:
            return TemporalExpression(kind="absolute_time", hour=int(hour_slot.value))

        return None  # structurally unreachable: one of the three branches above always matched


class AreaQueryParser:
    """Wraps the {area} grammar ("wie warm ist es im Wohnzimmer") - the 11th
    separately-compiled hassil grammar, HomeIntent plan V4.9, "Cross-
    Sentence References" (first-turn half: a state query with no entity
    name at all, only a room).

    "warm"/"kalt" are decorative alternation, not a captured slot - same
    precedent query.yaml's own "[hoch|warm|kalt|hell]" already established
    for its {name}-based sentence (grepped empirically before writing this
    grammar: neither word appears anywhere else, so this can't misroute an
    existing sentence). Resolution always looks for the one ``sensor``
    entity in the named room reporting ``device_class == "temperature"`` -
    asking "wie warm"/"wie kalt" both mean the same thing structurally
    ("give me the temperature reading"), not a threshold comparison (that's
    V4.6's separate Comparison mechanism). Reuses the existing
    ``HassGetState`` intent name so the response phrasing
    (service_call.py's ``_speak_query``) and ``QUERY_INTENTS`` wiring stay
    identical to a name-based query - only *how* the target entity is found
    differs.

    Zero or several temperature sensors in the same room is refused rather
    than guessed - same "never guess" rule as every other parser here.
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | None:
        slot_lists = {"area": WildcardSlotList(name="area")}
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        area_slot = result.entities.get("area")
        if area_slot is None:
            return None
        area_name = _strip_locative_prepositions(str(area_slot.value))
        if not area_name:
            return None

        area_resolved = resolve_area_name(area_name, context.entities)
        if area_resolved.status is not AreaResolveStatus.OK:
            return None  # room not found or ambiguous - never guess

        matches = resolve_candidates(
            context.entities,
            Constraints(domain="sensor", area_id=area_resolved.area_id, device_class="temperature"),
        )
        if len(matches) != 1:
            return None  # no single unambiguous temperature sensor in that room - never guess
        entity = matches[0]

        frame = SemanticFrame(
            intent=result.intent.name,
            target=TargetReference(text=area_name, entity_id=entity.entity_id, domain=entity.domain),
            area=AreaReference(text=area_name, area_id=area_resolved.area_id),
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=[entity])


class QueryFollowupParser:
    """Wraps the "und {area}"/"und {level}" grammar ("Und in der Küche?",
    "Und oben?") - the 12th separately-compiled hassil grammar, HomeIntent
    plan V4.9, "Cross-Sentence References" (follow-up half).

    Structurally distinct from every other parser here, same reason
    ``ReferenceParser`` already documents for itself: resolution happens
    against the previous turn's resolved query target, not a freshly spoken
    name, so this parser takes ``last_entities``/``previous_query_command``
    as plain parameters rather than folding them into ``ParseContext``.

    Two branches, dispatched in ``parse()`` on whether the caller
    (``NluEngine.match_query_followup()``) found a ``QueryCommand`` on the
    previous turn (HomeIntent v4.2.1 plan, Phase 8):

    **``HassGetState`` branch** (original, unchanged) - *what* to look for
    (domain + device_class) is never re-spoken, it's carried over from
    ``last_entities[0]`` (the previous turn's single resolved query target).
    Mirrors ``derive_query_type``'s own domain-first/device_class-second
    precedence (nlu/query.py): a light carries over by domain alone (lights
    don't report a device_class), everything else carries over by domain
    *and* device_class - so "Und in der Küche?" after a temperature query
    only matches a temperature sensor in the new room, never some other
    sensor there. Refuses (``None``) unless the new area/floor yields
    *exactly* one candidate - no cardinality concept here, mirrors
    ``HassGetState``'s own always-singular shape.

    **State-query branch** (Phase 8, extended live-bug fix 2026-08-18) -
    continues ``HassStateQuery``/``HassCheckState``/``HassExistsQuery``
    using the previous turn's ``QueryCommand`` (``frame.parameters[
    "query_command"]``, populated by ``StateQueryParser`` since Phase 7)
    instead of ``last_entities[0]``. Generic **delta merge**, not per-
    sentence special cases: each of area/floor, device_class, and state is
    independently optional in this turn's utterance - whichever *is*
    spoken (``_resolve_state_query_delta()``) overrides the matching field,
    whichever is *absent* is carried over verbatim from ``previous``. This
    is what makes "Und im Esszimmer?" (area only), "Und welche Türen sind
    offen?" (device_class only, area carries over), "Und welche sind
    geschlossen?" (state only, domain/device_class/area all carry over),
    and a combined "Und welche Türen sind offen im Esszimmer?" all resolve
    through the same code path instead of three separate ones - see
    ``_resolve_state_query_delta()``'s docstring for the grammar side of
    this. Domain/device_class changes are validated against
    ``QUERY_INTENTS[previous.intent].allowed_domains`` (same check
    ``StateQueryParser`` itself applies) - a device_class that doesn't fit
    the previous intent's domain set is refused, not guessed.

    Re-run through the same ``_QUERY_EXECUTOR`` ``StateQueryParser`` itself
    uses (Regel 6, one shared classifier). Unlike the ``HassGetState``
    branch, a LIST/COUNT/EXISTS follow-up keeps the "empty is a normal
    answer" rule ("Und im Bad?" -> "Keine Fenster sind offen." is a real
    answer, not a miss) - only ``HassCheckState`` (``QueryScope.SINGLE``)
    refuses on 0 or 2+ matches, same "never guess" precedent the
    ``HassGetState`` branch already set.

    {area} resolves against a fresh room lookup (this turn's ``entities``,
    not the remembered one - the whole point is a *new* room); {level}
    ("oben"/"unten") resolves a floor the same way ``QuantifierParser``'s
    own {level} slot does (v2 plan Phase 28 precedent,
    ``resolve_floor_by_level_keyword``) - same as before, a floor-only
    follow-up is never written back into the merged ``QueryTarget`` (it
    has no floor field, only ``area``), so it stays a same-turn-only
    resolution, not carried into a third turn. ``HassGetState`` branch
    keeps using the narrower ``_resolve_area_or_level()`` (no
    device_class/state delta - domain/device_class there come from
    ``last_entities[0]``, not a ``QueryCommand``, so there is no
    ``QUERY_INTENTS`` entry to validate a device_class change against).
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(
        self,
        text: str,
        entities: list[EntitySnapshot],
        last_entities: tuple[EntitySnapshot, ...],
        previous_query_command: QueryCommand | None = None,
        world_model: WorldModel | None = None,
    ) -> ParseResult | None:
        if previous_query_command is not None:
            return self._parse_state_query_followup(text, entities, previous_query_command, world_model)
        return self._parse_get_state_followup(text, entities, last_entities)

    def _resolve_area_or_level(
        self, text: str, entities: list[EntitySnapshot]
    ) -> tuple[str | None, str | None, str | None, str] | None:
        """(area_id, area_name, floor_id, target_text) from the "und
        {area}"/"und {level}" grammar, or ``None`` on any structural or
        resolution miss (unknown/ambiguous room, no single oben/unten
        floor) - never guess. Exactly one of area_id/floor_id is set.
        """
        slot_lists = {"area": WildcardSlotList(name="area"), "level": _LEVEL_SLOT_LIST}
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        area_slot = result.entities.get("area")
        if area_slot is not None:
            area_name = _strip_locative_prepositions(str(area_slot.value))
            if not area_name:
                return None
            area_resolved = resolve_area_name(area_name, entities)
            if area_resolved.status is not AreaResolveStatus.OK:
                return None  # room not found or ambiguous - never guess
            return area_resolved.area_id, area_name, None, area_name

        level_slot = result.entities.get("level")
        if level_slot is None:
            return None
        level_resolved = resolve_floor_by_level_keyword(str(level_slot.value), entities)
        if level_resolved.status is not FloorResolveStatus.OK:
            return None  # no single oben/unten floor among today's entities - never guess
        return None, None, level_resolved.floor_id, str(level_slot.value)

    def _parse_get_state_followup(
        self, text: str, entities: list[EntitySnapshot], last_entities: tuple[EntitySnapshot, ...]
    ) -> ParseResult | None:
        if not last_entities:
            return None
        reference = last_entities[0]
        domain = reference.domain
        device_class = None if domain == "light" else reference.device_class
        if domain != "light" and device_class is None:
            return None  # nothing meaningful to carry over - never guess

        resolved_location = self._resolve_area_or_level(text, entities)
        if resolved_location is None:
            return None
        area_id, area_name, floor_id, target_text = resolved_location

        candidates = resolve_candidates(
            entities, Constraints(domain=domain, area_id=area_id, floor_id=floor_id, device_class=device_class)
        )
        if len(candidates) != 1:
            return None  # no single unambiguous match in the new area/floor - never guess
        entity = candidates[0]

        frame = SemanticFrame(
            intent="HassGetState",
            target=TargetReference(text=target_text, entity_id=entity.entity_id, domain=entity.domain),
            area=AreaReference(text=area_name, area_id=area_id) if area_id is not None else None,
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=[entity])

    def _resolve_state_query_delta(
        self, text: str, entities: list[EntitySnapshot]
    ) -> tuple[str | None, str | None, str | None, str | None, str | None, str] | None:
        """(area_id, area_name, floor_id, device_class_value, state_name,
        target_text) from the delta grammar - "und {area}"/"und {level}"
        (unchanged) plus the new "und welche {device_class} sind {state}"/
        "und welche sind {state}"/"und welche {device_class} sind {state}
        {area}" sentences (query_followup.yaml). Each of area-or-level,
        device_class, and state is independently optional - exactly which
        ones are present depends on which sentence matched, and the caller
        (``_parse_state_query_followup``) carries over whatever is absent
        from the previous turn's ``QueryCommand``. At least one is always
        present, since every sentence in the grammar requires at least one
        content slot - this method never has to guess "nothing changed".
        ``None`` on any structural or resolution miss (unknown/ambiguous
        room, no single oben/unten floor) - never guess.
        """
        slot_lists = {
            "area": WildcardSlotList(name="area"),
            "level": _LEVEL_SLOT_LIST,
            "device_class": _DEVICE_CLASS_SLOT_LIST,
            "state": _STATE_SLOT_LIST,
        }
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        area_id = area_name = floor_id = None
        area_slot = result.entities.get("area")
        if area_slot is not None:
            area_name = _strip_locative_prepositions(str(area_slot.value))
            if not area_name:
                return None
            area_resolved = resolve_area_name(area_name, entities)
            if area_resolved.status is not AreaResolveStatus.OK:
                return None  # room not found or ambiguous - never guess
            area_id = area_resolved.area_id
        else:
            level_slot = result.entities.get("level")
            if level_slot is not None:
                level_resolved = resolve_floor_by_level_keyword(str(level_slot.value), entities)
                if level_resolved.status is not FloorResolveStatus.OK:
                    return None  # no single oben/unten floor - never guess
                floor_id = level_resolved.floor_id
                area_name = str(level_slot.value)

        device_class_slot = result.entities.get("device_class")
        device_class_value = str(device_class_slot.value) if device_class_slot is not None else None

        state_slot = result.entities.get("state")
        state_name = str(state_slot.value) if state_slot is not None else None

        target_text = area_name if area_name is not None else text
        return area_id, area_name, floor_id, device_class_value, state_name, target_text

    def _parse_state_query_followup(
        self,
        text: str,
        entities: list[EntitySnapshot],
        previous: QueryCommand,
        world_model: WorldModel | None = None,
    ) -> ParseResult | None:
        if previous.target.kind is QueryTargetKind.DEVICE:
            resolved_location = self._resolve_area_or_level(text, entities)
            if resolved_location is None:
                return None
            area_id, area_name, _floor_id, _target_text = resolved_location
            return self._parse_device_query_followup(text, area_id, area_name, previous, world_model)

        delta = self._resolve_state_query_delta(text, entities)
        if delta is None:
            return None
        area_id, area_name, floor_id, device_class_value, state_name, target_text = delta

        if device_class_value is not None:
            domain, _, device_class_raw = device_class_value.partition(":")
            device_class = device_class_raw if device_class_raw != "None" else None
            spec = QUERY_INTENTS.get(previous.intent)
            if spec is None or domain not in spec.allowed_domains:
                return None  # never guess outside the intent's own allowed domains
        else:
            domain = previous.target.domain
            device_class = previous.target.device_class

        requested_state = _STATE_NAME_TO_SEMANTIC[state_name] if state_name is not None else previous.filter.state

        # Area/floor mentioned this turn wins; otherwise carry over the
        # previous turn's area verbatim (a floor is never carried forward -
        # QueryTarget has no floor field, same "same-turn-only" precedent
        # the pure "und {level}" sentence already established).
        if area_id is not None or floor_id is not None:
            final_area_id, final_area_name, final_floor_id = area_id, area_name, floor_id
        elif previous.target.area is not None:
            final_area_id = previous.target.area.area_id
            final_area_name = previous.target.area.name
            final_floor_id = None
        else:
            final_area_id = final_area_name = final_floor_id = None

        candidates = resolve_candidates(
            entities,
            Constraints(domain=domain, area_id=final_area_id, floor_id=final_floor_id, device_class=device_class),
        )

        area_snapshot = AreaSnapshot(area_id=final_area_id, name=final_area_name) if final_area_id is not None else None
        new_command = QueryCommand(
            intent=previous.intent,
            scope=previous.scope,
            target=QueryTarget(domain=domain, device_class=device_class, area=area_snapshot),
            filter=QueryFilter(state=requested_state),
        )
        query_result = _QUERY_EXECUTOR.execute(new_command, candidates)
        if query_result.status in (QueryResultStatus.TARGET_NOT_FOUND, QueryResultStatus.AMBIGUOUS):
            return None  # never guess - same refusal precedent as the HassGetState branch above

        matches = list(query_result.entities)
        # SINGLE (HassCheckState) stays a plain singular match, like the
        # HassGetState branch; LIST/COUNT/EXISTS keep StateQueryParser's own
        # "quantifier=all even when empty" precedent so an intentional
        # "Keine Fenster sind offen." doesn't misfire validate_command()'s
        # ambiguity check (see StateQueryParser's class docstring).
        quantifier = None if previous.scope is QueryScope.SINGLE else Quantifier(kind="all")

        frame = SemanticFrame(
            intent=previous.intent,
            target=TargetReference(text=target_text, domain=domain, device_class=device_class),
            area=AreaReference(text=final_area_name, area_id=final_area_id, area_name=final_area_name)
            if final_area_id is not None
            else None,
            quantifier=quantifier,
            parameters={
                "semantic_state": requested_state,
                "count_only": previous.scope is QueryScope.COUNT,
                "device_class": device_class,
                "domain": domain,
                "query_command": new_command,
                "query_result": query_result,
            },
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=matches)

    def _parse_device_query_followup(
        self,
        text: str,
        area_id: str | None,
        area_name: str | None,
        previous: QueryCommand,
        world_model: WorldModel | None,
    ) -> ParseResult | None:
        """Continues a HassDeviceQuery ("Welche Geräte sind im Büro?" -> "Und
        im Keller?") - devices are cross-domain and area-only
        (``QueryTarget`` has no floor field, same gap ``ReasoningEngine``'s
        own ``Constraints`` building has), so a floor-only followup ("Und
        oben?") has nothing to resolve against and is refused rather than
        guessed. ``_respond_device_list`` also assumes an area is always
        present, so ``area_id is None`` must never reach ``QueryExecutor``
        here.
        """
        if area_id is None:
            return None
        area_snapshot = AreaSnapshot(area_id=area_id, name=area_name)
        new_command = QueryCommand(
            intent=previous.intent,
            scope=previous.scope,
            target=QueryTarget(kind=QueryTargetKind.DEVICE, area=area_snapshot),
            filter=QueryFilter(),
        )
        query_result = _QUERY_EXECUTOR.execute(new_command, candidates=[], world_model=world_model)

        frame = SemanticFrame(
            intent=previous.intent,
            target=None,
            area=AreaReference(text=area_name, area_id=area_id, area_name=area_name),
            quantifier=Quantifier(kind="all"),
            parameters={
                "query_command": new_command,
                "query_result": query_result,
            },
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=[])


class CommandFollowupParser:
    """Wraps the "und wieder aus"/"und im {area} auch" command-follow-up
    grammar (``intents/de/command_followup/command_followup.yaml``) - live
    conversation-context bug fix 2026-08-18: "Schalte das Studio ein." ->
    "Und jetzt wieder aus." must resolve to TURN_OFF/Studio, not fail as an
    unrelated fresh sentence.

    Structurally distinct from every other parser here the same way
    ``QueryFollowupParser`` is: resolution happens against the previous
    turn's already-built ``SemanticCommand`` (not a freshly spoken name), so
    this parser takes ``last_command`` as a plain parameter rather than
    folding it into ``ParseContext``. One ``recognize()`` call, then
    dispatch on which of the grammar's two intents matched - never two
    separate ``recognize()`` calls for what is structurally one decision.

    **``HassCommandFollowupInvert``** ("und wieder aus", "mach es wieder
    an") - the target (domain + area + resolved entities) is carried over
    *verbatim* from ``last_command.entities``/``last_command.area``; only
    the intent changes, via the central ``service_call.ACTION_OPPOSITES``
    table. A previous intent with no listed opposite (e.g. ``HassToggle``,
    deliberately absent from that table - its own effect already depends on
    current state, so "the opposite of toggle" has no single fixed answer)
    makes this branch refuse (``None``) rather than guess - falls through to
    the normal "nicht verstanden" response (Regel 4).

    **``HassCommandFollowupSameActionNewArea``** ("und im {area} auch") -
    the *same* intent as ``last_command`` (no inversion), re-targeted at a
    freshly resolved area using the previous command's domain. "auch" here
    signals continuation, not inversion - deliberately a separate grammar
    intent from the "wieder" sentences above so the two are never confused
    (regression Test F: "Und im Schlafzimmer auch." is a *second,
    independent* command, not an inversion of the first).
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(
        self, text: str, entities: list[EntitySnapshot], last_command: SemanticCommand
    ) -> ParseResult | None:
        slot_lists = {"area": WildcardSlotList(name="area")}
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None
        if result.intent.name == "HassCommandFollowupInvert":
            return self._parse_invert(text, last_command)
        if result.intent.name == "HassCommandFollowupSameActionNewArea":
            return self._parse_same_action_new_area(text, entities, result, last_command)
        return None

    def _parse_invert(self, text: str, last_command: SemanticCommand) -> ParseResult | None:
        opposite_intent = ACTION_OPPOSITES.get(last_command.intent)
        if opposite_intent is None:
            return None  # no unique opposite - never guess (Regel 4)
        if not last_command.entities:
            return None
        domain = last_command.entities[0].domain
        area = last_command.area
        frame = SemanticFrame(
            intent=opposite_intent,
            target=TargetReference(text=domain, domain=domain),
            area=AreaReference(text=area.name, area_id=area.area_id) if area is not None else None,
            quantifier=Quantifier(kind="all") if len(last_command.entities) > 1 else None,
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=list(last_command.entities))

    def _parse_same_action_new_area(
        self,
        text: str,
        entities: list[EntitySnapshot],
        result,
        last_command: SemanticCommand,
    ) -> ParseResult | None:
        if not last_command.entities:
            return None
        domain = last_command.entities[0].domain

        area_slot = result.entities.get("area")
        if area_slot is None:
            return None
        area_name = _strip_locative_prepositions(str(area_slot.value))
        if not area_name:
            return None
        area_resolved = resolve_area_name(area_name, entities)
        if area_resolved.status is not AreaResolveStatus.OK:
            return None  # unknown or ambiguous room - never guess

        candidates = resolve_candidates(entities, Constraints(domain=domain, area_id=area_resolved.area_id))
        if not candidates:
            return None  # nothing of the previous command's domain in the new area - never guess

        frame = SemanticFrame(
            intent=last_command.intent,
            target=TargetReference(text=domain, domain=domain),
            area=AreaReference(text=area_name, area_id=area_resolved.area_id),
            quantifier=Quantifier(kind="all") if len(candidates) > 1 else None,
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=candidates)


# Custom, non-HA-core intent names for the "die anderen" complement grammar
# (HomeIntent plan V3.5) -> the real intent whose INTENTS spec/response
# resolve() should use. Same naming precedent as HassReferenceOther/
# HassSetPercentage.
_OTHERS_INTENT_MAP = {"HassTurnOnOthers": "HassTurnOn", "HassTurnOffOthers": "HassTurnOff"}


class ReferenceParser:
    """Wraps the reference/pronoun grammar ("Mach es aus.", "Mach die auch
    an.", "Die Rollläden dort runter.", "Die andere.") - the 8th separately-
    compiled hassil grammar (v2 plan Phase 27, "Pronomen und Referenzen").

    Structurally distinct from every other parser here: resolution happens
    against the previous turn's ``ConversationContext``, not against a freshly
    spoken name, so this parser takes the context pieces it needs
    (``last_entities``/``last_area``) as plain parameters rather than folding
    them into ``ParseContext`` - it takes primitives rather than a
    ``ConversationContext`` object itself, same reason ``ContextFollowupParser``
    does: keeps this module decoupled from ``nlu/context.py``. The
    area-anchored ``{domain}`` sentences ("... dort hoch/runter") still need
    the *current* turn's full ``entities`` (not ``last_entities``) to find every
    cover in the remembered area - the previous turn only resolved one.

    Three resolution strategies, one grammar (no keyword router needed in
    engine.py - like ContextFollowupParser, the caller decides *when* to try
    this parser via ``NluEngine.match_reference()``, not *whether the text
    could collide* - verified empirically against hassil==3.11.0: no
    collision between these fixed pronoun sentences and any other grammar's
    own sentences):

    1. Plain pronoun ("es"/"die auch") - resolved directly against
       ``last_entities``. Any count >= 1 is accepted for the 5 basic
       INTENTS (turn on/off), but "es heller/dunkler" keeps
       ``match_followup()``'s single-light-only scope (same reason: those
       response lambdas only ever read ``entities[0]``).
    2. Area-anchored domain reference ("{domain} dort hoch/runter") -
       resolved against a *fresh* ``entities`` scan filtered by
       ``last_area.area_id``, reusing ``constraint_resolver.resolve_candidates()``
       exactly like ``QuantifierParser`` does.
    3. Unresolvable relative reference ("die andere"/"die daneben") -
       recognized by a custom, non-HA-core intent name (``HassReferenceOther``,
       same precedent ``HassSetPercentage`` already established) but never
       resolved: returns ``AmbiguousReference`` instead of a ``ParseResult``,
       since there is no candidate list or spatial model to pick from
       without guessing.
    4. Complement reference ("die anderen auch an" - HomeIntent plan V3.5) -
       recognized by custom intent names ``HassTurnOnOthers``/
       ``HassTurnOffOthers`` (same precedent as strategy 3), mapped back to
       the real ``HassTurnOn``/``HassTurnOff`` intent via
       ``_OTHERS_INTENT_MAP``. Unlike strategy 3 this *is* resolved, because
       "the others" has a deterministic candidate universe here: every entity
       of ``last_entities``' domain within ``last_area`` (same anchor
       strategy 2 requires - without a remembered area there is no bounded
       set to take "others" from, so it returns ``None`` rather than
       guessing at every matching entity in the whole house), minus the
       entities already in ``last_entities``. Mixed-domain ``last_entities``
       also returns ``None`` - "the others" is undefined without one target
       domain to complement against.

    Whenever strategy 1, 2 or 4 resolves to more than one entity,
    ``frame.quantifier`` is set to ``Quantifier(kind="all")`` - required so
    ``validate_command()``'s check #3 (a non-quantifier command resolving to
    2+ entities is treated as an unresolved ambiguity) doesn't misfire on a
    deliberate multi-entity reference.
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(
        self,
        text: str,
        entities: list[EntitySnapshot],
        last_entities: tuple[EntitySnapshot, ...],
        last_area: AreaSnapshot | None,
    ) -> ParseResult | AmbiguousReference | None:
        slot_lists = {"domain": _DOMAIN_SLOT_LIST}
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        if result.intent.name == "HassReferenceOther":
            return AmbiguousReference(source_text=text)

        real_intent_name = _OTHERS_INTENT_MAP.get(result.intent.name)
        if real_intent_name is not None:
            return self._resolve_others(real_intent_name, entities, last_entities, last_area, text)

        domain_slot = result.entities.get("domain")
        if domain_slot is not None:
            return self._resolve_area_anchored(result.intent.name, str(domain_slot.value), entities, last_area, text)

        return self._resolve_pronoun(result.intent.name, last_entities, text)

    @staticmethod
    def _resolve_pronoun(intent_name: str, last_entities: tuple[EntitySnapshot, ...], text: str) -> ParseResult | None:
        if not last_entities:
            return None

        parameters: dict[str, object] = {}
        if intent_name in ("HassLightBrighten", "HassLightDim"):
            # Same single-light scope constraint as match_followup() - the
            # LIGHT_EXTENDED_INTENTS response lambdas only read entities[0].
            lights = [e for e in last_entities if e.domain == "light"]
            if len(lights) != 1:
                return None
            matched = lights
            parameters = {"step_percent": _DEFAULT_DIMMING_STEP_PERCENT}
        else:
            if INTENTS.get(intent_name) is None:
                return None
            matched = list(last_entities)

        frame = SemanticFrame(
            intent=intent_name,
            target=TargetReference(
                text=text,
                entity_id=matched[0].entity_id if len(matched) == 1 else None,
                domain=matched[0].domain,
            ),
            area=None,
            quantifier=Quantifier(kind="all") if len(matched) > 1 else None,
            parameters=parameters,
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=matched)

    @staticmethod
    def _resolve_area_anchored(
        intent_name: str,
        domain: str,
        entities: list[EntitySnapshot],
        last_area: AreaSnapshot | None,
        text: str,
    ) -> ParseResult | None:
        if last_area is None:
            return None  # no remembered area to resolve "dort" against - never guess

        spec = INTENTS.get(intent_name)
        if spec is None or domain not in spec.allowed_domains:
            return None

        matches = resolve_candidates(entities, Constraints(domain=domain, area_id=last_area.area_id))
        if not matches:
            return None

        frame = SemanticFrame(
            intent=intent_name,
            target=TargetReference(text=domain, domain=domain),
            area=AreaReference(text=last_area.name, area_id=last_area.area_id),
            quantifier=Quantifier(kind="all") if len(matches) > 1 else None,
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=matches)

    @staticmethod
    def _resolve_others(
        intent_name: str,
        entities: list[EntitySnapshot],
        last_entities: tuple[EntitySnapshot, ...],
        last_area: AreaSnapshot | None,
        text: str,
    ) -> ParseResult | None:
        if not last_entities or last_area is None:
            return None  # no bounded set ("last domain" x "last area") to take "others" from - never guess

        domains = {e.domain for e in last_entities}
        if len(domains) != 1:
            return None  # "the others" is undefined without one target domain to complement against
        domain = domains.pop()

        spec = INTENTS.get(intent_name)
        if spec is None or domain not in spec.allowed_domains:
            return None

        already_mentioned = {e.entity_id for e in last_entities}
        others = [
            e
            for e in resolve_candidates(entities, Constraints(domain=domain, area_id=last_area.area_id))
            if e.entity_id not in already_mentioned
        ]
        if not others:
            return None

        frame = SemanticFrame(
            intent=intent_name,
            target=TargetReference(text=domain, domain=domain),
            area=AreaReference(text=last_area.name, area_id=last_area.area_id),
            quantifier=Quantifier(kind="all") if len(others) > 1 else None,
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=others)


# _DEVICE_CLASS_SLOT_LIST/_STATE_SLOT_LIST/_STATE_ADJ_SLOT_LIST now live in
# nlu/lexicon.py (V6.3, "Semantic Lexicon") - imported above. Predicate-
# position {state} values are the SemanticState member *name* (a plain
# string, cast back to the enum member via _STATE_NAME_TO_SEMANTIC below).
_STATE_NAME_TO_SEMANTIC: dict[str, SemanticState] = {
    "OPEN": SemanticState.OPEN,
    "CLOSED": SemanticState.CLOSED,
    "ON": SemanticState.ON,
    "OFF": SemanticState.OFF,
}

# Shared, stateless (HomeIntent v4.2.1 plan, Phase 7): StateQueryParser now
# runs its own candidate filtering/ambiguity classification through the same
# QueryExecutor a future V5 consumer would use, instead of a private ad hoc
# list comprehension - see StateQueryParser's own docstring for the "why now,
# but response text unchanged" scope decision.
_QUERY_EXECUTOR = QueryExecutor()


class StateQueryParser:
    """Wraps the {device_class}/{state}/{state_adj}/{name}/{area} grammar
    ("welche Fenster sind offen", "ist das Fenster im Schlafzimmer
    geöffnet", "gibt es offene Fenster") - the 13th separately-compiled
    hassil grammar, HomeIntent V4.2, "Semantic Query & State Resolution".

    Handles all three of its grammar's intents (``HassStateQuery`` - plural
    list/count, ``HassCheckState`` - singular boolean, ``HassExistsQuery`` -
    existence) in one class, dispatching on ``result.intent.name`` - same
    "one parser per grammar file" shape ``ComparisonQueryParser`` already
    established for its own single-grammar/multi-branch domain split.

    Reuses ``resolve_area_scored``/``constraint_resolver.resolve_candidates()``/
    ``resolve_entity_scored`` verbatim (Regel 6 - no parallel search system)
    and ``matches_semantic_state`` (nlu/semantic_state.py) to filter by the
    requested state - live ``EntitySnapshot.state``, never cached (Regel 5).

    This is the **one deliberate exception** to the codebase-wide "a multi-
    entity parser never returns an empty ``resolved_entities`` list" rule
    every other parser here follows: ``HassStateQuery``/``HassExistsQuery``
    with zero matches ("0 Fenster offen") is itself a valid, correct answer
    (V4.2's core requirement), not a miss - unlike ``ComparisonQueryParser``
    (which returns ``None`` on an empty match set), these two always return
    a ``ParseResult``, with ``frame.quantifier`` set to
    ``Quantifier(kind="all")`` even when ``resolved_entities`` is empty, so
    ``validate_command()``'s check #3 doesn't misfire. Do not "fix" this
    back to returning ``None`` on empty - see ``QueryIntentSpec.allows_empty``'s
    docstring (service_call.py) for the validator-side half of this design.

    ``HassCheckState`` (singular expectation) is the exception to the
    exception: an unresolved or ambiguous {name} is refused (``None``, no
    clarification round-trip) - same "never guess" scope-limiting precedent
    ``ComparisonQueryParser``/``AreaQueryParser`` already set for their own
    ambiguity cases, rather than extending ``resolve_clarification()``'s
    scope to cover query intents too.

    HomeIntent v4.2.1 plan, Phase 7 ("non-destructive migration"): each
    ``_parse_*`` method below now builds a ``nlu.query_command.QueryCommand``
    and runs its candidate list through the shared ``QueryExecutor``
    (``_QUERY_EXECUTOR``) instead of a private ad hoc
    ``matches_semantic_state`` list comprehension - the exact same filtering
    rule, just consolidated into the one class a future V5 caller would also
    use (Section 12). The resulting ``QueryCommand`` **and** the full
    ``QueryResult`` (status included, not just ``.entities``) are stashed in
    ``frame.parameters["query_command"]``/``frame.parameters["query_result"]``
    (WorldModelQuery wave) - ``engine.py::_build_match_result`` reads
    ``"query_result"`` and, when present, generates the response via
    ``nlu.response_generator.ResponseGenerator`` instead of
    ``service_call.py``'s ``QUERY_INTENTS`` response lambdas (which are now
    unreachable dead code for these three intents, kept only because
    ``QueryIntentSpec.response`` is a required field).
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(self, text: str, context: ParseContext) -> ParseResult | None:
        slot_lists = {
            "device_class": _DEVICE_CLASS_SLOT_LIST,
            "state": _STATE_SLOT_LIST,
            "state_adj": _STATE_ADJ_SLOT_LIST,
            "name": WildcardSlotList(name="name"),
            "area": WildcardSlotList(name="area"),
        }
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        spec = QUERY_INTENTS.get(result.intent.name)
        if spec is None:
            return None

        if result.intent.name == "HassCheckState":
            return self._parse_check_state(text, result.entities, context, spec)
        if result.intent.name == "HassExistsQuery":
            return self._parse_exists_query(text, result.entities, context, spec)
        if result.intent.name == "HassStateQuery":
            return self._parse_state_query(text, result.entities, context, spec)
        if result.intent.name == "HassDeviceQuery":
            return self._parse_device_query(text, result.entities, context)
        return None

    @staticmethod
    def _resolve_area(slots: dict, entities: list[EntitySnapshot]) -> tuple[str | None, str | None] | None:
        """(area_id, area_name) from the {area} slot, or (None, None) if no
        {area} word was captured at all. Returns ``None`` (not a tuple, so
        callers can distinguish "no area mentioned" from "area mentioned but
        unresolvable") when an {area} word *was* captured but doesn't
        resolve to exactly one known room - never guess.
        """
        area_slot = slots.get("area")
        if area_slot is None:
            return None, None
        area_text = _strip_locative_prepositions(str(area_slot.value))
        if not area_text:
            return None, None
        area_resolved = resolve_area_scored(area_text, entities)
        if area_resolved.status is not AreaResolutionStatus.RESOLVED or area_resolved.area is None:
            return None  # named but not a known/unambiguous room - never guess
        return area_resolved.area.area_id, area_resolved.area.name

    @staticmethod
    def _device_class_candidates(
        device_class_value: str, entities: list[EntitySnapshot], area_id: str | None
    ) -> tuple[str, str | None, list[EntitySnapshot]]:
        """Splits the "domain:device_class" composite slot value and returns
        the matching entities alongside the parsed (domain, device_class) -
        the caller needs those two separately for ``TargetReference``/
        ``frame.parameters`` regardless of the candidate list itself."""
        domain, _, device_class_raw = device_class_value.partition(":")
        device_class = device_class_raw if device_class_raw != "None" else None
        candidates = resolve_candidates(entities, Constraints(domain=domain, area_id=area_id, device_class=device_class))
        return domain, device_class, candidates

    def _parse_state_query(self, text: str, slots: dict, context: ParseContext, spec) -> ParseResult | None:
        device_class_slot = slots.get("device_class")
        state_slot = slots.get("state")
        if device_class_slot is None:
            return None

        resolved_area = self._resolve_area(slots, context.entities)
        if resolved_area is None:
            return None
        area_id, area_name = resolved_area

        device_class_value = str(device_class_slot.value)
        domain, device_class, candidates = self._device_class_candidates(device_class_value, context.entities, area_id)
        if domain not in spec.allowed_domains:
            return None

        requested_state = _STATE_NAME_TO_SEMANTIC[str(state_slot.value)] if state_slot is not None else None
        count_only = bool(re.search(r"\bwie viele\b", text, re.IGNORECASE))
        area_snapshot = AreaSnapshot(area_id=area_id, name=area_name) if area_id is not None else None
        query_command = QueryCommand(
            intent="HassStateQuery",
            scope=QueryScope.COUNT if count_only else QueryScope.LIST,
            target=QueryTarget(domain=domain, device_class=device_class, area=area_snapshot),
            filter=QueryFilter(state=requested_state),
        )
        query_result = _QUERY_EXECUTOR.execute(query_command, candidates)
        matches = list(query_result.entities)

        frame = SemanticFrame(
            intent="HassStateQuery",
            target=TargetReference(text=device_class_value, domain=domain, device_class=device_class),
            area=AreaReference(text=area_name, area_id=area_id, area_name=area_name) if area_id is not None else None,
            quantifier=Quantifier(kind="all"),
            parameters={
                "semantic_state": requested_state,
                "count_only": count_only,
                "device_class": device_class,
                "domain": domain,
                "query_command": query_command,
                "query_result": query_result,
            },
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=matches)

    def _parse_exists_query(self, text: str, slots: dict, context: ParseContext, spec) -> ParseResult | None:
        device_class_slot = slots.get("device_class")
        if device_class_slot is None:
            return None

        resolved_area = self._resolve_area(slots, context.entities)
        if resolved_area is None:
            return None
        area_id, area_name = resolved_area

        device_class_value = str(device_class_slot.value)
        domain, device_class, candidates = self._device_class_candidates(device_class_value, context.entities, area_id)
        if domain not in spec.allowed_domains:
            return None

        # {state_adj} is the "gibt es offene Fenster" attributive-word
        # branch; {state} is the "ist ein Fenster offen" predicate-word
        # branch (spec gap #4) - only one of the two is ever present for a
        # given sentence, since they come from disjoint templates.
        state_slot = slots.get("state_adj") or slots.get("state")
        requested_state = None
        if state_slot is not None:
            requested_state = _STATE_NAME_TO_SEMANTIC[str(state_slot.value)]

        area_snapshot = AreaSnapshot(area_id=area_id, name=area_name) if area_id is not None else None
        query_command = QueryCommand(
            intent="HassExistsQuery",
            scope=QueryScope.EXISTS,
            target=QueryTarget(domain=domain, device_class=device_class, area=area_snapshot),
            filter=QueryFilter(state=requested_state),
        )
        query_result = _QUERY_EXECUTOR.execute(query_command, candidates)
        matches = list(query_result.entities)

        frame = SemanticFrame(
            intent="HassExistsQuery",
            target=TargetReference(text=device_class_value, domain=domain, device_class=device_class),
            area=AreaReference(text=area_name, area_id=area_id, area_name=area_name) if area_id is not None else None,
            quantifier=Quantifier(kind="all"),
            parameters={
                "semantic_state": requested_state,
                "device_class": device_class,
                "domain": domain,
                "query_command": query_command,
                "query_result": query_result,
            },
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=matches)

    def _parse_check_state(self, text: str, slots: dict, context: ParseContext, spec) -> ParseResult | None:
        name_slot = slots.get("name")
        state_slot = slots.get("state")
        if name_slot is None or state_slot is None:
            return None

        resolved_area = self._resolve_area(slots, context.entities)
        if resolved_area is None:
            return None
        area_id, area_name = resolved_area

        name = _strip_locative_prepositions(str(name_slot.value))
        resolved = resolve_entity_scored(name, context.entities, area_id=area_id, index=context.index)
        if resolved.status is not ResolutionStatus.RESOLVED or resolved.entity is None:
            return None  # not found or ambiguous - never guess, no clarification round-trip (see class docstring)
        if resolved.entity.domain not in spec.allowed_domains:
            return None

        requested_state = _STATE_NAME_TO_SEMANTIC[str(state_slot.value)]
        area_snapshot = AreaSnapshot(area_id=area_id, name=area_name) if area_id is not None else None
        # device_class is inert here (QueryExecutor.SINGLE with a pre-resolved
        # entity_id never looks at it - only entity_id decides membership),
        # but carrying it over gives Phase 8's QueryFollowupParser something
        # to re-scope by when a later "Und im Bad?" continues this exact
        # HassCheckState with a new area (this entity's own device_class,
        # e.g. "window", not just its bare domain, e.g. "binary_sensor").
        query_command = QueryCommand(
            intent="HassCheckState",
            scope=QueryScope.SINGLE,
            target=QueryTarget(
                domain=resolved.entity.domain,
                device_class=resolved.entity.device_class,
                area=area_snapshot,
                entity_id=resolved.entity.entity_id,
            ),
            filter=QueryFilter(state=requested_state),
        )
        # resolve_entity_scored already did the ambiguity check (Regel 6) -
        # QueryExecutor.SINGLE with a pre-resolved entity_id only confirms
        # membership, it never re-decides cardinality here.
        query_result = _QUERY_EXECUTOR.execute(query_command, [resolved.entity])
        matches = list(query_result.entities)

        frame = SemanticFrame(
            intent="HassCheckState",
            target=TargetReference(text=name, entity_id=resolved.entity.entity_id, domain=resolved.entity.domain),
            area=AreaReference(text=area_name, area_id=area_id, area_name=area_name) if area_id is not None else None,
            parameters={
                "semantic_state": requested_state,
                "query_command": query_command,
                "query_result": query_result,
            },
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=matches)

    def _parse_device_query(self, text: str, slots: dict, context: ParseContext) -> ParseResult | None:
        """HassDeviceQuery ("welche Geräte sind im Büro?") - devices are
        cross-domain, so this answers from the WorldModel's device list
        (``QueryExecutor._execute_device``) instead of an entity/state
        filter. No {area} resolving to exactly one known room -> ``None``,
        same "never guess" precedent every other ``_parse_*`` method here
        follows (no "alle Geräte im Haus" fallback).

        Follow-up wave, Phase 4: an optional {state} slot ("Welche Geräte
        sind eingeschaltet im Büro?") narrows the device list further -
        ``QueryExecutor._execute_device`` applies the "at least 1 entity
        matches" aggregation rule, this method only reads and forwards the
        slot, same division of labor as every other ``QueryFilter.state``
        caller here.
        """
        resolved_area = self._resolve_area(slots, context.entities)
        if resolved_area is None:
            return None
        area_id, area_name = resolved_area
        if area_id is None:
            return None

        state_slot = slots.get("state")
        requested_state = _STATE_NAME_TO_SEMANTIC[str(state_slot.value)] if state_slot is not None else None

        area_snapshot = AreaSnapshot(area_id=area_id, name=area_name)
        query_command = QueryCommand(
            intent="HassDeviceQuery",
            scope=QueryScope.LIST,
            target=QueryTarget(kind=QueryTargetKind.DEVICE, area=area_snapshot),
            filter=QueryFilter(state=requested_state),
        )
        query_result = _QUERY_EXECUTOR.execute(query_command, candidates=[], world_model=context.world_model)

        frame = SemanticFrame(
            intent="HassDeviceQuery",
            target=None,
            area=AreaReference(text=area_name, area_id=area_id, area_name=area_name),
            quantifier=Quantifier(kind="all"),
            parameters={
                "query_command": query_command,
                "query_result": query_result,
            },
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=[])


# --- V5.29 "Automation Query" ------------------------------------------------


class AutomationQueryParser:
    """Wraps the {name}/{state} grammar ("welche Automationen gibt es",
    "was schaltet das Küchenlicht", "warum ist das Küchenlicht an") -
    HomeIntent V5 Teil 9/10, V5.29 "Automation Query", the 16th separately-
    compiled hassil grammar.

    Unlike every other query parser here, its ``QueryResult`` is built from
    ``automations.yaml``/the metadata sidecar (``AutomationSummary``), not
    live entity state - data this class has no way to fetch itself (``nlu``-
    adjacent parsers stay hass-free, same boundary ``StateQueryParser``
    already documents). So ``automations`` is an explicit parameter to
    ``parse()``, supplied by the caller, rather than folded into
    ``ParseContext`` like ``world_model`` - ``ParseContext`` otherwise holds
    only cheap, always-available per-turn data every parser can rely on;
    this one field would need an async file read on every single turn to
    keep that promise, which is exactly the per-turn I/O cost this design
    avoids (see ``engine.py``'s ``_AUTOMATION_QUERY_RE`` pre-check, mirroring
    ``match_automation()``'s own ``_AUTOMATION_TRIGGER_RE`` gate).

    No {area}/{device_class} slots - see this grammar's own YAML docstring
    for why area-scoping automations is out of scope. An unresolved or
    ambiguous {name} is refused (``None``, no clarification round-trip),
    same "never guess" precedent ``StateQueryParser._parse_check_state``
    already sets for its own singular {name} resolution.
    """

    def __init__(self, intents: Intents) -> None:
        self._intents = intents

    def parse(
        self,
        text: str,
        context: ParseContext,
        automations: tuple[AutomationSummary, ...],
    ) -> ParseResult | None:
        slot_lists = {
            "state": _STATE_SLOT_LIST,
            "name": WildcardSlotList(name="name"),
        }
        result = recognize(text, self._intents, slot_lists=slot_lists, language="de")
        if result is None or result.intent is None:
            return None

        if result.intent.name == "HassAutomationQuery":
            return self._parse_query(text, result.entities, context, automations, causal=False)
        if result.intent.name == "HassAutomationWhyQuery":
            return self._parse_query(text, result.entities, context, automations, causal=True)
        return None

    @staticmethod
    def _parse_query(
        text: str,
        slots: dict,
        context: ParseContext,
        automations: tuple[AutomationSummary, ...],
        causal: bool,
    ) -> ParseResult | None:
        intent_name = "HassAutomationWhyQuery" if causal else "HassAutomationQuery"
        name_slot = slots.get("name")

        if name_slot is None:
            # "welche Automationen gibt es" - no entity filter, list every
            # automation the caller read.
            query_command = QueryCommand(
                intent=intent_name,
                scope=QueryScope.LIST,
                target=QueryTarget(kind=QueryTargetKind.AUTOMATION),
                filter=QueryFilter(),
            )
            query_result = _QUERY_EXECUTOR.execute(query_command, candidates=[], automations=automations)
            frame = SemanticFrame(
                intent=intent_name,
                target=None,
                area=None,
                parameters={"query_command": query_command, "query_result": query_result},
                source_text=text,
            )
            return ParseResult(frame=frame, resolved_entities=[])

        name = _strip_locative_prepositions(str(name_slot.value))
        resolved = resolve_entity_scored(name, context.entities, index=context.index)
        if resolved.status is not ResolutionStatus.RESOLVED or resolved.entity is None:
            return None  # not found or ambiguous - never guess, no clarification round-trip

        query_command = QueryCommand(
            intent=intent_name,
            scope=QueryScope.LIST,
            target=QueryTarget(
                domain=resolved.entity.domain,
                device_class=resolved.entity.device_class,
                entity_id=resolved.entity.entity_id,
                kind=QueryTargetKind.AUTOMATION,
            ),
            filter=QueryFilter(),
        )
        query_result = _QUERY_EXECUTOR.execute(
            query_command, candidates=[resolved.entity], automations=automations
        )

        frame = SemanticFrame(
            intent=intent_name,
            target=TargetReference(text=name, entity_id=resolved.entity.entity_id, domain=resolved.entity.domain),
            area=None,
            parameters={"query_command": query_command, "query_result": query_result},
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=list(query_result.entities))
