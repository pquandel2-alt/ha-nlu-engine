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
    # HomeIntent V4.2 ("Semantic Query & State Resolution") - the
    # "state_query" golden category's binary_sensor fixtures. Deliberately
    # mixes an open and a closed window across two areas (so area-scoped
    # AND unscoped list/count/exists cases both have a real positive and a
    # real empty-result case), a door (distinct device_class, same
    # OPEN/CLOSED semantic as window), and a motion sensor (device_class
    # that stays ON/OFF rather than mapping to OPEN/CLOSED - see
    # nlu/semantic_state.py).
    EntitySnapshot(
        "binary_sensor.fenster_wohnzimmer", "Fenster Wohnzimmer", "binary_sensor", "on",
        area_id="wohnzimmer_bs", area_name="Wohnzimmer", device_class="window",
    ),
    EntitySnapshot(
        "binary_sensor.fenster_kueche", "Fenster Küche", "binary_sensor", "off",
        area_id="kueche_bs", area_name="Küche", device_class="window",
    ),
    EntitySnapshot(
        "binary_sensor.fenster_schlafzimmer", "Fenster Schlafzimmer", "binary_sensor", "on",
        area_id="schlafzimmer_bs", area_name="Schlafzimmer", device_class="window",
    ),
    EntitySnapshot(
        "binary_sensor.tuer_eingang", "Tür Eingang", "binary_sensor", "on",
        area_id="eingang", area_name="Eingang", device_class="door",
    ),
    EntitySnapshot(
        "binary_sensor.bewegung_flur", "Bewegung Flur", "binary_sensor", "on",
        area_id="flur_bs", area_name="Flur", device_class="motion",
    ),
]
