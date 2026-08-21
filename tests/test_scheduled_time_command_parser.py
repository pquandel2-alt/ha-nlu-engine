"""Date-bound one-shot command parsing and confirmation-time resolution."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.action_model import ActionType
from ha_nlu.nlu.automation_model import (
    CalendarReference,
    TriggerType,
    resolve_pending_schedule,
)

ENTITIES = [
    EntitySnapshot(
        "light.kueche_licht",
        "Küchenlicht",
        "light",
        "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "cover.wohnzimmer_rollladen",
        "Wohnzimmer Rollladen",
        "cover",
        "closed",
        capabilities=frozenset({"POSITION"}),
    ),
]


@pytest.mark.parametrize(
    ("sentence", "now", "expected"),
    [
        (
            "Morgen um 8 Uhr schalte das Küchenlicht ein",
            datetime(2026, 8, 21, 12, 0),
            datetime(2026, 8, 22, 8, 0),
        ),
        (
            "Heute Abend um 20 Uhr schalte das Küchenlicht ein",
            datetime(2026, 8, 21, 12, 0),
            datetime(2026, 8, 21, 20, 0),
        ),
        (
            "Am Samstag um 10 Uhr schalte das Küchenlicht ein",
            datetime(2026, 8, 21, 12, 0),
            datetime(2026, 8, 22, 10, 0),
        ),
        (
            "Am 25. August um 18 Uhr schalte das Küchenlicht ein",
            datetime(2026, 8, 21, 12, 0),
            datetime(2026, 8, 25, 18, 0),
        ),
        (
            "Übermorgen früh schalte das Küchenlicht ein",
            datetime(2026, 8, 21, 12, 0),
            datetime(2026, 8, 23, 8, 0),
        ),
        (
            "Am nächsten Werktag um 8 Uhr schalte das Küchenlicht ein",
            datetime(2026, 8, 21, 12, 0),
            datetime(2026, 8, 24, 8, 0),
        ),
    ],
)
def test_calendar_phrases_become_date_guarded_once_models(
    engine, sentence, now, expected
):
    result = engine.match_calendar_time_automation(sentence, ENTITIES)

    assert result is not None
    assert result.validation_error is None
    assert result.model.once is True
    assert result.model.triggers[0].type is TriggerType.CALENDAR_TIME
    scheduled = resolve_pending_schedule(result.model, now)
    assert scheduled.scheduled_for == expected
    assert scheduled.triggers[0].type is TriggerType.TIME


def test_calendar_phrase_can_sit_inside_the_device_command(engine):
    result = engine.match_calendar_time_automation(
        "Fahre morgen um 8 Uhr die Wohnzimmer Rolllade auf 40 Prozent",
        ENTITIES,
    )

    assert result is not None
    assert result.model.actions[0].type is ActionType.SET_POSITION
    assert result.model.actions[0].value == 40


def test_weekday_today_rolls_to_next_week_after_the_requested_time(engine):
    result = engine.match_calendar_time_automation(
        "Am Freitag um 10 Uhr schalte das Küchenlicht ein", ENTITIES
    )
    scheduled = resolve_pending_schedule(
        result.model, datetime(2026, 8, 21, 12, 0)
    )
    assert scheduled.scheduled_for == datetime(2026, 8, 28, 10, 0)


def test_explicit_today_in_the_past_is_rejected(engine):
    result = engine.match_calendar_time_automation(
        "Heute um 8 Uhr schalte das Küchenlicht ein", ENTITIES
    )
    with pytest.raises(ValueError, match="Vergangenheit"):
        resolve_pending_schedule(result.model, datetime(2026, 8, 21, 12, 0))


def test_nonexistent_dst_wall_time_is_rejected(engine):
    result = engine.match_calendar_time_automation(
        "Am 29. März 2026 um 2:30 Uhr schalte das Küchenlicht ein", ENTITIES
    )
    with pytest.raises(ValueError, match="Zeitumstellung"):
        resolve_pending_schedule(
            result.model,
            datetime(2026, 3, 1, 12, 0, tzinfo=ZoneInfo("Europe/Berlin")),
        )


def test_calendar_schedule_keeps_semantic_reference_until_confirmation(engine):
    result = engine.match_calendar_time_automation(
        "Morgen um 8 Uhr schalte das Küchenlicht ein", ENTITIES
    )
    assert result.model.calendar_schedule.reference is CalendarReference.TOMORROW


def test_compound_relative_duration_is_summed(engine):
    result = engine.match_relative_time_automation(
        "In zwei Stunden und 30 Minuten schalte das Küchenlicht ein", ENTITIES
    )
    assert result is not None
    assert result.model.triggers[0].relative_offset_seconds == 9_000


def test_imprecise_day_period_requests_an_exact_time(engine):
    feedback = engine.understanding_feedback(
        "Morgen gegen Abend schalte das Küchenlicht ein", ENTITIES
    )
    assert feedback.speech == "Bitte nenne für diesen Auftrag eine genaue Uhrzeit."


def test_unconfirmed_calendar_automation_can_be_rescheduled_by_dialog(engine):
    original = engine.match_calendar_time_automation(
        "Morgen um 8 Uhr schalte das Küchenlicht ein", ENTITIES
    )
    revised = engine.revise_pending_automation(
        "Verschiebe die Uhrzeit auf 9:30 Uhr", original.model, ENTITIES
    )

    assert revised.model.calendar_schedule.hour == 9
    assert revised.model.calendar_schedule.minute == 30
