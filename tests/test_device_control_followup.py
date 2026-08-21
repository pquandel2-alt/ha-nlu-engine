from ha_nlu.device_control import match_device_control_followup
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.context import ConversationContext


def _context(entity):
    return ConversationContext(None, (entity,), None, None)


def test_media_followup_uses_last_device_without_repeating_name():
    player = EntitySnapshot("media_player.wohnzimmer", "Wohnzimmer TV", "media_player", "playing")
    result = match_device_control_followup("Pausiere es", _context(player))

    assert result.plan.service == "media_pause"
    assert result.plan.entity_id == player.entity_id


def test_vacuum_followup_can_return_to_base():
    vacuum = EntitySnapshot("vacuum.helfer", "Saugroboter", "vacuum", "cleaning")
    result = match_device_control_followup("Schick ihn zur Ladestation", _context(vacuum))

    assert result.plan.service == "return_to_base"
