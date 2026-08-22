"""Unit tests for world_model.WorldModel/build_world_model() (World Model
Wave, 2026-08-13) - hass-free, hand-built EntitySnapshot/DeviceSnapshot
fixtures, same style as tests/test_entity_index.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from ha_nlu.devices import DeviceSnapshot  # noqa: E402
from ha_nlu.entities import EntitySnapshot, build_entity_index  # noqa: E402
from ha_nlu.world_model import build_world_model  # noqa: E402

LIGHT_WOHNZIMMER = EntitySnapshot(
    "light.wohnzimmer", "Wohnzimmerlicht", "light", "on",
    area_id="wohnzimmer", area_name="Wohnzimmer", floor_id="eg", floor_name="Erdgeschoss",
)
LIGHT_KUECHE = EntitySnapshot(
    "light.kueche", "Küchenlicht", "light", "on", area_id="kueche", area_name="Küche",
    capabilities=frozenset({"TURN_ON"}),
)
SWITCH_UNSELECTED = EntitySnapshot(
    "switch.wohnzimmer_stecker", "Wohnzimmer Steckdose", "switch", "on", area_id="wohnzimmer",
)

DEVICE_WOHNZIMMER = DeviceSnapshot(
    device_id="device_wohnzimmer",
    name="Wohnzimmer Lampe",
    manufacturer="Acme",
    area_id="wohnzimmer",
    area_name="Wohnzimmer",
    # Owns both the selected light and an unselected switch - the switch is
    # NOT in the entities list handed to build_world_model() below.
    entity_ids=("light.wohnzimmer", "switch.wohnzimmer_stecker"),
)
DEVICE_KUECHE = DeviceSnapshot(
    device_id="device_kueche", name="Küchenlampe", area_id="kueche", entity_ids=("light.kueche",),
)
DEVICE_NO_AREA = DeviceSnapshot(device_id="device_orphan", name="Verwaistes Gerät", entity_ids=())

ENTITIES = [LIGHT_WOHNZIMMER, LIGHT_KUECHE]
DEVICES = [DEVICE_WOHNZIMMER, DEVICE_KUECHE, DEVICE_NO_AREA]


def test_build_world_model_bundles_all_families():
    world_model = build_world_model(ENTITIES, DEVICES)

    assert world_model.entities == tuple(ENTITIES)
    assert world_model.devices == tuple(DEVICES)
    assert {a.area_id for a in world_model.areas} == {"wohnzimmer", "kueche"}
    assert {f.floor_id for f in world_model.floors} == {"eg"}
    assert world_model.entity_index == build_entity_index(ENTITIES)


def test_device_for_entity():
    world_model = build_world_model(ENTITIES, DEVICES)

    assert world_model.device_for_entity("light.wohnzimmer") == DEVICE_WOHNZIMMER
    assert world_model.device_for_entity("light.kueche") == DEVICE_KUECHE
    assert world_model.device_for_entity("light.unknown") is None


def test_entities_for_device_drops_entities_not_in_given_list():
    world_model = build_world_model(ENTITIES, DEVICES)

    # DEVICE_WOHNZIMMER.entity_ids includes switch.wohnzimmer_stecker, which
    # isn't part of ENTITIES (unselected this turn) - it must not appear.
    assert world_model.entities_for_device("device_wohnzimmer") == (LIGHT_WOHNZIMMER,)
    assert world_model.entities_for_device("device_kueche") == (LIGHT_KUECHE,)
    assert world_model.entities_for_device("device_unknown") == ()


def test_devices_in_area():
    world_model = build_world_model(ENTITIES, DEVICES)

    assert world_model.devices_in_area("wohnzimmer") == (DEVICE_WOHNZIMMER,)
    assert world_model.devices_in_area("kueche") == (DEVICE_KUECHE,)
    # DEVICE_NO_AREA has area_id=None - absent from every devices_in_area()
    # result, but still reachable via devices_by_id.
    assert world_model.devices_in_area("nonexistent") == ()
    assert world_model.devices_by_id["device_orphan"] == DEVICE_NO_AREA


def test_semantic_indices_and_combined_selection():
    world_model = build_world_model(ENTITIES, DEVICES)

    assert world_model.entities_by_domain["light"] == tuple(ENTITIES)
    assert world_model.entities_by_area_id["wohnzimmer"] == (LIGHT_WOHNZIMMER,)
    assert world_model.entities_by_floor_id["eg"] == (LIGHT_WOHNZIMMER,)
    assert world_model.entities_by_capability["TURN_ON"] == (LIGHT_KUECHE,)
    assert world_model.select_entities(domain="light", area_id="kueche") == (LIGHT_KUECHE,)
    assert world_model.select_entities(domain="light", area_id="unknown") == ()


def test_empty_everything_yields_empty_world_model():
    world_model = build_world_model([], [])

    assert world_model.entities == ()
    assert world_model.devices == ()
    assert world_model.areas == ()
    assert world_model.floors == ()
    assert world_model.device_for_entity("light.anything") is None
    assert world_model.entities_for_device("device_anything") == ()
    assert world_model.devices_in_area("area_anything") == ()
