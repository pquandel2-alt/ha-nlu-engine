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
    "vacuum": frozenset({"docked", "idle", "paused", "off"}),
    "lawn_mower": frozenset({"docked", "idle", "paused", "off"}),
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
    if requested is SemanticState.UNKNOWN:
        return False
    return derive_semantic_state(entity) is requested
