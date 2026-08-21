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
