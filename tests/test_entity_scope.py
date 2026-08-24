from ha_nlu.entities import EntitySnapshot
from ha_nlu.entity_scope import resolve_entity_scope
from ha_nlu.extended_device_control import match_extended_device_control
from ha_nlu.extended_device_query import match_extended_device_query
from ha_nlu.device_control import _mentioned_entity, _result


ENTITIES = [
    EntitySnapshot("humidifier.office", "Befeuchter Büro", "humidifier", "on", area_id="office", area_name="Büro", floor_id="upper", floor_name="Obergeschoss", attributes={"humidity": 50}),
    EntitySnapshot("humidifier.bed", "Befeuchter Schlafzimmer", "humidifier", "off", area_id="bed", area_name="Schlafzimmer", floor_id="upper", floor_name="Obergeschoss", attributes={"humidity": 45}),
    EntitySnapshot("input_boolean.guest", "Gastmodus", "input_boolean", "off", area_id="office", area_name="Büro"),
]


def test_scope_resolves_floor_independent_of_word_order():
    scope = resolve_entity_scope("Im Obergeschoss bitte alle Luftbefeuchter", ENTITIES, frozenset({"humidifier"}))
    assert scope is not None
    assert {item.entity_id for item in scope.entities} == {"humidifier.office", "humidifier.bed"}


def test_extended_group_control_uses_one_multi_target_plan():
    result = match_extended_device_control(
        "Schalte im Obergeschoss sämtliche Luftbefeuchter aus",
        ENTITIES,
        _mentioned_entity,
        _result,
    )
    assert result is not None and result.plan is not None
    assert result.plan.service == "turn_off"
    assert set(result.plan.entity_id) == {"humidifier.office", "humidifier.bed"}


def test_extended_area_query_reports_concrete_state():
    result = match_extended_device_query("Welche Luftbefeuchter sind im Büro an?", ENTITIES)
    assert result is not None and "Befeuchter Büro" in result.response_text


def test_extended_group_value_is_checked_for_every_target():
    result = match_extended_device_control(
        "Stelle alle Luftbefeuchter im Obergeschoss auf 55 Prozent Luftfeuchtigkeit",
        ENTITIES,
        _mentioned_entity,
        _result,
    )
    assert result is not None and result.plan is not None
    assert result.plan.service == "set_humidity"
    assert result.plan.data == {"humidity": 55}
