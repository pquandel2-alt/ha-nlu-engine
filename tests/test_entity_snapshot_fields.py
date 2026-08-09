"""Phase 5 (v2 plan): EntitySnapshot extended with device_class, state_class,
aliases, attributes, capabilities. Pins the dataclass defaults (so callers
that only pass the original four positional fields keep working) and the
hass_entities.py wiring that fills device_class/state_class/attributes from
real HA state."""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot


def test_new_fields_default_to_empty_when_omitted():
    snap = EntitySnapshot("light.x", "X", "light", "off")
    assert snap.device_class is None
    assert snap.state_class is None
    assert snap.aliases == ()
    assert snap.attributes == {}
    assert snap.capabilities == frozenset()


def test_new_fields_can_be_set_explicitly():
    snap = EntitySnapshot(
        "sensor.temp",
        "Temperatur",
        "sensor",
        "18.4",
        device_class="temperature",
        state_class="measurement",
        aliases=("Außentemperatur",),
        attributes={"unit_of_measurement": "°C"},
        capabilities=frozenset({"TEMPERATURE"}),
    )
    assert snap.device_class == "temperature"
    assert snap.state_class == "measurement"
    assert snap.aliases == ("Außentemperatur",)
    assert snap.attributes == {"unit_of_measurement": "°C"}
    assert snap.capabilities == frozenset({"TEMPERATURE"})


def test_two_default_attributes_dicts_are_independent():
    # default_factory=dict must not share one mutable dict across instances.
    a = EntitySnapshot("light.a", "A", "light", "off")
    b = EntitySnapshot("light.b", "B", "light", "off")
    assert a.attributes is not b.attributes
