"""Shared entity set for tests/golden/*.json (v2 plan Phase 20, "Golden
Tests"). One place, imported by both scripts/generate_golden_tests.py
(which produces the fixtures) and tests/test_golden.py (which replays
them) - both must resolve names against the exact same entities, or a
replay could pick a different candidate than generation did.

Deliberately its own small set rather than conftest.py's ALL_ENTITIES:
golden cases exercise every capability-gated feature (colour, colour
temperature, fan speed, climate temperature, sensor/light queries, a
shared-area pair for quantifiers) that ALL_ENTITIES' plain fixtures don't
carry capabilities/attributes for.
"""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot

GOLDEN_ENTITIES: list[EntitySnapshot] = [
    EntitySnapshot(
        "light.wohnzimmer", "Wohnzimmerlicht", "light", "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS", "COLOR", "COLOR_TEMPERATURE"}),
        attributes={"brightness": 128},
    ),
    EntitySnapshot(
        "light.kueche", "Küchenlicht", "light", "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    ),
    EntitySnapshot(
        "light.flur", "Flurlicht", "light", "on",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "switch.steckdose_buero", "Steckdose Büro", "switch", "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "cover.buero", "Rollladen Büro", "cover", "closed",
        capabilities=frozenset({"POSITION"}),
    ),
    EntitySnapshot(
        "cover.schlafzimmer", "Rollladen Schlafzimmer", "cover", "closed",
        capabilities=frozenset({"POSITION"}),
    ),
    EntitySnapshot(
        "cover.poleraum_links", "Rolllade Poleraum links", "cover", "closed",
        capabilities=frozenset({"POSITION"}), area_id="poleraum", area_name="Poleraum",
    ),
    EntitySnapshot(
        "cover.poleraum_rechts", "Rolllade Poleraum rechts", "cover", "closed",
        capabilities=frozenset({"POSITION"}), area_id="poleraum", area_name="Poleraum",
    ),
    EntitySnapshot(
        "fan.venti", "Ventilator", "fan", "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "FAN_SPEED"}),
        attributes={"percentage_step": 20.0},
    ),
    EntitySnapshot(
        "climate.heizung", "Heizung Wohnzimmer", "climate", "heat",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "TEMPERATURE"}),
        attributes={"temperature": 20},
    ),
    EntitySnapshot(
        "climate.einfach", "Einfache Heizung", "climate", "heat",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "sensor.aussentemperatur", "Außentemperatur", "sensor", "18.4", unit="°C",
    ),
    EntitySnapshot(
        "sensor.luftfeuchtigkeit_bad", "Luftfeuchtigkeit Bad", "sensor", "52", unit="%",
    ),
    EntitySnapshot(
        "sensor.waschmaschine_leistung", "Waschmaschine", "sensor", "1200", unit="W", device_class="power",
    ),
    EntitySnapshot(
        "sensor.trockner_energie", "Trockner", "sensor", "2.1", unit="kWh", device_class="energy",
    ),
    EntitySnapshot(
        "sensor.fensterkontakt_batterie", "Fensterkontakt Batterie", "sensor", "84", unit="%",
        device_class="battery",
    ),
    # Deliberately tied friendly_name across two areas - only consumer is
    # the "ambiguity" category (v2 plan Phase 25, "Clarification"); no other
    # category sentence references "Testlicht", so it can't collide.
    EntitySnapshot(
        "light.testlicht_a", "Testlicht", "light", "off",
        area_id="zimmer_a", area_name="Zimmer A",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "light.testlicht_b", "Testlicht", "light", "off",
        area_id="zimmer_b", area_name="Zimmer B",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
]
