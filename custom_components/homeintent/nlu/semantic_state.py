"""Semantic state normalization (HomeIntent V4.2, "Semantic Query &
State Resolution"): the single place that knows a ``cover``'s
``state == "open"`` and a window ``binary_sensor``'s ``state == "on"`` are
the same semantic concept - "geöffnet". Mirrors nlu/query.py's
``QueryType``/``derive_query_type()`` shape: a small ``Enum`` plus a
data-driven derivation function, not scattered per-parser ``if`` chains
(same style as nlu/capabilities.py::derive_capabilities()).

Every consumer (StateQueryParser, its response builders) reads state
through this module rather than comparing raw ``entity.state`` strings
directly - so "which raw values mean OPEN for which domain/device_class"
is defined exactly once.
"""

from __future__ import annotations

from enum import Enum, auto

from ..entities import EntitySnapshot


class SemanticState(Enum):
    OPEN = auto()
    CLOSED = auto()
    ON = auto()
    OFF = auto()
    ACTIVE = auto()
    INACTIVE = auto()
    UNKNOWN = auto()


# binary_sensor device_classes where "on" means physically open (HA's own
# device_class semantics: https://www.home-assistant.io/integrations/binary_sensor/)
# - not every binary_sensor's "on" means open (a motion sensor's "on" means
# "motion detected", not "open"), so this must be an explicit allow-list,
# never a blanket binary_sensor -> OPEN/CLOSED mapping.
_BINARY_SENSOR_OPEN_CLOSE_DEVICE_CLASSES = frozenset({"window", "door", "opening", "garage_door"})

# cover.state is already the native HA vocabulary ("open"/"closed") - no
# translation needed, just a direct string match.
_COVER_STATE_TO_SEMANTIC = {"open": SemanticState.OPEN, "closed": SemanticState.CLOSED}

# on/off domains where "on"/"off" is the semantic itself (not open/closed).
_ON_OFF_DOMAINS = frozenset({
    "light", "switch", "fan", "humidifier", "input_boolean",
})

_RAW_STATE_TO_ON_OFF = {"on": SemanticState.ON, "off": SemanticState.OFF}

_ACTIVE_STATES = {
    "vacuum": frozenset({"cleaning", "returning"}),
    "lawn_mower": frozenset({"mowing", "returning"}),
}
_INACTIVE_STATES = {
    "vacuum": frozenset({"docked", "idle", "off"}),
    "lawn_mower": frozenset({"docked", "idle", "off"}),
}
_MEDIA_ON_STATES = frozenset({"on", "idle", "playing", "paused", "buffering", "standby"})

# Domains for which HomeIntent has an explicit, deterministic mapping from
# raw HA state to one of the semantic states above. Query callers use this
# as the single boundary instead of inventing their own allow-lists.
QUERYABLE_STATE_DOMAINS = frozenset({
    "binary_sensor", "cover", "light", "switch", "fan", "climate",
    "media_player", "vacuum", "humidifier", "input_boolean", "valve",
    "lawn_mower",
})


def derive_semantic_state(entity: EntitySnapshot) -> SemanticState:
    """Never guesses (Regel 4): an entity whose raw state is
    "unavailable"/"unknown" (or any other value outside the recognized
    vocabulary for its domain/device_class) maps to ``UNKNOWN``, which
    ``matches_semantic_state()`` never matches against a requested filter -
    an unavailable sensor is correctly excluded from "welche Fenster sind
    offen?" rather than silently miscounted as open or closed.
    """
    if entity.domain == "cover":
        return _COVER_STATE_TO_SEMANTIC.get(entity.state, SemanticState.UNKNOWN)
    if entity.domain == "binary_sensor":
        if entity.device_class in _BINARY_SENSOR_OPEN_CLOSE_DEVICE_CLASSES:
            return {"on": SemanticState.OPEN, "off": SemanticState.CLOSED}.get(entity.state, SemanticState.UNKNOWN)
        return _RAW_STATE_TO_ON_OFF.get(entity.state, SemanticState.UNKNOWN)
    if entity.domain in _ON_OFF_DOMAINS:
        return _RAW_STATE_TO_ON_OFF.get(entity.state, SemanticState.UNKNOWN)
    if entity.domain == "climate":
        return SemanticState.OFF if entity.state == "off" else (
            SemanticState.UNKNOWN
            if entity.state in {"unknown", "unavailable", ""}
            else SemanticState.ON
        )
    if entity.domain == "media_player":
        if entity.state == "off":
            return SemanticState.OFF
        return SemanticState.ON if entity.state in _MEDIA_ON_STATES else SemanticState.UNKNOWN
    if entity.domain == "valve":
        return {
            "open": SemanticState.OPEN,
            "opening": SemanticState.OPEN,
            "closed": SemanticState.CLOSED,
            "closing": SemanticState.CLOSED,
        }.get(entity.state, SemanticState.UNKNOWN)
    if entity.state in _ACTIVE_STATES.get(entity.domain, ()):
        return SemanticState.ACTIVE
    if entity.state in _INACTIVE_STATES.get(entity.domain, ()):
        return SemanticState.INACTIVE
    return SemanticState.UNKNOWN


