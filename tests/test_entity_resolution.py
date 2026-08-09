"""Unit tests for entities.resolve_entity - hass-free, no engine/hassil involved."""

from __future__ import annotations

from ha_nlu.entities import (
    EntitySnapshot,
    ResolveStatus,
    resolve_entities_by_domain,
    resolve_entity,
)


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


def test_reverse_contains_match():
    # Real HA instances often name a cover just after the room ("Wohnzimmer")
    # while people naturally say "Rollladen Wohnzimmer" - the friendly name
    # must resolve even though it's the *shorter* string this time.
    entities = [EntitySnapshot("cover.rolllade_wohnzimmer", "Wohnzimmer", "cover", "open")]
    result = resolve_entity("Rollladen Wohnzimmer", entities)
    assert result.status is ResolveStatus.OK
    assert result.entity.entity_id == "cover.rolllade_wohnzimmer"


def test_reverse_contains_ambiguous_against_generic_entity():
    # If a generic "Rollladen" entity also exists, "Rollladen Wohnzimmer"
    # is genuinely ambiguous between it and "Wohnzimmer" - must not guess.
    entities = [
        EntitySnapshot("cover.rolllade_wohnzimmer", "Wohnzimmer", "cover", "open"),
        EntitySnapshot("cover.rollladen", "Rollladen", "cover", "open"),
    ]
    result = resolve_entity("Rollladen Wohnzimmer", entities)
    assert result.status is ResolveStatus.AMBIGUOUS
    assert len(result.candidates) == 2


def test_resolve_entities_by_domain_no_area():
    entities = [
        EntitySnapshot("cover.a", "A", "cover", "open", area_id="buro"),
        EntitySnapshot("cover.b", "B", "cover", "open", area_id="poleraum"),
        EntitySnapshot("light.c", "C", "light", "on", area_id="buro"),
    ]
    result = resolve_entities_by_domain("cover", entities)
    assert [e.entity_id for e in result] == ["cover.a", "cover.b"]


def test_resolve_entities_by_domain_with_area():
    entities = [
        EntitySnapshot("cover.a", "A", "cover", "open", area_id="poleraum"),
        EntitySnapshot("cover.b", "B", "cover", "open", area_id="poleraum"),
        EntitySnapshot("cover.c", "C", "cover", "open", area_id="buro"),
    ]
    result = resolve_entities_by_domain("cover", entities, area_id="poleraum")
    assert [e.entity_id for e in result] == ["cover.a", "cover.b"]


def test_resolve_entities_by_domain_empty_result():
    entities = [EntitySnapshot("cover.a", "A", "cover", "open", area_id="buro")]
    result = resolve_entities_by_domain("cover", entities, area_id="poleraum")
    assert result == []


def test_duplicate_friendly_name_is_ambiguous():
    # Two entities with the identical friendly name (e.g. the same device
    # exposed by two integrations) must not silently pick one.
    entities = [
        EntitySnapshot("cover.rolllade_poleraum_rechts", "Rolllade Poleraum rechts", "cover", "open"),
        EntitySnapshot(
            "cover.rolllade_poleraum_rechts_sonoff_100294b0df",
            "Rolllade Poleraum rechts",
            "cover",
            "open",
        ),
    ]
    result = resolve_entity("Rolllade Poleraum rechts", entities)
    assert result.status is ResolveStatus.AMBIGUOUS
    assert len(result.candidates) == 2
