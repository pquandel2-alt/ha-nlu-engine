"""Intent -> Home Assistant service-call mapping.

Domain/service pairs mirror the already-verified control logic in
xiaozhi_entity_mcp's tool handlers (turn_on -> homeassistant.turn_on,
open_cover -> cover.open_cover, ...), so behaviour matches an existing,
working integration rather than inventing new semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .entities import EntitySnapshot
from .nlu.capabilities import Capability
from .nlu.query import QueryType, derive_query_type


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
        allowed_domains=frozenset({"light", "switch", "fan", "climate"}),
        build=lambda es: ServiceCallPlan("homeassistant", "turn_on", _entity_id_field(es)),
        response=lambda es: _plural_response(es, "eingeschaltet.", "eingeschaltet."),
    ),
    "HassTurnOff": IntentSpec(
        allowed_domains=frozenset({"light", "switch", "fan", "climate"}),
        build=lambda es: ServiceCallPlan("homeassistant", "turn_off", _entity_id_field(es)),
        response=lambda es: _plural_response(es, "ausgeschaltet.", "ausgeschaltet."),
    ),
    "HassToggle": IntentSpec(
        allowed_domains=frozenset({"light", "switch", "fan", "climate"}),
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


# A light's ``state`` is "on"/"off", not a number - its brightness lives in
# the raw HA "brightness" attribute (0-255, HA's own scale). Converted to a
# percentage here (not stored pre-converted anywhere) since nothing else in
# this project needs a light's brightness as a fraction of 255.
def _speak_brightness(entity: EntitySnapshot) -> str:
    if entity.state == "off":
        return "aus."
    brightness = entity.attributes.get("brightness")
    if brightness is None:
        return "an."  # on, but the light doesn't report a brightness level (e.g. onoff-only)
    return f"{round(brightness / 255 * 100)} Prozent."


def _speak_query(entity: EntitySnapshot) -> str:
    """Dispatches on nlu/query.py's QueryType - today only BRIGHTNESS needs
    its own phrasing, every other type (including STATE) is spoken via the
    same raw state+unit logic ``_speak_state`` already provided."""
    if derive_query_type(entity) is QueryType.BRIGHTNESS:
        return _speak_brightness(entity)
    return _speak_state(entity)


# Which raw HA attribute a comparison-query match's current value is spoken
# from, per domain (HomeIntent plan V4.6, "Comparisons", query-filter half -
# user decision 2026-08-11). Deliberately a separate small read here rather
# than importing parsers.py's ``_current_percent``/``_current_temperature``:
# parsers.py already imports from this module (QUERY_INTENTS itself), so the
# reverse import would be circular - same reasoning kept everywhere else in
# this project for the parsers.py/service_call.py boundary.
def _speak_comparison_value(entity: EntitySnapshot) -> str:
    if entity.domain == "light":
        brightness = entity.attributes.get("brightness")
        return f"{round(brightness / 255 * 100)} Prozent" if brightness is not None else "unbekannt"
    if entity.domain == "cover":
        position = entity.attributes.get("current_position")
        return f"{round(position)} Prozent" if position is not None else "unbekannt"
    if entity.domain == "climate":
        current = entity.attributes.get("current_temperature")
        return f"{round(current)} Grad" if current is not None else "unbekannt"
    return "unbekannt"


def _speak_comparison_matches(entities: list[EntitySnapshot]) -> str:
    """ComparisonQueryParser already filtered ``entities`` down to the ones
    satisfying the comparison (see its docstring) - this only speaks the
    result, same "no matches" bailout as everywhere else in this engine
    doesn't apply here since an empty list never reaches this function
    (parsers.py returns ``None`` instead)."""
    if len(entities) == 1:
        entity = entities[0]
        return f"{entity.friendly_name}: {_speak_comparison_value(entity)}."
    return ", ".join(f"{e.friendly_name} ({_speak_comparison_value(e)})" for e in entities) + "."


QUERY_INTENTS: dict[str, QueryIntentSpec] = {
    "HassGetState": QueryIntentSpec(
        allowed_domains=frozenset({"sensor", "light"}),
        response=lambda es: _speak_query(es[0]),
    ),
    "HassQueryComparison": QueryIntentSpec(
        allowed_domains=frozenset({"light", "cover", "climate"}),
        response=_speak_comparison_matches,
    ),
}


@dataclass(frozen=True)
class LightExtendedIntentSpec:
    """Separate from IntentSpec/PercentIntentSpec: these 4 intents (v2 plan
    Phase 14, "Licht-NLU erweitern") only ever target the ``light`` domain
    but need different capabilities per intent, and build/response need the
    full parameters mapping (step_percent, or color_name, or
    color_temp_kelvin - one differently-named parameter per intent, unlike
    the single uniform ``percent`` PercentIntentSpec carries). ``capability``
    is the single source of truth nlu/validator.py reads for its
    UNSUPPORTED_CAPABILITY check - no separate intent-to-capability dict
    duplicated there.
    """

    capability: Capability
    build: Callable[[list[EntitySnapshot], Mapping[str, Any]], ServiceCallPlan]
    response: Callable[[list[EntitySnapshot], Mapping[str, Any]], str]


# German word spoken back in a response is not necessarily the one the user
# said (e.g. both "lila" and "violett" resolve to "purple") - same
# not-an-exact-echo precedent as _plural_response's domain-plural wording.
_COLOR_SPOKEN_DE = {
    "red": "rot", "green": "grün", "blue": "blau", "yellow": "gelb", "orange": "orange",
    "purple": "lila", "white": "weiß", "pink": "pink", "turquoise": "türkis", "cyan": "cyan",
}
_COLOR_TEMP_SPOKEN_DE = {2700: "warmweiß", 6500: "kaltweiß"}


@dataclass(frozen=True)
class FanExtendedIntentSpec:
    """Separate from LightExtendedIntentSpec: different domain (fan) and a
    different parameter shape (``level``, not step_percent/color_name) -
    same "one dataclass per domain extension" precedent LightExtendedIntentSpec's
    own docstring explains (v2 plan Phase 16, "Fan-NLU erweitern")."""

    capability: Capability
    build: Callable[[list[EntitySnapshot], Mapping[str, Any]], ServiceCallPlan]
    response: Callable[[list[EntitySnapshot], Mapping[str, Any]], str]


def _fan_set_speed_plan(es: list[EntitySnapshot], params: Mapping[str, Any]) -> ServiceCallPlan:
    """"Stufe N" -> a percentage, via the resolved fan's own percentage_step
    attribute (HA's FanEntity base class always exposes it, = 100 /
    speed_count - defaults to 1.0 for a continuous-percentage fan). Clamped
    to 100 so an unusually high level on a coarse-stepped fan can't produce
    an out-of-range service call."""
    percentage_step = es[0].attributes.get("percentage_step") or 1.0
    percentage = min(round(params["level"] * percentage_step), 100)
    return ServiceCallPlan("fan", "turn_on", _entity_id_field(es), {"percentage": percentage})


FAN_EXTENDED_INTENTS: dict[str, FanExtendedIntentSpec] = {
    "HassFanSetSpeed": FanExtendedIntentSpec(
        capability=Capability.FAN_SPEED,
        build=_fan_set_speed_plan,
        response=lambda es, params: f"{es[0].friendly_name} auf Stufe {params['level']} gestellt.",
    ),
    # "schneller"/"langsamer" call HA's native fan.increase_speed/
    # decrease_speed directly, with no extra data - unlike light brightness
    # (Phase 14) there is no invented step size to decide on here; HA/the
    # device own the step.
    "HassFanIncreaseSpeed": FanExtendedIntentSpec(
        capability=Capability.FAN_SPEED,
        build=lambda es, params: ServiceCallPlan("fan", "increase_speed", _entity_id_field(es)),
        response=lambda es, params: f"{es[0].friendly_name} schneller gestellt.",
    ),
    "HassFanDecreaseSpeed": FanExtendedIntentSpec(
        capability=Capability.FAN_SPEED,
        build=lambda es, params: ServiceCallPlan("fan", "decrease_speed", _entity_id_field(es)),
        response=lambda es, params: f"{es[0].friendly_name} langsamer gestellt.",
    ),
}


@dataclass(frozen=True)
class ClimateExtendedIntentSpec:
    """Separate from FanExtendedIntentSpec: different domain (climate) and a
    different parameter shape (an absolute ``temperature`` target, not
    ``level``/step_percent) - same "one dataclass per domain extension"
    precedent FanExtendedIntentSpec's own docstring explains (v2 plan Phase
    17, "Climate-NLU")."""

    capability: Capability
    build: Callable[[list[EntitySnapshot], Mapping[str, Any]], ServiceCallPlan]
    response: Callable[[list[EntitySnapshot], Mapping[str, Any]], str]


# "wärmer"/"kälter" have no user-specified amount (unlike light brightness in
# Phase 14) - a fixed default step, same design choice FanExtendedIntentSpec's
# docstring explains for why *that* phase didn't need one (climate has no
# native increase/decrease service to defer to, unlike fan.increase_speed).
_CLIMATE_TEMPERATURE_STEP = 1


def _climate_step_plan(es: list[EntitySnapshot], step: int) -> ServiceCallPlan:
    """New absolute target = the resolved entity's current setpoint (its
    ``temperature`` attribute - the same signal nlu/capabilities.py already
    reads to derive Capability.TEMPERATURE) plus/minus the fixed step."""
    current = es[0].attributes["temperature"]
    return ServiceCallPlan("climate", "set_temperature", _entity_id_field(es), {"temperature": current + step})


CLIMATE_EXTENDED_INTENTS: dict[str, ClimateExtendedIntentSpec] = {
    "HassClimateSetTemperature": ClimateExtendedIntentSpec(
        capability=Capability.TEMPERATURE,
        build=lambda es, params: ServiceCallPlan(
            "climate", "set_temperature", _entity_id_field(es), {"temperature": params["temperature"]}
        ),
        response=lambda es, params: f"{es[0].friendly_name} auf {params['temperature']} Grad gestellt.",
    ),
    "HassClimateIncreaseTemperature": ClimateExtendedIntentSpec(
        capability=Capability.TEMPERATURE,
        build=lambda es, params: _climate_step_plan(es, _CLIMATE_TEMPERATURE_STEP),
        response=lambda es, params: f"{es[0].friendly_name} wärmer gestellt.",
    ),
    "HassClimateDecreaseTemperature": ClimateExtendedIntentSpec(
        capability=Capability.TEMPERATURE,
        build=lambda es, params: _climate_step_plan(es, -_CLIMATE_TEMPERATURE_STEP),
        response=lambda es, params: f"{es[0].friendly_name} kälter gestellt.",
    ),
}


LIGHT_EXTENDED_INTENTS: dict[str, LightExtendedIntentSpec] = {
    "HassLightBrighten": LightExtendedIntentSpec(
        capability=Capability.BRIGHTNESS,
        build=lambda es, params: ServiceCallPlan(
            "light", "turn_on", _entity_id_field(es), {"brightness_step_pct": params["step_percent"]}
        ),
        response=lambda es, params: f"{es[0].friendly_name} um {params['step_percent']} Prozent heller gestellt.",
    ),
    "HassLightDim": LightExtendedIntentSpec(
        capability=Capability.BRIGHTNESS,
        build=lambda es, params: ServiceCallPlan(
            "light", "turn_on", _entity_id_field(es), {"brightness_step_pct": -params["step_percent"]}
        ),
        response=lambda es, params: f"{es[0].friendly_name} um {params['step_percent']} Prozent dunkler gestellt.",
    ),
    "HassLightSetColor": LightExtendedIntentSpec(
        capability=Capability.COLOR,
        build=lambda es, params: ServiceCallPlan(
            "light", "turn_on", _entity_id_field(es), {"color_name": params["color_name"]}
        ),
        response=lambda es, params: (
            f"{es[0].friendly_name} auf {_COLOR_SPOKEN_DE.get(params['color_name'], params['color_name'])} gestellt."
        ),
    ),
    "HassLightSetColorTemp": LightExtendedIntentSpec(
        capability=Capability.COLOR_TEMPERATURE,
        build=lambda es, params: ServiceCallPlan(
            "light", "turn_on", _entity_id_field(es), {"kelvin": params["color_temp_kelvin"]}
        ),
        response=lambda es, params: (
            f"{es[0].friendly_name} auf "
            f"{_COLOR_TEMP_SPOKEN_DE.get(params['color_temp_kelvin'], str(params['color_temp_kelvin']) + ' Kelvin')} "
            "gestellt."
        ),
    ),
}
