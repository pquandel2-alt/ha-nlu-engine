"""Unit tests for entities.build_entity_index (v2 plan Phase 23,
"Performance/Indexing") - hass-free, no engine/hassil involved."""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot, build_entity_index

LIGHT_WOHNZIMMER = EntitySnapshot(
    "light.wohnzimmer", "Wohnzimmerlicht", "light", "on", area_id="wohnzimmer", area_name="Wohnzimmer",
)
LIGHT_KUECHE = EntitySnapshot(
    "light.kueche", "Küchenlicht", "light", "on", area_id="kueche", area_name="Küche",
    aliases=("Deckenlicht",),
)
SWITCH_NO_AREA = EntitySnapshot("switch.steckdose", "Steckdose", "switch", "off")


def test_by_domain_groups_all_entities_of_that_domain():
    index = build_entity_index([LIGHT_WOHNZIMMER, LIGHT_KUECHE, SWITCH_NO_AREA])
    assert sorted(e.entity_id for e in index.by_domain["light"]) == ["light.kueche", "light.wohnzimmer"]
    assert index.by_domain["switch"] == (SWITCH_NO_AREA,)
    assert "cover" not in index.by_domain


def test_by_area_excludes_entities_without_area_id():
    index = build_entity_index([LIGHT_WOHNZIMMER, LIGHT_KUECHE, SWITCH_NO_AREA])
    assert index.by_area["wohnzimmer"] == (LIGHT_WOHNZIMMER,)
    assert index.by_area["kueche"] == (LIGHT_KUECHE,)
    assert sum(len(v) for v in index.by_area.values()) == 2


def test_by_normalized_name_is_case_and_whitespace_insensitive():
    index = build_entity_index([LIGHT_WOHNZIMMER])
    assert index.by_normalized_name["wohnzimmerlicht"] == (LIGHT_WOHNZIMMER,)
    assert "  Wohnzimmerlicht  " not in index.by_normalized_name


def test_by_normalized_alias_covers_entity_id_and_configured_alias():
    index = build_entity_index([LIGHT_KUECHE])
    assert LIGHT_KUECHE in index.by_normalized_alias["light.kueche"]
    assert LIGHT_KUECHE in index.by_normalized_alias["deckenlicht"]
    # Humanized entity_id form ("Kueche" from "light.kueche").
    assert LIGHT_KUECHE in index.by_normalized_alias["kueche"]


def test_empty_entities_yields_empty_index():
    index = build_entity_index([])
    assert index.by_domain == {}
    assert index.by_area == {}
    assert index.by_normalized_name == {}
    assert index.by_normalized_alias == {}
