"""Unit tests for areas.resolve_area_name - hass-free, no engine/hassil involved."""

from __future__ import annotations

from ha_nlu.areas import AreaResolveStatus, resolve_area_name
from ha_nlu.entities import EntitySnapshot

POLERAUM_COVERS = [
    EntitySnapshot("cover.a", "Rolllade Poleraum links", "cover", "closed", area_id="poleraum", area_name="Poleraum"),
    EntitySnapshot("cover.b", "Rolllade Poleraum rechts", "cover", "closed", area_id="poleraum", area_name="Poleraum"),
    EntitySnapshot("cover.c", "Rolllade Büro", "cover", "closed", area_id="buro", area_name="Büro"),
]


def test_exact_match():
    result = resolve_area_name("Poleraum", POLERAUM_COVERS)
    assert result.status is AreaResolveStatus.OK
    assert result.area_id == "poleraum"


def test_exact_match_case_insensitive():
    result = resolve_area_name("büro", POLERAUM_COVERS)
    assert result.status is AreaResolveStatus.OK
    assert result.area_id == "buro"


def test_unambiguous_contains_match():
    result = resolve_area_name("im Poleraum", POLERAUM_COVERS)
    assert result.status is AreaResolveStatus.OK
    assert result.area_id == "poleraum"


def test_not_found():
    result = resolve_area_name("Keller", POLERAUM_COVERS)
    assert result.status is AreaResolveStatus.NOT_FOUND


def test_empty_name_not_found():
    result = resolve_area_name("", POLERAUM_COVERS)
    assert result.status is AreaResolveStatus.NOT_FOUND


def test_entities_without_area_are_ignored():
    entities = [EntitySnapshot("cover.a", "Rolllade", "cover", "closed")]
    result = resolve_area_name("Poleraum", entities)
    assert result.status is AreaResolveStatus.NOT_FOUND


def test_ambiguous_area_name():
    entities = [
        EntitySnapshot("cover.a", "A", "cover", "closed", area_id="buro_oben", area_name="Büro"),
        EntitySnapshot("cover.b", "B", "cover", "closed", area_id="buro_unten", area_name="Büro"),
    ]
    result = resolve_area_name("Büro", entities)
    assert result.status is AreaResolveStatus.AMBIGUOUS
    assert len(result.candidates) == 2
