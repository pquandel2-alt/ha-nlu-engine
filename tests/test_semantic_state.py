"""HomeIntent V4.2: nlu/semantic_state.py - SemanticState derivation and
matching. Hass-free, no engine involved (mirrors tests/test_area_resolution.py's
style). Covers the window/door vs motion/moisture branching and the
"UNKNOWN never matches" rule explicitly."""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.semantic_state import (
    SemanticState,
    derive_semantic_state,
    evaluate_semantic_state,
    matches_semantic_state,
    supports_state_predicate,
)


def _entity(domain: str, state: str, device_class: str | None = None) -> EntitySnapshot:
    return EntitySnapshot(f"{domain}.x", "X", domain, state, device_class=device_class)


def test_cover_open_closed():
    assert derive_semantic_state(_entity("cover", "open")) is SemanticState.OPEN
    assert derive_semantic_state(_entity("cover", "closed")) is SemanticState.CLOSED


def test_window_binary_sensor_maps_on_off_to_open_closed():
    assert derive_semantic_state(_entity("binary_sensor", "on", "window")) is SemanticState.OPEN
    assert derive_semantic_state(_entity("binary_sensor", "off", "window")) is SemanticState.CLOSED


def test_door_binary_sensor_maps_on_off_to_open_closed():
    assert derive_semantic_state(_entity("binary_sensor", "on", "door")) is SemanticState.OPEN
    assert derive_semantic_state(_entity("binary_sensor", "off", "door")) is SemanticState.CLOSED


def test_motion_binary_sensor_stays_on_off_not_open_closed():
    assert derive_semantic_state(_entity("binary_sensor", "on", "motion")) is SemanticState.ON
    assert derive_semantic_state(_entity("binary_sensor", "off", "motion")) is SemanticState.OFF


def test_moisture_binary_sensor_stays_on_off_not_open_closed():
    assert derive_semantic_state(_entity("binary_sensor", "on", "moisture")) is SemanticState.ON
    assert derive_semantic_state(_entity("binary_sensor", "off", "moisture")) is SemanticState.OFF


def test_binary_sensor_without_device_class_stays_on_off():
    assert derive_semantic_state(_entity("binary_sensor", "on", None)) is SemanticState.ON


def test_light_switch_fan_on_off():
    assert derive_semantic_state(_entity("light", "on")) is SemanticState.ON
    assert derive_semantic_state(_entity("switch", "off")) is SemanticState.OFF
    assert derive_semantic_state(_entity("fan", "on")) is SemanticState.ON


def test_unrecognized_domain_is_unknown():
    assert derive_semantic_state(_entity("sensor", "21.5")) is SemanticState.UNKNOWN


def test_unavailable_state_is_unknown_not_guessed():
    assert derive_semantic_state(_entity("cover", "unavailable")) is SemanticState.UNKNOWN
    assert derive_semantic_state(_entity("binary_sensor", "unknown", "window")) is SemanticState.UNKNOWN


def test_matches_semantic_state_positive():
    assert matches_semantic_state(_entity("cover", "open"), SemanticState.OPEN) is True


def test_matches_semantic_state_negative():
    assert matches_semantic_state(_entity("cover", "closed"), SemanticState.OPEN) is False


def test_unknown_never_matches_even_unknown_request():
    entity = _entity("cover", "unavailable")
    assert matches_semantic_state(entity, SemanticState.UNKNOWN) is False
    assert matches_semantic_state(entity, SemanticState.OPEN) is False


def test_running_vacuum_is_both_active_and_colloquially_on():
    vacuum = _entity("vacuum", "cleaning")
    assert evaluate_semantic_state(vacuum, SemanticState.ACTIVE) is True
    assert evaluate_semantic_state(vacuum, SemanticState.ON) is True


def test_paused_vacuum_is_not_running_but_on_off_is_unknown():
    vacuum = _entity("vacuum", "paused")
    assert evaluate_semantic_state(vacuum, SemanticState.ACTIVE) is False
    assert evaluate_semantic_state(vacuum, SemanticState.INACTIVE) is True
    assert evaluate_semantic_state(vacuum, SemanticState.ON) is None
    assert evaluate_semantic_state(vacuum, SemanticState.OFF) is None


def test_unavailable_state_is_never_turned_into_false_no():
    assert evaluate_semantic_state(_entity("light", "unavailable"), SemanticState.ON) is None


def test_domain_incompatible_predicate_is_not_supported():
    assert supports_state_predicate("cover", SemanticState.ON) is False
    assert supports_state_predicate("light", SemanticState.OPEN) is False
