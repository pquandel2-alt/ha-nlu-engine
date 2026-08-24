from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from ha_nlu.entities import EntitySnapshot
from ha_nlu.history_query import (
    HistoryMetric,
    async_execute_history_query,
    parse_history_query,
    render_history_result,
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
