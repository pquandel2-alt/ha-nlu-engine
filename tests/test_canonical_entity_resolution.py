from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.entity_resolution import resolve_query_targets


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
