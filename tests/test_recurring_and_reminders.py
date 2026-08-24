from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.action_model import ActionType
from ha_nlu.nlu.automation_model import TriggerType, resolve_pending_schedule
from ha_nlu.nlu.condition_model import ConditionType
from ha_nlu.nlu.ha_automation_generator import generate_ha_automation_config
from ha_nlu.reminder import reminder_automation_text, reminder_quiet_hours


LIGHT = EntitySnapshot(
    "light.kueche", "Küchenlicht", "light", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
WINDOW = EntitySnapshot(
    "binary_sensor.kuechenfenster", "Küchenfenster", "binary_sensor", "off",
    device_class="window", capabilities=frozenset(),
)


def test_relative_reminder_reuses_one_shot_notification_pipeline(engine):
    rewritten = reminder_automation_text(
        "Erinnere mich in fünf Minuten an die Waschmaschine"
    )
    assert rewritten == "in fünf Minuten sende mir eine Nachricht dass die Waschmaschine"
    result = engine.match_relative_time_automation(rewritten, [LIGHT])
    assert result is not None
    assert result.model.once is True
    assert result.model.actions[0].type is ActionType.NOTIFY


def test_explicit_quiet_hours_shift_one_shot_to_end_instead_of_losing_it(engine):
    text = (
        "Erinnere mich in fünf Minuten an die Waschmaschine "
        "aber nicht zwischen 22 und 7 Uhr"
    )
    rewritten = reminder_automation_text(text)
    quiet = reminder_quiet_hours(text)
    result = engine.match_relative_time_automation(rewritten, [LIGHT])
    model = replace(
        result.model,
        quiet_start_hour=quiet[0],
        quiet_end_hour=quiet[1],
    )
    resolved = resolve_pending_schedule(model, datetime(2026, 8, 24, 22, 30))
    assert resolved.scheduled_for == datetime(2026, 8, 25, 7, 0)


def test_weekday_recurrence_is_time_trigger_plus_native_weekday_condition(engine):
    result = engine.match_recurring_time_automation(
        "Jeden Werktag um 7 Uhr schalte das Küchenlicht ein",
        [LIGHT], datetime(2026, 8, 24, 12),
    )
    assert result is not None and result.validation_error is None
    assert result.model.triggers[0].type is TriggerType.TIME
    condition = result.model.conditions[0].condition
    assert condition.type is ConditionType.WEEKDAY
    assert condition.weekdays == ("mon", "tue", "wed", "thu", "fri")


def test_every_second_week_gets_creation_time_anchor(engine):
    result = engine.match_recurring_time_automation(
        "Jeden zweiten Samstag um 10 Uhr schalte das Küchenlicht ein",
        [LIGHT], datetime(2026, 8, 24, 12),
    )
    assert result is not None
    assert result.model.conditions[1].condition.type is ConditionType.TEMPLATE


def test_recurring_rule_can_be_limited_to_wrapping_month_range(engine):
    result = engine.match_recurring_time_automation(
        "Jeden Montag um 8 Uhr nur zwischen Oktober und März schalte das Küchenlicht ein",
        [LIGHT], datetime(2026, 8, 24, 12),
    )
    assert result is not None and result.validation_error is None
    template = result.model.conditions[1].condition.raw_state
    assert "now().month >= 10" in template
    assert "now().month <= 3" in template


def test_state_must_remain_true_uses_trigger_for_not_delay(engine):
    result = engine.match_persistent_state_automation(
        "Wenn das Küchenfenster zehn Minuten offen bleibt, schalte das Küchenlicht ein",
        [WINDOW, LIGHT],
    )
    assert result is not None and result.validation_error is None
    assert result.model.triggers[0].for_seconds == 600
    assert result.model.triggers[0].delay_seconds is None


def test_same_state_event_twice_within_window_uses_bounded_wait(engine):
    result = engine.match_repeated_event_automation(
        "Wenn das Küchenfenster innerhalb von fünf Minuten zweimal geöffnet wird, schalte das Küchenlicht ein",
        [WINDOW, LIGHT],
    )
    assert result is not None and result.validation_error is None
    assert result.model.triggers[0].repeat_within_seconds == 300
    generated = generate_ha_automation_config(result.model, [WINDOW, LIGHT])
    assert generated.error is None
    assert generated.config["actions"][0]["timeout"] == {"seconds": 300}
    assert generated.config["actions"][0]["continue_on_timeout"] is False
