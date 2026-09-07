from datetime import datetime, timedelta, timezone

from ha_nlu.situation import (
    EventQuality,
    EventType,
    NormalizedEvent,
    RoutineStatistics,
)


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(index: int, hour: int, *, entity_id: str = "light.test") -> NormalizedEvent:
    occurred = START + timedelta(days=index)
    occurred = occurred.replace(hour=hour)
    return NormalizedEvent(
        f"evt-{entity_id}-{index}", EventType.ACTIVATED, entity_id, "off", "on",
        occurred, "living", (), True, "home", "home_assistant", EventQuality.GOOD,
        duration_seconds=60 + index,
    )


def test_detects_explainable_distribution_drift():
    stats = RoutineStatistics(minimum_observations=5)
    for index in range(20):
        stats.observe(_event(index, 8))
    for index in range(20, 30):
        stats.observe(_event(index, 22))

    drift = stats.drift_assessment(recent_window=10)

    assert drift.drifted
    assert drift.score == 1.0
    assert "statistische Vermutung" in drift.explanation


def test_temporal_correlation_is_explicitly_non_causal():
    first = RoutineStatistics(minimum_observations=3)
    second = RoutineStatistics(minimum_observations=3)
    for index in range(5):
        first.observe(_event(index, 8, entity_id="binary_sensor.motion"))
        second.observe(_event(index, 8, entity_id="light.room"))

    result = first.correlation_with(second)

    assert result.paired_observations == 5
    assert result.support == 1.0
    assert "keine Ursache" in result.explanation


def test_simulation_does_not_consume_cooldown_or_hysteresis_state():
    stats = RoutineStatistics(minimum_observations=3, anomaly_threshold=0.5)
    for index in range(3):
        stats.observe(_event(index, 8))
    unusual = _event(10, 23)

    preview = stats.simulate(unusual)
    committed = stats.assess(unusual)

    assert preview.unusual
    assert committed.unusual
    assert stats.last_alert_at == unusual.occurred_at
