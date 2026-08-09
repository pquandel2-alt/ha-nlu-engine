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
]
TURN_OFF_PHRASES = [
    "Mach {name} aus",
    "Schalte {name} aus",
    "{name} ausschalten",
    "Kannst du {name} ausmachen?",
    "Bitte {name} aus",
]
COVER_OPEN_PHRASES = [
    "Öffne {name}",
    "Fahre {name} hoch",
    "{name} hochfahren",
    "Mach {name} auf",
]
COVER_CLOSE_PHRASES = [
    "Schließe {name}",
    "Fahre {name} runter",
    "{name} runterfahren",
    "Mach {name} zu",
]


def _snapshots(names: dict[str, str], domain: str, state: str) -> list[EntitySnapshot]:
    return [EntitySnapshot(eid, name, domain, state) for name, eid in names.items()]


ALL_ENTITIES: list[EntitySnapshot] = (
    _snapshots(LIGHTS, "light", "off")
    + _snapshots(SWITCHES, "switch", "off")
    + _snapshots(COVERS, "cover", "closed")
    + _snapshots(FANS, "fan", "off")
)


@pytest.fixture(scope="session")
def engine() -> NluEngine:
    return NluEngine()


@pytest.fixture(scope="session")
def entities() -> list[EntitySnapshot]:
    return ALL_ENTITIES