def matches_semantic_state(entity: EntitySnapshot, requested: SemanticState) -> bool:
    """``UNKNOWN`` never matches, even if ``requested`` is itself somehow
    ``UNKNOWN`` - there is no valid sentence that asks for "state unknown"
    entities, and treating two UNKNOWNs as equal would silently surface
    unavailable entities in list/count queries."""
    return evaluate_semantic_state(entity, requested) is True


def supports_state_predicate(
    domain: str,
    requested: SemanticState,
    device_class: str | None = None,
) -> bool:
    """Whether a spoken predicate has deterministic meaning for a domain."""
    if requested is SemanticState.UNKNOWN:
        return False
    if domain == "binary_sensor":
        return requested in (
            {SemanticState.OPEN, SemanticState.CLOSED}
            if device_class in _BINARY_SENSOR_OPEN_CLOSE_DEVICE_CLASSES
            else {SemanticState.ON, SemanticState.OFF}
        )
    if domain in {"cover", "valve"}:
        return requested in {SemanticState.OPEN, SemanticState.CLOSED}
    if domain in {"light", "switch", "input_boolean"}:
        return requested in {SemanticState.ON, SemanticState.OFF}
    if domain in {"fan", "climate", "humidifier", "media_player"}:
        return requested in {
            SemanticState.ON, SemanticState.OFF,
            SemanticState.ACTIVE, SemanticState.INACTIVE,
        }
    if domain in {"vacuum", "lawn_mower"}:
        return requested in {
            SemanticState.ON, SemanticState.OFF,
            SemanticState.ACTIVE, SemanticState.INACTIVE,
        }
    return False


def evaluate_semantic_state(
    entity: EntitySnapshot, requested: SemanticState
) -> bool | None:
    """Return true/false/unknown for one domain-compatible predicate.

    ON/OFF and ACTIVE/INACTIVE are linked only for domains where natural
    German uses both families for the same operational distinction. Paused
    devices remain deliberately undecidable for ON/OFF while still answering
    ``läuft`` with false. Unknown and unavailable states never become a
    fabricated ``Nein``.
    """
    if not supports_state_predicate(entity.domain, requested, entity.device_class):
        return None
    actual = derive_semantic_state(entity)
    if actual is requested:
        return True

    if entity.state == "paused":
        if requested is SemanticState.ACTIVE:
            return False
        if requested is SemanticState.INACTIVE:
            return True
        return None
    if actual is SemanticState.UNKNOWN:
        return None

    if entity.domain in {"vacuum", "lawn_mower"}:
        equivalents = {
            SemanticState.ON: SemanticState.ACTIVE,
            SemanticState.OFF: SemanticState.INACTIVE,
            SemanticState.ACTIVE: SemanticState.ON,
            SemanticState.INACTIVE: SemanticState.OFF,
        }
        equivalent = equivalents.get(requested)
        if equivalent is not None and actual in {requested, equivalent}:
            return True

    if entity.domain == "media_player" and requested in {
        SemanticState.ACTIVE, SemanticState.INACTIVE,
    }:
        running = entity.state in {"playing", "buffering"}
        known = entity.state in _MEDIA_ON_STATES or entity.state == "off"
        return (running if requested is SemanticState.ACTIVE else not running) if known else None

    if entity.domain in {"fan", "climate", "humidifier"}:
        if requested is SemanticState.ACTIVE:
            return actual is SemanticState.ON
        if requested is SemanticState.INACTIVE:
            return actual is SemanticState.OFF

    return False
