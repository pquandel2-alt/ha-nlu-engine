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
    entity_id: str
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class IntentSpec:
    allowed_domains: frozenset[str]
    build: Callable[[EntitySnapshot], ServiceCallPlan]
    response: Callable[[EntitySnapshot], str]


INTENTS: dict[str, IntentSpec] = {
    "HassTurnOn": IntentSpec(
        allowed_domains=frozenset({"light", "switch", "fan"}),
        build=lambda e: ServiceCallPlan("homeassistant", "turn_on", e.entity_id),
        response=lambda e: f"{e.friendly_name} eingeschaltet.",
    ),
    "HassTurnOff": IntentSpec(
        allowed_domains=frozenset({"light", "switch", "fan"}),
        build=lambda e: ServiceCallPlan("homeassistant", "turn_off", e.entity_id),
        response=lambda e: f"{e.friendly_name} ausgeschaltet.",
    ),
    "HassToggle": IntentSpec(
        allowed_domains=frozenset({"light", "switch", "fan"}),
        build=lambda e: ServiceCallPlan("homeassistant", "toggle", e.entity_id),
        response=lambda e: f"{e.friendly_name} umgeschaltet.",
    ),
    "HassOpenCover": IntentSpec(
        allowed_domains=frozenset({"cover"}),
        build=lambda e: ServiceCallPlan("cover", "open_cover", e.entity_id),
        response=lambda e: f"{e.friendly_name} wird geöffnet.",
    ),
    "HassCloseCover": IntentSpec(
        allowed_domains=frozenset({"cover"}),
        build=lambda e: ServiceCallPlan("cover", "close_cover", e.entity_id),
        response=lambda e: f"{e.friendly_name} wird geschlossen.",
    ),
}
