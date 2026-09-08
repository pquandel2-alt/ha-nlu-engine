from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.discourse import (
    DiscourseRole,
    ReferenceStatus,
    remember_entities,
    resolve_reference,
)


LIGHT_A = EntitySnapshot(
    "light.wohnen", "Wohnzimmerlicht", "light", "on",
    area_id="living", floor_id="ground",
)
LIGHT_B = EntitySnapshot(
    "light.schlafen", "Schlafzimmerlicht", "light", "off",
    area_id="bedroom", floor_id="upper",
)


def test_salience_tracks_more_than_the_last_entity():
    first = remember_entities(None, (LIGHT_A,), role=DiscourseRole.QUERY_RESULT)
    second = remember_entities(first, (LIGHT_B,), role=DiscourseRole.QUERY_RESULT)

    assert {item.entity_id for item in second.referents} == {
        LIGHT_A.entity_id, LIGHT_B.entity_id
    }
    resolved = resolve_reference("mach es dort aus", second, (LIGHT_A, LIGHT_B))
    assert resolved.status is ReferenceStatus.RESOLVED
    assert resolved.entities == (LIGHT_B,)


def test_equal_salience_never_chooses_a_singular_reference():
    state = remember_entities(
        None, (LIGHT_A, LIGHT_B), role=DiscourseRole.QUERY_RESULT
    )

    result = resolve_reference("mach es aus", state, (LIGHT_A, LIGHT_B))
    assert result.status is ReferenceStatus.AMBIGUOUS
    assert result.margin == 0
    assert {item.entity_id for item in result.entities} == {
        LIGHT_A.entity_id, LIGHT_B.entity_id
    }


def test_grounding_never_resurrects_entity_missing_from_live_registry():
    state = remember_entities(None, (LIGHT_A,), role=DiscourseRole.ACTION_TARGET)

    assert resolve_reference("mach es aus", state, ()).status is ReferenceStatus.NOT_FOUND
