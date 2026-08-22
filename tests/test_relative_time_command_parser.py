"""Wave 13: delayed single-clause commands become one-shot automations."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.action_model import ActionType
from ha_nlu.nlu.automation_model import TriggerType, resolve_relative_schedule


ENTITIES = [
    EntitySnapshot(
        "cover.wohnzimmer_rollladen",
        "Wohnzimmer Rollladen",
        "cover",
        "closed",
        area_id="wohnzimmer",
        area_name="Wohnzimmer",
        capabilities=frozenset({"POSITION"}),
    ),
    EntitySnapshot(
        "light.kueche_licht",
        "Küchenlicht",
        "light",
        "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
]


def test_original_cover_command_becomes_a_once_time_automation(engine):
    result = engine.match_relative_time_automation(
        "Fahre in 5 Minuten die Wohnzimmer Rolllade auf 30%", ENTITIES
    )

    assert result is not None
    assert result.validation_error is None
    assert result.model.once is True
    assert result.model.triggers[0].type is TriggerType.RELATIVE_TIME
    assert result.model.triggers[0].relative_offset_seconds == 300
    assert result.model.actions[0].type is ActionType.SET_POSITION
    assert result.model.actions[0].value == 30


def test_seconds_offset_carries_across_midnight(engine):
    now = datetime(2026, 8, 21, 23, 59, 45)

    result = engine.match_relative_time_automation(
        "Fahre in 30 Sekunden die Wohnzimmer Rolllade auf 30 Prozent", ENTITIES
    )

    assert result is not None
    trigger = resolve_relative_schedule(result.model, now).triggers[0]
    assert (trigger.time_hour, trigger.time_minute, trigger.time_second) == (0, 0, 15)


def test_spelled_hour_and_prefix_word_order_are_supported(engine):
    result = engine.match_relative_time_automation(
        "In einer Stunde schalte das Küchenlicht ein",
        ENTITIES,
    )

    assert result is not None
    trigger = resolve_relative_schedule(
        result.model, datetime(2026, 8, 21, 12, 30, 0)
    ).triggers[0]
    assert (trigger.time_hour, trigger.time_minute, trigger.time_second) == (13, 30, 0)
    assert result.model.actions[0].type is ActionType.TURN_ON


def test_suffix_word_order_is_supported(engine):
    result = engine.match_relative_time_automation(
        "Schalte das Küchenlicht ein in 5 Minuten",
        ENTITIES,
    )

    assert result is not None
    assert result.model.actions[0].type is ActionType.TURN_ON


def test_reported_short_imperative_half_position_is_delayed_once(engine):
    entities = [
        EntitySnapshot(
            "cover.buero", "Rollade Büro", "cover", "open",
            area_id="buero", area_name="Büro",
            capabilities=frozenset({"POSITION"}),
        ),
    ]

    result = engine.match_relative_time_automation(
        "Fahr die Rollade im Büro in 30 Sekunden halb runter", entities
    )

    assert result is not None
    assert result.validation_error is None
    assert result.model.once is True
    assert result.model.triggers[0].relative_offset_seconds == 30
    assert result.model.actions[0].type is ActionType.SET_POSITION
    assert result.model.actions[0].target.area_id == "buero"
    assert result.model.actions[0].value == 50


def test_dst_jump_uses_elapsed_time_not_nonexistent_wall_time(engine):
    berlin = ZoneInfo("Europe/Berlin")
    now = datetime(2026, 3, 29, 1, 30, 0, tzinfo=berlin)

    result = engine.match_relative_time_automation(
        "In einer Stunde schalte das Küchenlicht ein", ENTITIES
    )

    assert result is not None
    trigger = resolve_relative_schedule(result.model, now).triggers[0]
    # 02:30 does not exist on this date; one elapsed hour later is 03:30.
    assert (trigger.time_hour, trigger.time_minute, trigger.time_second) == (3, 30, 0)


def test_offsets_beyond_one_day_are_safe_with_the_date_guard(engine):
    result = engine.match_relative_time_automation(
        "In 25 Stunden schalte das Küchenlicht ein",
        ENTITIES,
    )

    assert result is not None
    scheduled = resolve_relative_schedule(
        result.model, datetime(2026, 8, 21, 12, 0, 0)
    )
    assert scheduled.scheduled_for == datetime(2026, 8, 22, 13, 0, 0)


def test_non_temporal_command_does_not_enter_relative_automation_path(engine):
    assert (
        engine.match_relative_time_automation(
            "Schalte das Küchenlicht ein", ENTITIES
        )
        is None
    )
