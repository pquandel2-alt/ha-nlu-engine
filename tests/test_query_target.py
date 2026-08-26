from ha_nlu.entities import EntitySnapshot
from ha_nlu.query_target import mentioned_entities, resolve_query_targets


def test_query_target_composes_domain_and_area_independent_of_name_order():
    entities = [
        EntitySnapshot(
            "climate.buero", "Heizung Büro", "climate", "heat",
            area_id="buero", area_name="Büro",
        ),
        EntitySnapshot(
            "climate.wohnzimmer", "Heizung Wohnzimmer", "climate", "heat",
            area_id="wohnzimmer", area_name="Wohnzimmer",
        ),
    ]

    result = resolve_query_targets(
        "Welche Modi hat im Büro eigentlich die Heizung?",
        entities,
        frozenset({"climate"}),
    )

    assert [entity.entity_id for entity in result] == ["climate.buero"]


def test_explicit_longest_name_wins_without_fuzzy_guessing():
    short = EntitySnapshot("media_player.radio", "Radio", "media_player", "idle")
    long = EntitySnapshot(
        "media_player.radio_kueche", "Radio Küche", "media_player", "idle"
    )

    assert mentioned_entities("Was kann Radio Küche?", [short, long]) == (long,)
