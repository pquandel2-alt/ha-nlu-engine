from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.entity_resolution import GroundingStatus, ground_entities


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


def test_canonical_grounding_reports_evidence_and_cardinality():
    explicit = ground_entities(
        "Spielt Stereo?", ENTITIES, frozenset({"media_player"})
    )
    group = ground_entities(
        "Spielen die Radios?", ENTITIES, frozenset({"media_player"})
    )

    assert explicit.status is GroundingStatus.RESOLVED
    assert explicit.entities[0].entity_id == "media_player.wohnzimmer"
    assert explicit.evidence == "explicit_name"
    assert group.status is GroundingStatus.GROUP
    assert len(group.entities) == 2
