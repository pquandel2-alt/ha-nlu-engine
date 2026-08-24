from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.action_model import ActionModel, ActionType
from ha_nlu.nlu.automation_model import AutomationModel, TriggerModel, TriggerTarget, TriggerType
from ha_nlu.nlu.condition_model import ConditionModel, ConditionNode, ConditionType
from ha_nlu.nlu.ha_automation_generator import generate_ha_automation_config
from ha_nlu.nlu.semantic_state import SemanticState


WINDOW = EntitySnapshot("binary_sensor.window", "Fenster", "binary_sensor", "off", device_class="window")
LIGHT = EntitySnapshot("light.office", "Bürolicht", "light", "off")
CALENDAR = EntitySnapshot("calendar.family", "Familie", "calendar", "on")


def test_trigger_ids_and_native_calendar_trigger_are_generated():
    model = AutomationModel(
        triggers=(TriggerModel(type=TriggerType.CALENDAR, calendar_entity_id=CALENDAR.entity_id, calendar_event="start", offset_minutes=-10, trigger_id="calendar_start"),),
        actions=(ActionModel(ActionType.TURN_ON, TriggerTarget(domain="light", entity_id=LIGHT.entity_id)),),
    )
    result = generate_ha_automation_config(model, [CALENDAR, LIGHT])
    assert result.error is None
    assert result.config["triggers"] == [{"trigger": "calendar", "entity_id": "calendar.family", "event": "start", "offset": "-00:10:00", "id": "calendar_start"}]


def test_structured_wait_condition_becomes_bounded_template():
    wait = ActionModel(
        ActionType.WAIT,
        wait_condition=ConditionNode(condition=ConditionModel(ConditionType.STATE, TriggerTarget(domain="binary_sensor", device_class="window", entity_id=WINDOW.entity_id), state=SemanticState.CLOSED)),
        timeout_seconds=300,
    )
    model = AutomationModel(
        triggers=(TriggerModel(TriggerType.TIME, time_hour=8),),
        actions=(wait, ActionModel(ActionType.TURN_ON, TriggerTarget(domain="light", entity_id=LIGHT.entity_id))),
    )
    result = generate_ha_automation_config(model, [WINDOW, LIGHT])
    assert result.error is None
    assert "is_state('binary_sensor.window', 'off')" in result.config["actions"][0]["wait_template"]
    assert result.config["actions"][0]["timeout"] == {"seconds": 300}


def test_choose_action_generates_native_if_then_else():
    condition = ConditionNode(condition=ConditionModel(
        ConditionType.STATE,
        TriggerTarget(domain="binary_sensor", device_class="window", entity_id=WINDOW.entity_id),
        state=SemanticState.CLOSED,
    ))
    choose = ActionModel(
        ActionType.CHOOSE,
        if_condition=condition,
        then_steps=(ActionModel(ActionType.TURN_ON, TriggerTarget(domain="light", entity_id=LIGHT.entity_id)),),
        else_steps=(ActionModel(ActionType.TURN_OFF, TriggerTarget(domain="light", entity_id=LIGHT.entity_id)),),
    )
    model = AutomationModel(
        triggers=(TriggerModel(TriggerType.TIME, time_hour=8),), actions=(choose,)
    )
    result = generate_ha_automation_config(model, [WINDOW, LIGHT])
    assert result.error is None
    assert result.config["actions"][0]["if"][0]["condition"] == "state"
    assert result.config["actions"][0]["then"][0]["action"] == "homeassistant.turn_on"
    assert result.config["actions"][0]["else"][0]["action"] == "homeassistant.turn_off"
