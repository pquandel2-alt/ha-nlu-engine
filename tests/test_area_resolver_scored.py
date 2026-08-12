"""Phase 7 (v2 plan): Area Resolver 2.0 - resolve_area_scored(). Pins the
scoring tiers (exact, normalized exact, contains, reverse contains) and
ambiguity detection, mirroring test_resolver.py's coverage of
resolve_entity_scored (Phase 6). resolve_area_name() itself (the wrapper)
stays covered by test_area_resolution.py - those must keep passing
unchanged as the regression net for this rewrite."""

from __future__ import annotations

from ha_nlu.areas import AreaResolutionStatus, resolve_area_scored
from ha_nlu.entities import EntitySnapshot

POLERAUM_COVERS = [
    EntitySnapshot("cover.a", "Rolllade Poleraum links", "cover", "closed", area_id="poleraum", area_name="Poleraum"),
    EntitySnapshot("cover.b", "Rolllade Poleraum rechts", "cover", "closed", area_id="poleraum", area_name="Poleraum"),
    EntitySnapshot("cover.c", "Rolllade Büro", "cover", "closed", area_id="buro", area_name="Büro"),
]


def test_exact_match_scores_hundred():
    result = resolve_area_scored("Poleraum", POLERAUM_COVERS)
    assert result.status is AreaResolutionStatus.RESOLVED
    assert result.area.area_id == "poleraum"
    assert result.score == 100


def test_normalized_exact_scores_below_literal_exact():
    result = resolve_area_scored("büro", POLERAUM_COVERS)
    assert result.status is AreaResolutionStatus.RESOLVED
    assert result.area.area_id == "buro"
    assert result.score == 85


def test_contains_scores_fifty():
    # Spoken text is the shorter string here (contained *within* the area's
    # name) - the mirror image of test_reverse_contains_scores_forty, where
    # the area name is the shorter string.
    entities = [EntitySnapshot("cover.a", "Rolllade", "cover", "closed", area_id="poleraum", area_name="Poleraum Süd")]
    result = resolve_area_scored("Poleraum", entities)
    assert result.status is AreaResolutionStatus.RESOLVED
    assert result.area.area_id == "poleraum"
    assert result.score == 50


def test_reverse_contains_scores_forty():
    # Area name is the shorter string here (contained *within* the spoken
    # text) - the mirror image of test_contains_scores_fifty, where the
    # spoken text is the shorter string.
    entities = [EntitySnapshot("light.a", "Lampe", "light", "off", area_id="wz", area_name="Zimmer")]
    result = resolve_area_scored("Wohnzimmer Zimmer", entities)
    assert result.status is AreaResolutionStatus.RESOLVED
    assert result.score == 40


def test_ambiguous_when_scores_tied():
    entities = [
        EntitySnapshot("cover.a", "A", "cover", "closed", area_id="buro_oben", area_name="Büro"),
        EntitySnapshot("cover.b", "B", "cover", "closed", area_id="buro_unten", area_name="Büro"),
    ]
    result = resolve_area_scored("Büro", entities)
    assert result.status is AreaResolutionStatus.AMBIGUOUS
    assert len(result.candidates) == 2


def test_not_found():
    result = resolve_area_scored("Keller", POLERAUM_COVERS)
    assert result.status is AreaResolutionStatus.NOT_FOUND


def test_empty_name_not_found():
    assert resolve_area_scored("", POLERAUM_COVERS).status is AreaResolutionStatus.NOT_FOUND


def test_entities_without_area_are_ignored():
    entities = [EntitySnapshot("cover.a", "Rolllade", "cover", "closed")]
    result = resolve_area_scored("Poleraum", entities)
    assert result.status is AreaResolutionStatus.NOT_FOUND


# --- Area aliases (HA Area Registry ``aliases``, e.g. "draußen" -> "Garten") --

GARTEN_SENSORS = [
    EntitySnapshot(
        "binary_sensor.a", "Gartentür", "binary_sensor", "off",
        area_id="garten", area_name="Garten", area_aliases=("draußen", "Terrasse"),
    ),
    EntitySnapshot(
        "light.a", "Gartenlicht", "light", "off",
        area_id="garten", area_name="Garten", area_aliases=("draußen", "Terrasse"),
    ),
    EntitySnapshot("cover.a", "Rolllade Büro", "cover", "closed", area_id="buro", area_name="Büro"),
]


def test_exact_alias_match_resolves_area():
    result = resolve_area_scored("draußen", GARTEN_SENSORS)
    assert result.status is AreaResolutionStatus.RESOLVED
    assert result.area.area_id == "garten"
    assert result.score == 90


def test_exact_alias_scores_below_literal_area_name_match():
    result = resolve_area_scored("Garten", GARTEN_SENSORS)
    assert result.status is AreaResolutionStatus.RESOLVED
    assert result.score == 100


def test_alias_does_not_match_unrelated_area():
    result = resolve_area_scored("draußen", POLERAUM_COVERS)
    assert result.status is AreaResolutionStatus.NOT_FOUND


def test_second_alias_also_resolves_same_area():
    result = resolve_area_scored("Terrasse", GARTEN_SENSORS)
    assert result.status is AreaResolutionStatus.RESOLVED
    assert result.area.area_id == "garten"
