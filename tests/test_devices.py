"""Unit tests for devices.DeviceSnapshot (World Model Wave, 2026-08-13) -
hass-free, plain dataclass construction/defaults/equality, same style as
test_entities.py's EntitySnapshot coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from ha_nlu.devices import DeviceSnapshot  # noqa: E402


def test_device_snapshot_defaults():
    device = DeviceSnapshot(device_id="device_1", name="Lampe")

    assert device.manufacturer is None
    assert device.model is None
    assert device.area_id is None
    assert device.area_name is None
    assert device.floor_id is None
    assert device.floor_name is None
    assert device.floor_level is None
    assert device.entity_ids == ()


def test_device_snapshot_full_fields():
    device = DeviceSnapshot(
        device_id="device_1",
        name="Wohnzimmerlampe",
        manufacturer="Acme",
        model="X1",
        area_id="wohnzimmer",
        area_name="Wohnzimmer",
        floor_id="eg",
        floor_name="Erdgeschoss",
        floor_level=0,
        entity_ids=("light.a", "light.b"),
    )

    assert device.entity_ids == ("light.a", "light.b")
    assert device.floor_level == 0


def test_device_snapshot_equality_is_value_based():
    a = DeviceSnapshot(device_id="device_1", name="Lampe")
    b = DeviceSnapshot(device_id="device_1", name="Lampe")

    assert a == b
