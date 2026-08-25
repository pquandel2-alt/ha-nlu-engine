import pytest

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


@pytest.mark.parametrize(
    ("text", "service"),
    (
        ("Kannst du es bitte pausieren?", "media_pause"),
        ("Bitte jetzt damit weiterspielen", "media_play"),
        ("Und das Ganze stoppen", "media_stop"),
    ),
)
def test_media_followup_is_composed_from_operation_and_context(text, service):
    player = EntitySnapshot("media_player.wohnzimmer", "Wohnzimmer TV", "media_player", "playing")
    result = match_device_control_followup(text, _context(player))

    assert result is not None
    assert result.plan.service == service


@pytest.mark.parametrize(
    ("text", "service"),
    (
        ("Den bitte pausieren", "pause"),
        ("Und jetzt zur Station", "return_to_base"),
        ("Kannst du ihn wieder starten?", "start"),
    ),
)
def test_vacuum_followup_is_composed_from_operation_and_context(text, service):
    vacuum = EntitySnapshot("vacuum.helfer", "Saugroboter", "vacuum", "cleaning")
    result = match_device_control_followup(text, _context(vacuum))

    assert result is not None
    assert result.plan.service == service


def test_conflicting_or_conditional_followup_is_never_executed():
    player = EntitySnapshot("media_player.wohnzimmer", "Wohnzimmer TV", "media_player", "playing")
    assert match_device_control_followup("Pausiere und stoppe es", _context(player)) is None
    assert match_device_control_followup(
        "Pausiere es wenn das Telefon klingelt", _context(player)
    ) is None
