"""Phase 12/13 (v2 plan): ServiceMapper - map_to_service_call() turns a
(already-validated) SemanticCommand into the ServiceCallPlan Home Assistant
executes. Domain-specific service/data-key logic itself is unchanged (still
the build callables in service_call.py's INTENTS/PERCENT_INTENTS) - these
tests pin the one decision this module owns: which registry entry applies
to a given command."""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.command import SemanticCommand
from ha_nlu.nlu.frame import SemanticFrame, TargetReference
from ha_nlu.nlu.service_mapper import map_to_service_call
from ha_nlu.service_call import ServiceCallPlan

LIGHT = EntitySnapshot("light.a", "Lampe A", "light", "off", capabilities=frozenset({"BRIGHTNESS"}))
COVER = EntitySnapshot("cover.a", "Rolllade A", "cover", "closed", capabilities=frozenset({"POSITION"}))
SWITCH = EntitySnapshot("switch.a", "Schalter A", "switch", "off")


def _command(intent: str, entities: tuple[EntitySnapshot, ...], parameters: dict | None = None) -> SemanticCommand:
    frame = SemanticFrame(intent=intent, target=TargetReference(text="x"), area=None, parameters=parameters or {})
    return SemanticCommand(
        intent=intent, entities=entities, area=None, parameters=parameters or {}, source_frame=frame
    )


def test_turn_on_switch_maps_to_homeassistant_turn_on():
    plan = map_to_service_call(_command("HassTurnOn", (SWITCH,)))
    assert plan == ServiceCallPlan("homeassistant", "turn_on", "switch.a")


def test_percent_command_maps_by_entity_domain_not_intent_name():
    plan = map_to_service_call(_command("HassSetPercentage", (LIGHT,), {"percent": 40}))
    assert plan == ServiceCallPlan("light", "turn_on", "light.a", {"brightness_pct": 40})


def test_percent_command_on_cover_maps_to_set_cover_position():
    plan = map_to_service_call(_command("HassSetPercentage", (COVER,), {"percent": 30}))
    assert plan == ServiceCallPlan("cover", "set_cover_position", "cover.a", {"position": 30})


def test_unknown_intent_maps_to_none():
    assert map_to_service_call(_command("HassDoesNotExist", (SWITCH,))) is None
