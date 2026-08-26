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


@pytest.mark.parametrize(
    ("entity", "text", "service", "data"),
    (
        (
            EntitySnapshot(
                "climate.buero", "Heizung Büro", "climate", "heat",
                attributes={"hvac_modes": ["heat", "auto"]},
            ),
            "Und jetzt auf Automatik",
            "set_hvac_mode",
            {"hvac_mode": "auto"},
        ),
        (
            EntitySnapshot(
                "select.profil", "Heizprofil", "select", "Komfort",
                attributes={"options": ["Eco", "Komfort"]},
            ),
            "Und jetzt Eco",
            "select_option",
            {"option": "Eco"},
        ),
        (
            EntitySnapshot(
                "humidifier.bad", "Luftbefeuchter Bad", "humidifier", "on",
                attributes={"min_humidity": 30, "max_humidity": 80},
            ),
            "Und auf 45 Prozent Luftfeuchtigkeit",
            "set_humidity",
            {"humidity": 45},
        ),
    ),
)
def test_followup_reuses_capability_parser_for_all_registered_properties(
    entity, text, service, data
):
    result = match_device_control_followup(text, _context(entity), [entity])

    assert result is not None
    assert result.plan is not None
    assert result.plan.service == service
    assert result.plan.data == data


def test_followup_never_redirects_a_different_named_entity_to_old_context():
    old = EntitySnapshot(
        "media_player.wohnzimmer", "Radio Wohnzimmer", "media_player", "playing"
    )
    new = EntitySnapshot(
        "media_player.schlafzimmer", "Radio Schlafzimmer", "media_player", "playing"
    )

    assert match_device_control_followup(
        "Pausiere das Radio Schlafzimmer", _context(old), [old, new]
    ) is None
