"""Phase 9 (v2 plan): Capability System - derive_capabilities(). Pins which
HA signal maps to which Capability per domain, and that entities without the
signal don't get the capability guessed."""

from __future__ import annotations

from ha_nlu.nlu.capabilities import Capability, derive_capabilities


def test_light_without_color_modes_has_only_on_off():
    caps = derive_capabilities("light", None, {})
    assert caps == {Capability.TURN_ON, Capability.TURN_OFF}


def test_brightness_only_light_has_brightness_but_not_color():
    caps = derive_capabilities("light", None, {"supported_color_modes": ["brightness"]})
    assert caps == {Capability.TURN_ON, Capability.TURN_OFF, Capability.BRIGHTNESS}


def test_color_light_has_brightness_and_color():
    caps = derive_capabilities("light", None, {"supported_color_modes": ["hs"]})
    assert caps == {Capability.TURN_ON, Capability.TURN_OFF, Capability.BRIGHTNESS, Capability.COLOR}


def test_color_temp_light_has_brightness_and_color_temperature_not_color():
    caps = derive_capabilities("light", None, {"supported_color_modes": ["color_temp"]})
    assert caps == {
        Capability.TURN_ON,
        Capability.TURN_OFF,
        Capability.BRIGHTNESS,
        Capability.COLOR_TEMPERATURE,
    }


def test_switch_has_only_on_off():
    caps = derive_capabilities("switch", None, {})
    assert caps == {Capability.TURN_ON, Capability.TURN_OFF}


def test_cover_with_position_attribute_has_position():
    caps = derive_capabilities("cover", None, {"current_position": 40})
    assert caps == {Capability.POSITION}


def test_cover_without_position_attribute_has_no_capabilities():
    caps = derive_capabilities("cover", None, {})
    assert caps == frozenset()


def test_fan_with_percentage_has_fan_speed():
    caps = derive_capabilities("fan", None, {"percentage": 50})
    assert caps == {Capability.TURN_ON, Capability.TURN_OFF, Capability.FAN_SPEED}


def test_fan_without_percentage_has_only_on_off():
    caps = derive_capabilities("fan", None, {})
    assert caps == {Capability.TURN_ON, Capability.TURN_OFF}


def test_temperature_sensor_has_temperature_capability():
    caps = derive_capabilities("sensor", "temperature", {})
    assert caps == {Capability.TEMPERATURE}


def test_humidity_sensor_has_humidity_capability():
    caps = derive_capabilities("sensor", "humidity", {})
    assert caps == {Capability.HUMIDITY}


def test_power_sensor_has_power_capability():
    caps = derive_capabilities("sensor", "power", {})
    assert caps == {Capability.POWER}


def test_energy_sensor_has_energy_capability():
    caps = derive_capabilities("sensor", "energy", {})
    assert caps == {Capability.ENERGY}


def test_sensor_without_relevant_device_class_has_no_capabilities():
    caps = derive_capabilities("sensor", "battery", {})
    assert caps == frozenset()
