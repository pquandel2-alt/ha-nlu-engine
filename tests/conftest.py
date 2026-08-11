"""Fixtures derived from the curated entity lists and phrase templates in
``ha-ai-finetune/generate_training_data.py`` (copied here rather than
imported across repos, since that script lives in an unrelated project and
is not a dependency of ha-nlu-engine).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from ha_nlu.engine import NluEngine  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402

LIGHTS = {
    "Treppenlicht": "light.treppen_licht_gruppe",
    "Flurlicht": "light.flur_licht",
    "Kücheninsel": "light.kucheninsel",
    "Schlafzimmerlicht": "light.schlafzimmer_licht",
    "Terrassenlicht": "light.terrassen_licht",
    "Küchendeckenlicht": "light.kuche_deckenlicht_2",
    "Dachgeschosslicht": "light.dachgeschoss_licht",
    "Studiolicht": "light.studio_4",
    "Ambientelicht": "light.ambiente",
    "Wohnzimmer Regal": "light.wohnzimmer_regal",
}

SWITCHES = {
    "Tablet Ladesteckdose": "switch.wifi_smart_switch",
    "Garagentor": "switch.garagentor",
    "Teich Springbrunnen": "switch.garten_teich_springbrunnen",
    "Licht Sportraum": "switch.licht_sportraum",
    "Haustürlicht": "switch.haustur_light",
    "Sichtschutz": "switch.sichtschutz",
    "Kücheninsel Steckdose": "switch.kucheninsel_power_switch",
}

COVERS = {
    "Rollladen": "cover.rollladen",
    "Rollladen Büro": "cover.rolllade_buro",
    "Rollladen Wohnzimmer": "cover.rolllade_wohnzimmer",
    "Rollladen Badezimmer groß": "cover.rolllade_gross",
    "Rollladen Küche": "cover.rolllade_3",
    "Rollladen Schlafzimmer": "cover.rolllade_4",
}

FANS = {
    "Ventilator": "fan.venti",
}

TURN_ON_PHRASES = [
    "Mach {name} an",
    "Schalte {name} ein",
    "{name} einschalten",
    "Kannst du {name} anmachen?",
    "Bitte {name} an",
    "Dreh {name} an",
    "Lass {name} an",
]
TURN_OFF_PHRASES = [
    "Mach {name} aus",
    "Schalte {name} aus",
    "{name} ausschalten",
    "Kannst du {name} ausmachen?",
    "Bitte {name} aus",
    "Dreh {name} aus",
    "Lass {name} aus",
]
COVER_OPEN_PHRASES = [
    "Öffne {name}",
    "Fahre {name} hoch",
    "{name} hochfahren",
    "Mach {name} auf",
    "Mach {name} ganz auf",
]
COVER_CLOSE_PHRASES = [
    "Schließe {name}",
    "Fahre {name} runter",
    "{name} runterfahren",
    "Mach {name} zu",
    "Mach {name} ganz zu",
]


def _snapshots(
    names: dict[str, str], domain: str, state: str, capabilities: frozenset[str] = frozenset()
) -> list[EntitySnapshot]:
    return [EntitySnapshot(eid, name, domain, state, capabilities=capabilities) for name, eid in names.items()]


ALL_ENTITIES: list[EntitySnapshot] = (
    # Dimmable/positionable by default, same as a real light/cover would be
    # via hass_entities.py's derive_capabilities() - needed since Phase 11
    # (Command Validator) checks these on percent commands.
    _snapshots(LIGHTS, "light", "off", capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}))
    + _snapshots(SWITCHES, "switch", "off", capabilities=frozenset({"TURN_ON", "TURN_OFF"}))
    + _snapshots(COVERS, "cover", "closed", capabilities=frozenset({"POSITION"}))
    + _snapshots(FANS, "fan", "off", capabilities=frozenset({"TURN_ON", "TURN_OFF"}))
)

# Real-world reproduction of the reported "Fahre beide Rollladen im
# Poleraum hoch" case: exactly two covers sharing one area.
POLERAUM_COVERS: list[EntitySnapshot] = [
    EntitySnapshot(
        "cover.rolllade_poleraum_links", "Rolllade Poleraum links", "cover", "closed",
        area_id="poleraum", area_name="Poleraum",
    ),
    EntitySnapshot(
        "cover.rolllade_poleraum_rechts", "Rolllade Poleraum rechts", "cover", "closed",
        area_id="poleraum", area_name="Poleraum",
    ),
]

QUANTIFIER_ENTITIES: list[EntitySnapshot] = ALL_ENTITIES + POLERAUM_COVERS

SENSORS = {
    "Außentemperatur": ("sensor.aussentemperatur", "18.4", "°C", "temperature"),
    "Luftfeuchtigkeit Bad": ("sensor.luftfeuchtigkeit_bad", "52", "%", "humidity"),
    "Waschmaschine": ("sensor.waschmaschine_leistung", "1200", "W", "power"),
    "Waschmaschine Verbrauch": ("sensor.waschmaschine_energie", "3.7", "kWh", "energy"),
    "Fensterkontakt Büro Batterie": ("sensor.fensterkontakt_buero_batterie", "84", "%", "battery"),
}

SENSOR_ENTITIES: list[EntitySnapshot] = [
    EntitySnapshot(eid, name, "sensor", state, unit=unit, device_class=device_class)
    for name, (eid, state, unit, device_class) in SENSORS.items()
]


@pytest.fixture(scope="session")
def engine() -> NluEngine:
    return NluEngine()


@pytest.fixture(scope="session")
def entities() -> list[EntitySnapshot]:
    return ALL_ENTITIES


@pytest.fixture(scope="session")
def quantifier_entities() -> list[EntitySnapshot]:
    return QUANTIFIER_ENTITIES


@pytest.fixture(scope="session")
def sensor_entities() -> list[EntitySnapshot]:
    return SENSOR_ENTITIES
