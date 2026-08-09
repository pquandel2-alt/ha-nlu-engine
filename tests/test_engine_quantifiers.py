"""'alle'/'beide' quantifiers over a whole domain, optionally scoped to a room."""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot

from conftest import POLERAUM_COVERS


def test_beide_rollladen_im_poleraum_hoch(engine, quantifier_entities):
    # Verbatim regression case from the real-world bug report.
    result = engine.match("Fahre beide Rollladen im Poleraum hoch", quantifier_entities)
    assert result is not None
    assert result.plan.domain == "cover"
    assert result.plan.service == "open_cover"
    assert sorted(result.plan.entity_id) == sorted(e.entity_id for e in POLERAUM_COVERS)


def test_alle_rolladen_hoch(engine, quantifier_entities):
    # Verbatim regression case (note: single-l "Rolladen" misspelling).
    result = engine.match("fahre alle Rolladen hoch", quantifier_entities)
    assert result is not None
    assert result.plan.domain == "cover"
    assert result.plan.service == "open_cover"
    expected = sorted(e.entity_id for e in quantifier_entities if e.domain == "cover")
    assert sorted(result.plan.entity_id) == expected


def test_alle_lichter_aus_whole_house(engine, entities):
    result = engine.match("mach alle Lichter aus", entities)
    assert result is not None
    assert result.plan.domain == "homeassistant"
    assert result.plan.service == "turn_off"
    expected = sorted(e.entity_id for e in entities if e.domain == "light")
    assert sorted(result.plan.entity_id) == expected


def test_alle_lichter_im_buro_room_scoped(engine):
    entities = [
        EntitySnapshot("light.a", "Deckenlicht", "light", "off", area_id="buro", area_name="Büro"),
        EntitySnapshot("light.b", "Stehlampe", "light", "off", area_id="buro", area_name="Büro"),
        EntitySnapshot("light.c", "Küchenlicht", "light", "off", area_id="kueche", area_name="Küche"),
    ]
    result = engine.match("mach alle Lichter im Büro aus", entities)
    assert result is not None
    assert sorted(result.plan.entity_id) == ["light.a", "light.b"]


def test_beide_rejects_single_match_in_room(engine):
    entities = [
        EntitySnapshot("cover.a", "Rolllade", "cover", "closed", area_id="gaeste", area_name="Gästezimmer"),
    ]
    result = engine.match("fahre beide Rollladen im Gästezimmer hoch", entities)
    assert result is None


def test_beide_rejects_triple_match_in_room(engine):
    entities = [
        EntitySnapshot("cover.a", "Rolllade 1", "cover", "closed", area_id="wohnzimmer", area_name="Wohnzimmer"),
        EntitySnapshot("cover.b", "Rolllade 2", "cover", "closed", area_id="wohnzimmer", area_name="Wohnzimmer"),
        EntitySnapshot("cover.c", "Rolllade 3", "cover", "closed", area_id="wohnzimmer", area_name="Wohnzimmer"),
    ]
    result = engine.match("fahre beide Rollladen im Wohnzimmer hoch", entities)
    assert result is None


def test_unknown_room_returns_none(engine, quantifier_entities):
    result = engine.match("mach alle Lichter im Bunker aus", quantifier_entities)
    assert result is None


def test_domain_with_no_matches_in_room_returns_none(engine):
    entities = [
        EntitySnapshot("light.a", "Deckenlicht", "light", "off", area_id="keller", area_name="Keller"),
    ]
    result = engine.match("fahre alle Rollläden im Keller hoch", entities)
    assert result is None
