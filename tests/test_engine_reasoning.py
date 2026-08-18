"""ReasoningEngine (V6.25/26) wired centrally into
``NluEngine._build_match_result`` - additive/observational only, see
``MatchResult.resolved_intent``'s own docstring in engine.py. This test
proves the wiring is real (the field gets populated for a live match), not
that it drives any response/plan - it doesn't.
"""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot

TWO_ROOM_HOUSE = [
    EntitySnapshot(
        "light.wohnzimmer_a", "Wohnzimmerlicht A", "light", "off",
        area_id="wohnzimmer", area_name="Wohnzimmer",
    ),
    EntitySnapshot(
        "light.wohnzimmer_b", "Wohnzimmerlicht B", "light", "off",
        area_id="wohnzimmer", area_name="Wohnzimmer",
    ),
    EntitySnapshot(
        "light.kueche", "Küchenlicht", "light", "off",
        area_id="kueche", area_name="Küche",
    ),
]

TWO_FLOOR_HOUSE = [
    EntitySnapshot(
        "light.wohnzimmer", "Wohnzimmerlicht", "light", "off",
        area_id="wohnzimmer", area_name="Wohnzimmer",
        floor_id="erdgeschoss", floor_name="Erdgeschoss", floor_level=0,
    ),
    EntitySnapshot(
        "light.buero", "Bürolicht", "light", "off",
        area_id="buero", area_name="Büro",
        floor_id="obergeschoss", floor_name="Obergeschoss", floor_level=1,
    ),
]


def test_resolved_intent_populated_for_simple_command(engine):
    # Area+domain-scoped ("alle Lichter im Wohnzimmer"), not a bare
    # name lookup: ReasoningEngine.resolve() only ever composes
    # domain/device_class/area constraints (via constraint_resolver), it
    # never does the parser's own name-scoring - so a named-entity command
    # (e.g. "das Wohnzimmer Regal") would legitimately diverge (matches
    # every light in the house, not just the named one). This case is
    # constraint-shaped, so both paths land on the same set.
    result = engine.match("mach alle Lichter im Wohnzimmer an", TWO_ROOM_HOUSE)
    assert result is not None
    assert result.resolved_intent is not None
    assert {e.entity_id for e in result.resolved_intent.entities} == {
        e.entity_id for e in result.command.entities
    }
    assert {e.entity_id for e in result.command.entities} == {
        "light.wohnzimmer_a", "light.wohnzimmer_b",
    }


def test_resolved_intent_diverges_from_matched_entities_on_current_turn_floor(engine):
    # Known, documented limitation (see MatchResult.resolved_intent's own
    # docstring): SemanticFrame has no floor field, so ReasoningEngine can't
    # see "oben" from this sentence - it re-resolves without any floor
    # constraint and picks up every light in the house, not just the
    # upstairs one the spoken command actually targets. Purely observational
    # (resolved_intent drives nothing), so this is not a user-visible
    # regression - just a recorded gap.
    result = engine.match("mach alle Lichter oben an", TWO_FLOOR_HOUSE)
    assert result is not None
    assert result.plan.entity_id == "light.buero"
    assert result.resolved_intent is not None
    assert {e.entity_id for e in result.resolved_intent.entities} == {
        "light.wohnzimmer", "light.buero",
    }
