from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.context import ConversationContext
from ha_nlu.nlu.dialog_focus import derive_dialog_focus


def _context(result):
    command = result.command
    return ConversationContext(
        last_command=command,
        last_entities=tuple(command.entities),
        last_area=command.area,
        pending_clarification=None,
        focus=derive_dialog_focus(command),
    )


def test_explicit_location_correction_retargets_previous_action(engine):
    entities = [
        EntitySnapshot(
            "light.kueche", "Küchenlicht", "light", "off",
            area_id="kueche", area_name="Küche",
            capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
        ),
        EntitySnapshot(
            "light.buero", "Bürolicht", "light", "off",
            area_id="buero", area_name="Büro",
            capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
        ),
    ]
    first = engine.match("Mach Küchenlicht an", entities)

    corrected = engine.match_correction_followup(
        "Nein, nicht Küche sondern Büro", entities, _context(first)
    )

    assert corrected.plan.entity_id == "light.buero"
    assert corrected.plan.service == "turn_on"


def test_unknown_correction_location_is_explained_without_action(engine, entities):
    first = engine.match("Mach Rollladen Büro auf", entities)
    result = engine.match_correction_followup(
        "Nein, ich meinte Wintergarten", entities, _context(first)
    )

    assert result.plan is None
    assert "keinen Raum und keine Etage" in result.response_text


def test_explicit_entity_correction_keeps_previous_action(engine):
    entities = [
        EntitySnapshot(
            "light.kueche", "Küchenlicht", "light", "off",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
        EntitySnapshot(
            "light.flur", "Flurlicht", "light", "off",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
    ]
    first = engine.match("Mach Küchenlicht an", entities)

    corrected = engine.match_correction_followup(
        "Nein, nicht Küchenlicht sondern Flurlicht", entities, _context(first)
    )

    assert corrected.plan.entity_id == "light.flur"
    assert corrected.plan.service == "turn_on"


def test_explicit_entity_correction_accepts_only_article(engine):
    entities = [
        EntitySnapshot(
            "light.wohnzimmer", "Wohnzimmerlicht", "light", "off",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
        EntitySnapshot(
            "light.floor", "Stehlampe", "light", "off",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
    ]
    first = engine.match("Mach das Wohnzimmerlicht an", entities)
    corrected = engine.match_correction_followup(
        "Nein, ich meinte nur die Stehlampe.", entities, _context(first)
    )
    assert corrected.plan.entity_id == "light.floor"


def test_short_negative_correction_retargets_without_repeating_action(engine):
    entities = [
        EntitySnapshot(
            "light.kueche", "Küchenlicht", "light", "off",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
        EntitySnapshot(
            "light.flur", "Flurlicht", "light", "off",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
    ]
    first = engine.match("Mach Küchenlicht an", entities)

    corrected = engine.match_correction_followup(
        "Nein, das Flurlicht", entities, _context(first)
    )

    assert corrected.plan.entity_id == "light.flur"
    assert corrected.plan.service == "turn_on"


def test_group_correction_preserves_all_quantifier_for_new_floor(engine):
    entities = [
        EntitySnapshot(
            "light.eg_1", "Küchenlicht", "light", "off",
            floor_id="eg", floor_name="Erdgeschoss",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
        EntitySnapshot(
            "light.eg_2", "Flurlicht", "light", "off",
            floor_id="eg", floor_name="Erdgeschoss",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
        EntitySnapshot(
            "light.dg_1", "Schlafzimmerlicht", "light", "off",
            floor_id="dg", floor_name="Dachgeschoss",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
        EntitySnapshot(
            "light.dg_2", "Badlicht oben", "light", "off",
            floor_id="dg", floor_name="Dachgeschoss",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
    ]
    first = engine.match("Schalte alle Lichter im Erdgeschoss an", entities)

    corrected = engine.match_correction_followup(
        "Nein, ich meinte Dachgeschoss", entities, _context(first)
    )

    assert corrected.plan.entity_id == ["light.dg_1", "light.dg_2"]
    assert corrected.plan.service == "turn_on"
