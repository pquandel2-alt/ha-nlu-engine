from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from ha_nlu.entities import EntitySnapshot
from ha_nlu.history_query import (
    HistoryMetric,
    ComparativeHistoryQuery,
    StateHistoryMetric,
    async_execute_history_query,
    parse_history_query,
    render_history_result,
    render_state_history_result,
)


NOW = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
SENSOR = EntitySnapshot(
    "sensor.wohnzimmer_temperatur", "Wohnzimmer Temperatur", "sensor", "22",
    unit="°C", device_class="temperature",
)


@pytest.mark.parametrize(
    ("text", "metric"),
    (
        ("Wie hoch war die Wohnzimmer Temperatur gestern im Durchschnitt?", HistoryMetric.MEAN),
        ("Was war das Maximum der Wohnzimmer Temperatur heute?", HistoryMetric.MAX),
        ("Welches Minimum hatte die Wohnzimmer Temperatur diese Woche?", HistoryMetric.MIN),
        ("Wie viel hat Wohnzimmer Energie letzte Woche verbraucht?", HistoryMetric.CHANGE),
    ),
)
def test_history_metric_and_period_are_composed(text, metric):
    entities = [SENSOR]
    if "Energie" in text:
        entities = [EntitySnapshot("sensor.energy", "Wohnzimmer Energie", "sensor", "10", unit="kWh")]
    query = parse_history_query(text, entities, NOW)
    assert query is not None
    assert query.metric is metric
    assert query.start < query.end


def test_history_query_requires_explicit_sensor_and_period():
    assert parse_history_query("Wie war der Durchschnitt gestern?", [SENSOR], NOW) is None
    assert parse_history_query("Wie ist die Wohnzimmer Temperatur?", [SENSOR], NOW) is None


def test_binary_state_history_count_and_duration_are_composed():
    window = EntitySnapshot(
        "binary_sensor.window", "Badezimmer Fenster", "binary_sensor", "off"
    )
    count = parse_history_query(
        "Wie oft war das Badezimmer Fenster gestern offen?", [window], NOW
    )
    duration = parse_history_query(
        "Wie lange war das Badezimmer Fenster heute geöffnet?", [window], NOW
    )

    assert count is not None and count.metric is StateHistoryMetric.COUNT
    assert duration is not None and duration.metric is StateHistoryMetric.DURATION


def test_period_comparison_is_composed_without_fixed_word_order():
    query = parse_history_query(
        "War die Wohnzimmer Temperatur gestern niedriger als heute?", [SENSOR], NOW
    )

    assert isinstance(query, ComparativeHistoryQuery)
    assert query.first[3] == "heute"
    assert query.second[3] == "gestern"


def test_state_history_result_counts_transitions_and_sums_duration():
    window = EntitySnapshot(
        "binary_sensor.window", "Badezimmer Fenster", "binary_sensor", "off"
    )
    query = parse_history_query(
        "Wie oft war das Badezimmer Fenster gestern offen?", [window], NOW
    )
    assert query is not None
    rows = {
        window.entity_id: [
            {"state": "off"},
            {"state": "on"},
            {"state": "off"},
            {"state": "on"},
        ]
    }
    assert "2-mal offen" in render_state_history_result(query, rows)


def test_history_result_is_aggregated_defensively():
    query = parse_history_query(
        "Wohnzimmer Temperatur gestern im Durchschnitt", [SENSOR], NOW
    )
    assert query is not None
    text = render_history_result(query, {
        SENSOR.entity_id: [{"mean": 20.0}, {"mean": 22.0}],
    })
    assert "21 °C" in text


def test_recorder_unavailable_degrades_cleanly():
    query = parse_history_query(
        "Wohnzimmer Temperatur gestern im Durchschnitt", [SENSOR], NOW
    )
    assert query is not None

    class Services:
        async def async_call(self, *args, **kwargs):
            raise RuntimeError("recorder disabled")

    hass = type("Hass", (), {"services": Services()})()
    assert "nicht verfügbar" in asyncio.run(async_execute_history_query(hass, query))
