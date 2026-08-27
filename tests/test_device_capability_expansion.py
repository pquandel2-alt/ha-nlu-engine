from __future__ import annotations

import pytest

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


def test_media_mute_and_vacuum_locate_use_native_services():
    player = EntitySnapshot(
        "media_player.kitchen", "Küchenradio", "media_player", "playing"
    )
    vacuum = EntitySnapshot(
        "vacuum.helper", "Saugroboter Helfer", "vacuum", "docked"
    )

    mute = match_device_control("Schalte das Küchenradio stumm", [player])
    unmute = match_device_control(
        "Hebe die Stummschaltung vom Küchenradio auf", [player]
    )
    locate = match_device_control("Lass den Saugroboter Helfer piepen", [vacuum])

    assert (mute.plan.service, mute.plan.data) == (
        "volume_mute", {"is_volume_muted": True}
    )
    assert (unmute.plan.service, unmute.plan.data) == (
        "volume_mute", {"is_volume_muted": False}
    )
    assert locate.plan.service == "locate"


@pytest.mark.parametrize(
    "sentence",
    (
        "Hebe die Stummschaltung vom Küchenradio auf",
        "Schalte die Stummschaltung vom Küchenradio aus",
        "Mach den Ton beim Küchenradio wieder an",
        "Küchenradio laut schalten",
        "Mach das Küchenradio wieder laut",
        "Unmute Küchenradio",
        "Schalte das Küchenradio nicht mehr stumm",
    ),
)
def test_media_unmute_phrasings_are_compositional(sentence):
    player = EntitySnapshot(
        "media_player.kitchen", "Küchenradio", "media_player", "playing"
    )

    result = match_device_control(sentence, [player])

    assert result is not None and result.plan is not None
    assert result.plan.service == "volume_mute"
    assert result.plan.data == {"is_volume_muted": False}
