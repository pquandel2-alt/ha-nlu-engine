"""Unit tests for entities.resolve_entity - hass-free, no engine/hassil involved."""

from __future__ import annotations

from ha_nlu.entities import ResolveStatus, resolve_entity


def test_exact_match(entities):
    result = resolve_entity("Garagentor", entities)
    assert result.status is ResolveStatus.OK
    assert result.entity.entity_id == "switch.garagentor"


def test_exact_match_case_insensitive(entities):
    result = resolve_entity("garagentor", entities)
    assert result.status is ResolveStatus.OK
    assert result.entity.entity_id == "switch.garagentor"


def test_unambiguous_contains_match(entities):
    # Only "Rollladen Büro" contains "Büro".
    result = resolve_entity("Büro", entities)
    assert result.status is ResolveStatus.OK
    assert result.entity.entity_id == "cover.rolllade_buro"


def test_ambiguous_match(entities):
    # "licht" is a substring of many light/switch friendly names
    # (Treppenlicht, Flurlicht, Küchendeckenlicht, Haustürlicht, ...).
    result = resolve_entity("licht", entities)
    assert result.status is ResolveStatus.AMBIGUOUS
    assert len(result.candidates) > 1


def test_not_found(entities):
    result = resolve_entity("Kellerlicht", entities)
    assert result.status is ResolveStatus.NOT_FOUND
    assert result.entity is None


def test_empty_name_not_found(entities):
    result = resolve_entity("", entities)
    assert result.status is ResolveStatus.NOT_FOUND
