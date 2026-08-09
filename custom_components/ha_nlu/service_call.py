"""Intent -> Home Assistant service-call mapping.

Domain/service pairs mirror the already-verified control logic in
xiaozhi_entity_mcp's tool handlers (turn_on -> homeassistant.turn_on,
open_cover -> cover.open_cover, ...), so behaviour matches an existing,
working integration rather than inventing new semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .entities import EntitySnapshot


@dataclass(frozen=True)
class ServiceCallPlan:
    domain: str
    service: str
    entity_id: str | list[str]
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class IntentSpec:
    allowed_domains: frozenset[str]
    build: Callable[[list[EntitySnapshot]], ServiceCallPlan]
    response: Callable[[list[EntitySnapshot]], str]


def _entity_id_field(entities: list[EntitySnapshot]) -> str | list[str]:
    """A bare string for a single entity (keeps existing single-match
    service calls/tests unchanged), a list for multiple (quantifiers)."""
    ids = [e.entity_id for e in entities]
    return ids[0] if len(ids) == 1 else ids


_DOMAIN_PLURAL_DE = {"light": "Lichter", "switch": "Schalter", "fan": "Ventilatoren", "cover": "Rollläden"}


def _plural_response(entities: list[EntitySnapshot], singular_suffix: str, plural_suffix: str) -> str:
    """'{Name} {singular_suffix}' for one entity, '{count} {Domain-Plural} {plural_suffix}' for many -
    short and TTS-friendly rather than listing every name."""
    if len(entities) == 1:
        return f"{entities[0].friendly_name} {singular_suffix}"
    noun = _DOMAIN_PLURAL_DE.get(entities[0].domain, "Geräte")
    return f"{len(entities)} {noun} {plural_suffix}"


INTENTS: dict[str, IntentSpec] = {
    "HassTurnOn": IntentSpec(
        allowed_domains=frozenset({"light", "switch", "fan"}),
        build=lambda es: ServiceCallPlan("homeassistant", "turn_on", _entity_id_field(es)),
        response=lambda es: _plural_response(es, "eingeschaltet.", "eingeschaltet."),
    ),
    "HassTurnOff": IntentSpec(
        allowed_domains=frozenset({"light", "switch", "fan"}),
        build=lambda es: ServiceCallPlan("homeassistant", "turn_off", _entity_id_field(es)),
        response=lambda es: _plural_response(es, "ausgeschaltet.", "ausgeschaltet."),
    ),
    "HassToggle": IntentSpec(
        allowed_domains=frozenset({"light", "switch", "fan"}),
        build=lambda es: ServiceCallPlan("homeassistant", "toggle", _entity_id_field(es)),
        response=lambda es: _plural_response(es, "umgeschaltet.", "umgeschaltet."),
    ),
    "HassOpenCover": IntentSpec(
        allowed_domains=frozenset({"cover"}),
        build=lambda es: ServiceCallPlan("cover", "open_cover", _entity_id_field(es)),
        response=lambda es: _plural_response(es, "wird geöffnet.", "geöffnet."),
    ),
    "HassCloseCover": IntentSpec(
        allowed_domains=frozenset({"cover"}),
        build=lambda es: ServiceCallPlan("cover", "close_cover", _entity_id_field(es)),
        response=lambda es: _plural_response(es, "wird geschlossen.", "geschlossen."),
    ),
}


@dataclass(frozen=True)
class PercentIntentSpec:
    """Separate from IntentSpec: build/response take an extra percent value,
    a different callable signature than the 5 action intents above - kept
    apart deliberately rather than bolting an optional argument onto those."""

    build: Callable[[list[EntitySnapshot], int], ServiceCallPlan]
    response: Callable[[list[EntitySnapshot], int], str]


# Keyed by the *resolved entity's domain*, not by a grammar-level intent
# name: German speakers use the same generic verbs ("stelle", "setze") for
# both cover position and light brightness, so the sentence template alone
# cannot tell them apart (verified empirically - a verb-based split either
# rejects valid phrasings or silently mis-routes them). The single
# HassSetPercentage grammar only captures {name}/{percent}; which service
# call applies is decided here, from the entity that {name} actually
# resolved to. A domain with no entry here (e.g. sensor) falls through to
# "not understood" via the dict.get(...) is None check in _match_percentage.
PERCENT_INTENTS: dict[str, PercentIntentSpec] = {
    "cover": PercentIntentSpec(
        build=lambda es, pct: ServiceCallPlan("cover", "set_cover_position", _entity_id_field(es), {"position": pct}),
        response=lambda es, pct: f"{es[0].friendly_name} auf {pct} Prozent gefahren.",
    ),
    "light": PercentIntentSpec(
        build=lambda es, pct: ServiceCallPlan("light", "turn_on", _entity_id_field(es), {"brightness_pct": pct}),
        response=lambda es, pct: f"{es[0].friendly_name} auf {pct} Prozent Helligkeit gestellt.",
    ),
}


@dataclass(frozen=True)
class QueryIntentSpec:
    """A query never produces a ServiceCallPlan - it only speaks the
    current state (see MatchResult.plan: ServiceCallPlan | None)."""

    allowed_domains: frozenset[str]
    response: Callable[[list[EntitySnapshot]], str]


# Starter set of commonly seen HA units; unknown units are still spoken
# (raw, e.g. "42 mbar."), never crash - can be extended as needed.
_UNIT_SPOKEN_DE = {"°C": "Grad", "%": "Prozent", "hPa": "Hektopascal", "lx": "Lux", "W": "Watt", "kWh": "Kilowattstunden"}


def _speak_state(entity: EntitySnapshot) -> str:
    unit = _UNIT_SPOKEN_DE.get(entity.unit, entity.unit) if entity.unit else None
    return f"{entity.state} {unit}." if unit else f"{entity.state}."


QUERY_INTENTS: dict[str, QueryIntentSpec] = {
    "HassGetState": QueryIntentSpec(
        allowed_domains=frozenset({"sensor"}),
        response=lambda es: _speak_state(es[0]),
    ),
}
