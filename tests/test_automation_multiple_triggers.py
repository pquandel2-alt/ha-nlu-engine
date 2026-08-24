from ha_nlu.engine import NluEngine
from ha_nlu.entities import EntitySnapshot


def test_two_alternative_state_triggers_are_preserved_with_ids():
    entities = [
        EntitySnapshot("binary_sensor.window", "Bürofenster", "binary_sensor", "off", device_class="window"),
        EntitySnapshot("binary_sensor.door", "Bürotür", "binary_sensor", "off", device_class="door"),
        EntitySnapshot("light.office", "Bürolicht", "light", "off", capabilities=frozenset({"TURN_ON"})),
    ]
    result = NluEngine().match_automation(
        "Wenn das Bürofenster geöffnet wird oder wenn die Bürotür geöffnet wird, schalte das Bürolicht ein",
        entities,
    )
    assert result is not None and result.validation_error is None
    assert len(result.model.triggers) == 2
    assert [item.trigger_id for item in result.model.triggers] == ["ausloeser_1", "ausloeser_2"]
