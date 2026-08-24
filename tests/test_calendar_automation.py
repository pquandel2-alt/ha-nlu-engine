from __future__ import annotations

from ha_nlu.calendar_automation import parse_calendar_automation_draft
from ha_nlu.engine import NluEngine
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.action_model import ActionType
from ha_nlu.nlu.automation_model import TriggerType
from ha_nlu.nlu.condition_model import ConditionType
from ha_nlu.nlu.ha_automation_generator import generate_ha_automation_config


CALENDAR = EntitySnapshot("calendar.familie", "Familienkalender", "calendar", "off")
LIGHT = EntitySnapshot(
    "light.flur", "Flurlicht", "light", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
)
ENTITIES = [CALENDAR, LIGHT]


def test_calendar_draft_understands_named_event_and_offset():
    draft = parse_calendar_automation_draft(
        "Zehn Minuten vor einem Arzttermin schalte das Flurlicht ein", ENTITIES
    )
    assert draft is not None
    assert draft.calendar_entity_id == CALENDAR.entity_id
    assert draft.event == "start"
    assert draft.offset_minutes == -10
    assert draft.summary_contains == "Arzt"
    assert draft.action_text == "schalte das Flurlicht ein"


def test_calendar_draft_resolves_named_calendar_and_variable_word_order():
    draft = parse_calendar_automation_draft(
        "Schalte das Flurlicht ein, wenn Urlaub im Familienkalender beginnt",
        ENTITIES,
    )
    assert draft is not None
    assert draft.calendar_entity_id == CALENDAR.entity_id
    assert draft.summary_contains == "Urlaub"
    assert draft.action_text == "Schalte das Flurlicht ein"


def test_calendar_automation_builds_trigger_title_filter_and_action():
    result = NluEngine().match_calendar_event_automation(
        "Zehn Minuten vor einem Arzttermin schalte das Flurlicht ein", ENTITIES
    )
    assert result is not None and result.validation_error is None
    assert result.model.triggers[0].type is TriggerType.CALENDAR
    assert result.model.conditions[0].condition.type is ConditionType.CALENDAR_EVENT
    assert result.model.actions[0].type is ActionType.TURN_ON

    generated = generate_ha_automation_config(result.model, ENTITIES)
    assert generated.error is None
    assert generated.config == {
        "alias": "Zehn Minuten vor einem Arzttermin schalte das Flurlicht ein",
        "triggers": [{
            "trigger": "calendar",
            "entity_id": CALENDAR.entity_id,
            "event": "start",
            "offset": "-00:10:00",
        }],
        "actions": [{
            "action": "homeassistant.turn_on",
            "target": {"entity_id": LIGHT.entity_id},
        }],
        "mode": "queued",
        "conditions": [{
            "condition": "template",
            "value_template": (
                "{{ \"arzt\" in (trigger.calendar_event.summary | default('', true) | lower) }}"
            ),
        }],
    }


def test_remind_me_creates_persistent_notification_action():
    result = NluEngine().match_calendar_event_automation(
        "Wenn der Termin Müllabfuhr beginnt, erinnere mich", ENTITIES
    )
    assert result is not None
    assert result.model.actions[0].type is ActionType.NOTIFY
    assert result.model.actions[0].message == "Kalendertermin Müllabfuhr beginnt."
