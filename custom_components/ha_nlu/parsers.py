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

from hassil import Intents, RangeSlotList, RangeType, TextSlotList, WildcardSlotList, recognize

from .areas import AreaResolveStatus, AreaSnapshot, resolve_area_name
from .entities import EntitySnapshot, ResolveStatus, resolve_entities_by_domain, resolve_entity
from .floors import FloorResolveStatus, resolve_floor_by_level_keyword, resolve_floor_name
from .nlu.frame import AreaReference, Comparison, Quantifier, SemanticFrame, TargetReference, TemporalExpression
from .nlu.parser import AmbiguousReference, ClarificationRequest, ParseContext, ParseResult
from .service_call import (
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


# German word -> canonical HA domain, including the "Rolladen" (one l)
# misspelling seen in real user speech.
#
# Plural forms are listed *before* their singular counterpart wherever the
# singular is a literal text prefix of the plural (Licht/Lichter, Lampe/
# Lampen, Steckdose/Steckdosen, Rollo/Rollos, Ventilator/Ventilatoren): hassil
# matches TextSlotList values in declaration order and doesn't require a
# trailing word boundary, so with the singular listed first "Lichter" would
# match as "Licht" + a leftover "er" that silently gets swallowed by the
# {area} wildcard in the same sentence - the bug that broke the {level}
# ("oben"/"unten") sentences in Phase 28 until this reorder.
_DOMAIN_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("Lichter", "light"), ("Licht", "light"), ("Lampen", "light"), ("Lampe", "light"),
        ("Schalter", "switch"), ("Steckdosen", "switch"), ("Steckdose", "switch"),
        ("Rollladen", "cover"), ("Rollläden", "cover"), ("Rolladen", "cover"), ("Rolläden", "cover"),
        ("Rollos", "cover"), ("Rollo", "cover"),
        ("Ventilatoren", "fan"), ("Ventilator", "fan"),
    ],
    name="domain",
)

# Maps straight to "all"/"both" (rather than the raw German word) so
# QuantifierParser can apply the "beide" == exactly 2 hits rule directly.
# "nur" (v2 plan Phase 29, "Natural Quantifiers") also maps to "all" - "nur
# die Wohnzimmerlampen" restricts to a domain/area filter exactly like
# "alle", it just doesn't additionally claim "every matching light in the
# house" the way a bare "alle" does; the engine can't tell the two apart
# once the filter is applied, so there's no separate "only" kind.
_QUANTIFIER_SLOT_LIST = TextSlotList.from_tuples(
    [("alle", "all"), ("beide", "both"), ("beiden", "both"), ("beider", "both"), ("nur", "all")],
    name="quantifier",
)

# "zwei".."zehn" (v2 plan Phase 29) generalizes "beide"'s exact-count rule
# ("beide" == exactly 2) to arbitrary N ("die drei Lichter" == exactly 3).
# Same fixed, closed-vocabulary pattern as the slot lists above - string
# values (cast to int in QuantifierParser.parse()), same precedent
# _COLOR_TEMP_SLOT_LIST already established.
_COUNT_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("zwei", "2"), ("drei", "3"), ("vier", "4"), ("fünf", "5"),
        ("sechs", "6"), ("sieben", "7"), ("acht", "8"), ("neun", "9"), ("zehn", "10"),
    ],
    name="count",
)

# "oben"/"unten" (v2 plan Phase 28, "Hierarchische Orte") - a fixed, closed
# vocabulary like domain/quantifier above, not a {area}-style wildcard: these
# words never take a preposition ("mach alle Lichter oben an", not "... im
# oben an"), so they get their own slot/sentence shape rather than being
# folded into the {area} grammar.
_LEVEL_SLOT_LIST = TextSlotList.from_tuples(
    [("oben", "up"), ("unten", "down")],
    name="level",
)

# German colour words -> HA's native `color_name` service parameter (CSS
# colour names, so HA itself validates/converts them - not RGB triples
# invented here). "Basis-Set" per user decision (v2 plan Phase 14).
_COLOR_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("rot", "red"),
        ("grün", "green"),
        ("blau", "blue"),
        ("gelb", "yellow"),
        ("orange", "orange"),
        ("lila", "purple"),
        ("violett", "purple"),
        ("weiß", "white"),
        ("pink", "pink"),
        ("rosa", "pink"),
        ("türkis", "turquoise"),
        ("cyan", "cyan"),
    ],
    name="color",
)

# String values (cast to int by LightExtendedParser), same pattern as the
# domain/quantifier slot lists above - standard lighting-industry Kelvin
# reference values, not a UX decision requiring user input.
_COLOR_TEMP_SLOT_LIST = TextSlotList.from_tuples(
    [("warmweiß", "2700"), ("kaltweiß", "6500")],
    name="color_temp",
)

