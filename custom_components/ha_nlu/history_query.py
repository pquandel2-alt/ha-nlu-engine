"""Bounded natural-language adapter for Home Assistant recorder statistics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, auto

from .entities import EntitySnapshot, generate_aliases, normalize_for_compare


class HistoryMetric(Enum):
    MEAN = auto()
    MIN = auto()
    MAX = auto()
    CHANGE = auto()


@dataclass(frozen=True)
class HistoryQuery:
    entity: EntitySnapshot
    metric: HistoryMetric
    start: datetime
    end: datetime
    period: str
    period_label: str


_HISTORY_CUE_RE = re.compile(
    r"\b(?:durchschnitt|mittelwert|minimum|niedrigst|kleinst|maximum|"
    r"hoechst|groesst|verbraucht|verbrauch|erzeugt|produziert)\w*\b"
)


def _mentioned_entity(text: str, entities: list[EntitySnapshot]) -> EntitySnapshot | None:
    value = normalize_for_compare(text)
    matches: list[tuple[int, EntitySnapshot]] = []
    for entity in entities:
        names = (entity.friendly_name, *entity.aliases, *(a.text for a in generate_aliases(entity)))
        score = max(
            (len(normalized) for name in names if (normalized := normalize_for_compare(name)) and normalized in value),
            default=0,
        )
        if score:
            matches.append((score, entity))
    if not matches:
        return None
    top = max(score for score, _ in matches)
    selected = [entity for score, entity in matches if score == top]
    return selected[0] if len(selected) == 1 else None


def _time_range(value: str, now: datetime) -> tuple[datetime, datetime, str, str] | None:
    if re.search(r"\bgestern\b", value):
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return end - timedelta(days=1), end, "hour", "gestern"
    if re.search(r"\b(?:heute|heutigen)\b", value):
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now, "hour", "heute"
    if re.search(r"\b(?:diese|dieser|aktuellen?)\s+woche\b", value):
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now, "day", "diese Woche"
    if re.search(r"\b(?:letzte|letzter|vergangenen?)\s+woche\b", value):
        this_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return this_week - timedelta(days=7), this_week, "day", "letzte Woche"
    if re.search(r"\b(?:dieser|diesen|aktuellen?)\s+monat\b", value):
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now, "day", "diesen Monat"
    return None


def parse_history_query(
    text: str, entities: list[EntitySnapshot], now: datetime
) -> HistoryQuery | None:
    """Parse only explicit statistic questions with one named sensor."""
    value = normalize_for_compare(text)
    if _HISTORY_CUE_RE.search(value) is None:
        return None
    entity = _mentioned_entity(text, [item for item in entities if item.domain == "sensor"])
    time_range = _time_range(value, now)
    if entity is None or time_range is None:
        return None
    if re.search(r"\b(?:durchschnitt|mittelwert)\w*\b", value):
        metric = HistoryMetric.MEAN
    elif re.search(r"\b(?:minimum|niedrigst|kleinst)\w*\b", value):
        metric = HistoryMetric.MIN
    elif re.search(r"\b(?:maximum|hoechst|groesst)\w*\b", value):
        metric = HistoryMetric.MAX
    elif re.search(r"\b(?:verbraucht|verbrauch|erzeugt|produziert)\w*\b", value):
        metric = HistoryMetric.CHANGE
    else:
        return None
    start, end, period, label = time_range
    return HistoryQuery(entity, metric, start, end, period, label)


def _numeric_values(rows: list[dict], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        raw = row.get(key)
        if isinstance(raw, (int, float)):
            values.append(float(raw))
    return values


def render_history_result(query: HistoryQuery, response: object) -> str:
    """Render recorder.get_statistics' response without assuming every key."""
    mapping = response if isinstance(response, dict) else {}
    rows = mapping.get(query.entity.entity_id, [])
    if not isinstance(rows, list) or not rows:
        return f"Für {query.entity.friendly_name} liegen {query.period_label} keine Statistikdaten vor."
    key = {
        HistoryMetric.MEAN: "mean",
        HistoryMetric.MIN: "min",
        HistoryMetric.MAX: "max",
        HistoryMetric.CHANGE: "change",
    }[query.metric]
    values = _numeric_values(rows, key)
    if not values and query.metric is HistoryMetric.CHANGE:
        sums = _numeric_values(rows, "sum")
        if len(sums) >= 2:
            values = [sums[-1] - sums[0]]
    if not values:
        return f"Für {query.entity.friendly_name} liegt {query.period_label} kein passender Zahlenwert vor."
    number = (
        sum(values) / len(values)
        if query.metric is HistoryMetric.MEAN
        else min(values) if query.metric is HistoryMetric.MIN
        else max(values) if query.metric is HistoryMetric.MAX
        else sum(values)
    )
    label = {
        HistoryMetric.MEAN: "Der Durchschnitt",
        HistoryMetric.MIN: "Das Minimum",
        HistoryMetric.MAX: "Das Maximum",
        HistoryMetric.CHANGE: "Die Veränderung",
    }[query.metric]
    unit = f" {query.entity.unit}" if query.entity.unit else ""
    return f"{label} von {query.entity.friendly_name} betrug {query.period_label} {number:g}{unit}."


async def async_execute_history_query(hass, query: HistoryQuery) -> str:
    """Call HA's recorder response service only for a parsed history query."""
    service_data = {
        "start_time": query.start,
        "end_time": query.end,
        "statistic_ids": [query.entity.entity_id],
        "period": query.period,
        "types": [
            {
                HistoryMetric.MEAN: "mean",
                HistoryMetric.MIN: "min",
                HistoryMetric.MAX: "max",
                HistoryMetric.CHANGE: "change",
            }[query.metric]
        ],
    }
    try:
        result = await hass.services.async_call(
            "recorder",
            "get_statistics",
            service_data,
            blocking=True,
            return_response=True,
        )
    except Exception:  # Recorder absent/disabled or API not supported.
        return "Die Home-Assistant-Verlaufsdaten sind momentan nicht verfügbar."
    return render_history_result(query, result)
