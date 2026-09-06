"""V7 migration tests for closed extended device operations."""

from __future__ import annotations

from ha_nlu.engine import NluEngine
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.understanding import UnderstandingAuthority
from ha_nlu.service_call import REGISTERED_OPERATION_INTENT


ENTITIES = [
    EntitySnapshot(
        "climate.wohnen",
        "Wohnzimmer Heizung",
        "climate",
        "heat",
        attributes={"hvac_modes": ["heat", "cool"]},
    ),
    EntitySnapshot(
        "media_player.tv",
        "Wohnzimmer TV",
        "media_player",
        "idle",
        attributes={"source_list": ["HDMI 1", "Netflix"]},
    ),
    EntitySnapshot("vacuum.robi", "Saugroboter", "vacuum", "docked"),
    EntitySnapshot(
        "humidifier.bad",
        "Luftbefeuchter Bad",
        "humidifier",
        "on",
        attributes={"min_humidity": 30, "max_humidity": 70},
    ),
]


def test_registered_operations_are_native_v7_frames():
    engine = NluEngine()
    cases = (
        ("Stelle Wohnzimmer Heizung auf Kühlbetrieb", "climate", "set_hvac_mode"),
        ("Stelle die Lautstärke von Wohnzimmer TV auf 35 Prozent", "media_player", "volume_set"),
        ("Wähle auf Wohnzimmer TV die Quelle HDMI 1", "media_player", "select_source"),
        ("Schicke Saugroboter zur Ladestation", "vacuum", "return_to_base"),
        ("Stelle die Luftfeuchtigkeit vom Luftbefeuchter Bad auf 55 Prozent", "humidifier", "set_humidity"),
    )

    for text, domain, service in cases:
        outcome = engine.understand(text, ENTITIES)
        assert outcome.authority is UnderstandingAuthority.V7_MIGRATED
        assert outcome.payload is not None
        assert outcome.payload.frame.intent == REGISTERED_OPERATION_INTENT
        assert outcome.payload.plan is not None
        assert (outcome.payload.plan.domain, outcome.payload.plan.service) == (
            domain,
            service,
        )


def test_registered_operation_rejects_out_of_range_value():
    outcome = NluEngine().understand(
        "Stelle die Luftfeuchtigkeit vom Luftbefeuchter Bad auf 90 Prozent",
        ENTITIES,
    )

    assert outcome.payload is None


def test_registered_operation_question_never_builds_plan():
    outcome = NluEngine().understand(
        "Soll ich die Lautstärke von Wohnzimmer TV auf 35 Prozent stellen?",
        ENTITIES,
    )

    assert outcome.payload is None