# User decision (AskUserQuestion, v2 plan Phase 14): "heller"/"dunkler"
# without an explicit {percent} slot default to 10% per command.
_DEFAULT_DIMMING_STEP_PERCENT = 10

# "mindestens"/"höchstens"/"nicht höher als"/"über"/"unter" (HomeIntent plan
# V4.6, "Comparisons") -> Comparison.operator. "nicht höher als" is a
# multi-word text key - hassil's TextSlotList.from_tuples supports this
# (empirically verified against hassil==3.11.0 before this list was written,
# same discipline as _COLOR_TEMP_SLOT_LIST/_DOMAIN_SLOT_LIST). Both
# "höchstens" and "nicht höher als" map to "lte" - two spoken phrasings, one
# operator, same precedent _QUANTIFIER_SLOT_LIST's "nur"->"all" already set.
_COMPARATOR_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("mindestens", "gte"),
        ("höchstens", "lte"),
        ("nicht höher als", "lte"),
        ("über", "gt"),
        ("unter", "lt"),
    ],
    name="comparator",
)

# Dedicated {domain} vocabulary for ComparisonQueryParser's grammar only -
# not merged into _DOMAIN_SLOT_LIST (shared by QuantifierParser/
# ReferenceParser for every other command), since "Heizung"/"Raum" as
# synonyms for the climate domain only make sense in a comparison-query
# context ("welche Räume sind unter 20 Grad") and adding them to the shared
# list would silently enable "mach alle Räume an" etc. elsewhere - out of
# V4.6's scope. Plural before singular, same reordering reason
# _DOMAIN_SLOT_LIST's docstring documents.
_COMPARISON_DOMAIN_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("Lichter", "light"), ("Licht", "light"), ("Lampen", "light"), ("Lampe", "light"),
        ("Rollläden", "cover"), ("Rollladen", "cover"), ("Rolladen", "cover"), ("Rolläden", "cover"),
        ("Rollos", "cover"), ("Rollo", "cover"),
        ("Heizungen", "climate"), ("Heizung", "climate"),
        ("Thermostate", "climate"), ("Thermostat", "climate"),
        ("Räume", "climate"), ("Raum", "climate"),
    ],
    name="domain",
)

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

        matches = resolve_entities_by_domain(domain, context.entities, area_id=area_id, floor_id=floor_id)

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

        candidates = resolve_entities_by_domain(domain, context.entities, area_id=area_id, floor_id=floor_id)
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


# "in"/"für" (HomeIntent plan V4.7, "Temporal Expressions") -> which of the
# two numeric temporal kinds a sentence expresses. Both share the same
# {amount}/{unit} slots ("in fünf Minuten" vs. "für eine Stunde" only differ
# in this one preposition), so capturing it as its own closed-vocabulary slot
# - rather than duplicating the sentence per kind - avoids the YAML
# combinatorics V4.1's own filler-word decision already argued against.
_TEMPORAL_KIND_SLOT_LIST = TextSlotList.from_tuples([("in", "delay"), ("für", "duration")], name="temporal_kind")

# "Minute(n)"/"Stunde(n)" -> TemporalParser converts to minutes uniformly
# (Stunden * 60) rather than storing the raw unit, so every consumer of
# TemporalExpression.minutes only ever has to deal with one unit.
_TEMPORAL_UNIT_SLOT_LIST = TextSlotList.from_tuples(
    [("Minuten", "minutes"), ("Minute", "minutes"), ("Stunden", "hours"), ("Stunde", "hours")],
    name="unit",
)

# "morgen früh"/"heute Abend" (the plan's own two examples) plus their
# "heute früh"/"morgen Abend" mirror images - the 2x2 cross product of the
# exact two day-words and two day-part-words the plan text gives, nothing
# beyond that invented. Multi-word TextSlotList keys, same as
# _COMPARATOR_SLOT_LIST's "nicht höher als" (verified there already).
_TEMPORAL_RELATIVE_SLOT_LIST = TextSlotList.from_tuples(
    [
        ("morgen früh", "tomorrow_morning"),
        ("morgen abend", "tomorrow_evening"),
        ("heute abend", "today_evening"),
        ("heute früh", "today_morning"),
    ],
    name="relative",
)


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
       ``last_area.area_id``, reusing ``resolve_entities_by_domain`` exactly
       like ``QuantifierParser`` does.
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

        matches = resolve_entities_by_domain(domain, entities, area_id=last_area.area_id)
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
            for e in resolve_entities_by_domain(domain, entities, area_id=last_area.area_id)
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
