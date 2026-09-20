"""Query type classification (v2 plan Phase 18, "Query Engine"): which kind
of value a state query is actually asking for, derived deterministically
from the resolved entity's domain/device_class - the same "read the real
signal, never guess from the sentence/intent name alone" rule
nlu/capabilities.py already follows for Capability.

Today every type except BRIGHTNESS is spoken the same way (raw ``state`` +
unit - see service_call.py's ``_speak_state``), so this classification does
not yet change response text for them. It exists now regardless (rather than
only adding it once a consumer needs to branch on it) because the plan lists
these exact 7 types as the Query Engine's vocabulary, and a later phase
(Debug-Modus, Response System) is expected to read it back.
"""

from __future__ import annotations

from enum import Enum, auto

from ..entities import EntitySnapshot


class QueryType(Enum):
    STATE = auto()
    TEMPERATURE = auto()
    HUMIDITY = auto()
    BRIGHTNESS = auto()
    POWER = auto()
    ENERGY = auto()
    BATTERY = auto()


_DEVICE_CLASS_QUERY_TYPE: dict[str, QueryType] = {
    "temperature": QueryType.TEMPERATURE,
    "humidity": QueryType.HUMIDITY,
    "power": QueryType.POWER,
    "energy": QueryType.ENERGY,
    "battery": QueryType.BATTERY,
}


def derive_query_type(entity: EntitySnapshot) -> QueryType:
    """A light is never asked about via ``device_class`` (it has none for
    brightness) - its domain alone implies BRIGHTNESS, mirroring how
    nlu/capabilities.py treats ``domain == "light"`` as its own signal
    source. Every other domain/device_class falls back to STATE, spoken
    as-is (raw ``state`` + unit) - safe default, never a wrong guess."""
    if entity.domain == "light":
        return QueryType.BRIGHTNESS
    return _DEVICE_CLASS_QUERY_TYPE.get(entity.device_class or "", QueryType.STATE)
