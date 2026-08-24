from __future__ import annotations

from ha_nlu.device_control import match_device_control
from ha_nlu.entities import EntitySnapshot


def test_climate_preset_is_selected_from_live_capability_list():
    entity = EntitySnapshot(
        "climate.office", "Büroheizung", "climate", "heat",
        attributes={"preset_modes": ["eco", "comfort"]},
    )
    result = match_device_control("Stelle Büroheizung auf eco", [entity])
    assert result.plan.service == "set_preset_mode"
    assert result.plan.data == {"preset_mode": "eco"}


def test_fan_oscillation_and_direction_use_native_services():
    entity = EntitySnapshot("fan.office", "Bürolüfter", "fan", "on")
    oscillate = match_device_control("Schalte beim Bürolüfter das Schwenken ein", [entity])
    direction = match_device_control("Stelle die Richtung vom Bürolüfter rückwärts", [entity])
    assert oscillate.plan.service == "oscillate"
    assert oscillate.plan.data == {"oscillating": True}
    assert direction.plan.service == "set_direction"
    assert direction.plan.data == {"direction": "reverse"}


def test_cover_tilt_and_valve_position_are_capability_specific():
    cover = EntitySnapshot("cover.office", "Bürojalousie", "cover", "open")
    valve = EntitySnapshot("valve.garden", "Gartenventil", "valve", "closed")
    tilt = match_device_control("Stelle die Lamellen der Bürojalousie auf 35 Prozent", [cover])
    position = match_device_control("Stelle das Gartenventil auf 40 Prozent", [valve])
    assert tilt.plan.service == "set_cover_tilt_position"
    assert tilt.plan.data == {"tilt_position": 35}
    assert position.plan.service == "set_valve_position"
    assert position.plan.data == {"position": 40}


def test_humidifier_and_water_heater_modes_come_from_attributes():
    humidifier = EntitySnapshot(
        "humidifier.bedroom", "Schlafzimmerbefeuchter", "humidifier", "on",
        attributes={"available_modes": ["auto", "sleep"]},
    )
    heater = EntitySnapshot(
        "water_heater.boiler", "Warmwasserboiler", "water_heater", "eco",
        attributes={"operation_list": ["eco", "performance"]},
    )
    mode = match_device_control("Stelle Schlafzimmerbefeuchter auf sleep Modus", [humidifier])
    operation = match_device_control("Stelle Warmwasserboiler auf performance Betrieb", [heater])
    assert mode.plan.data == {"mode": "sleep"}
    assert operation.plan.data == {"operation_mode": "performance"}
