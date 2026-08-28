from __future__ import annotations

from ha_nlu.entities import EntitySnapshot, build_entity_index
from ha_nlu.nlu.entity_resolution import (
    ResolutionStatus,
    rank_semantic_targets,
    resolve_mentioned_target,
    resolve_named_target,
    resolve_query_targets,
)


ENTITIES = [
    EntitySnapshot(
        "media_player.wohnzimmer", "Radio Wohnzimmer", "media_player", "playing",
        area_id="wohnzimmer", area_name="Wohnzimmer", aliases=("Stereo",),
    ),
    EntitySnapshot(
        "media_player.kueche", "Radio Küche", "media_player", "paused",
        area_id="kueche", area_name="Küche",
    ),
]


def test_canonical_query_resolution_handles_explicit_and_group_targets():
    explicit = resolve_query_targets(
        "Spielt Stereo?", ENTITIES, frozenset({"media_player"})
    )
    group = resolve_query_targets(
        "Spielen die Radios?", ENTITIES, frozenset({"media_player"})
    )

    assert explicit[0].entity_id == "media_player.wohnzimmer"
    assert len(group) == 2


def test_named_and_embedded_target_resolution_share_domain_constraints():
    named = resolve_named_target(
        "Stereo", ENTITIES, frozenset({"media_player"})
    )
    embedded = resolve_mentioned_target(
        "Pausiere bitte Stereo", ENTITIES, frozenset({"media_player"})
    )

    assert named.status is ResolutionStatus.RESOLVED
    assert embedded.status is ResolutionStatus.RESOLVED
    assert named.entity == embedded.entity == ENTITIES[0]


def test_semantic_ranking_prefers_complete_registry_name_over_longer_suffix_name():
    entities = [
        EntitySnapshot("light.island", "Kücheninsel", "light", "off"),
        EntitySnapshot(
            "switch.island", "Kücheninsel Steckdose", "switch", "off"
        ),
    ]

    ranked = rank_semantic_targets(
        "Mach Kücheninsel an",
        entities,
        ignored_tokens=frozenset({"mach", "an"}),
    )

    assert ranked[0].entity.entity_id == "light.island"
    assert ranked[0].source == "friendly_name"
    assert ranked[0].score > ranked[1].score


def test_semantic_ranking_keeps_equal_names_tied_for_clarification():
    entities = [
        EntitySnapshot("light.one", "Leselicht", "light", "off"),
        EntitySnapshot("light.two", "Leselicht", "light", "off"),
    ]

    ranked = rank_semantic_targets("Leselicht an", entities)

    assert len(ranked) == 2
    assert ranked[0].score == ranked[1].score


def test_indexed_semantic_ranking_preserves_exact_name_and_alias_ties():
    entities = [
        EntitySnapshot("light.name", "Leselicht", "light", "off"),
        EntitySnapshot(
            "light.alias", "Sofalampe", "light", "off", aliases=("Leselicht",)
        ),
    ]
    kwargs = {
        "domains": frozenset({"light"}),
        "ignored_tokens": frozenset({"mach", "an"}),
    }

    scanned = rank_semantic_targets("Mach Leselicht an", entities, **kwargs)
    indexed = rank_semantic_targets(
        "Mach Leselicht an", entities, index=build_entity_index(entities), **kwargs
    )

    assert [(item.entity.entity_id, item.score) for item in indexed] == [
        (item.entity.entity_id, item.score) for item in scanned
    ]
