"""V6 ("Semantic Intelligence Architecture") Wave 1 performance baseline.

Purely additive, read-only measurement tool - does not import anything that
isn't already public API of the current pipeline (``NluEngine.match()``,
``EntitySnapshot``). Written *before* the "Semantic Composer" (Semantic
Frame -> Resolution -> Reasoning -> Command -> Validation -> ServiceMapper ->
Execution) is introduced in a later wave, so later waves can diff their own
measurements against this file's numbers to see whether/how much latency the
new layers add.

Scope (see docs/perf/v6-baseline.md for the full writeup): this measures
``NluEngine.match(text, entities)`` end-to-end - hassil sentence-template
matching (parsers.py) + entity/area resolution (entities.py/areas.py) +
``ServiceCallPlan`` construction (service_call.py/nlu/service_mapper.py).
It stops *before* the actual Home Assistant ``hass.services.async_call``
- that call crosses into HA's own event bus/state machine and isn't
meaningfully mockable/measurable from this repo in isolation, so it is
out of scope here (documented as a scope boundary, not an oversight).

Run with:
    source /home/philipp/ha-nlu-engine-venv/bin/activate
    python scripts/benchmark_v6_baseline.py
"""

from __future__ import annotations

import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "custom_components"))

from ha_nlu.engine import NluEngine  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from ha_nlu.world_model import build_world_model  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic entity generation
# ---------------------------------------------------------------------------

# Areas grouped by floor, so area-/floor-filtering (quantifier/area-query
# parsers) has real multi-floor, multi-area data to filter over instead of
# one flat bucket - mirrors a realistic multi-storey home, not just a
# single room repeated N times.
_FLOORS: list[tuple[str, str, int]] = [
    ("keller", "Keller", -1),
    ("eg", "Erdgeschoss", 0),
    ("og", "Obergeschoss", 1),
]
_AREAS: list[tuple[str, str, str]] = [
    # (area_id, area_name, floor_id)
    ("keller_technik", "Technikraum", "keller"),
    ("keller_vorrat", "Vorratsraum", "keller"),
    ("wohnzimmer", "Wohnzimmer", "eg"),
    ("kueche", "Küche", "eg"),
    ("flur_eg", "Flur", "eg"),
    ("buero", "Büro", "eg"),
    ("gaeste_wc", "Gäste-WC", "eg"),
    ("schlafzimmer", "Schlafzimmer", "og"),
    ("bad", "Bad", "og"),
    ("kinderzimmer", "Kinderzimmer", "og"),
    ("flur_og", "Flur Oben", "og"),
    ("arbeitszimmer", "Arbeitszimmer", "og"),
]
_FLOOR_BY_ID = {floor_id: (floor_name, floor_level) for floor_id, floor_name, floor_level in _FLOORS}

# Realistic domain mix for a mid-size smart home (weights, not exact counts -
# see _domain_for_index below). Sensor-heavy, light-heavy, everything else a
# minority - roughly matches the domain spread in tests/golden_fixtures.py's
# GOLDEN_ENTITIES and conftest.py's ALL_ENTITIES, scaled up.
_DOMAIN_WEIGHTS: list[tuple[str, int]] = [
    ("light", 30),
    ("sensor", 25),
    ("switch", 15),
    ("cover", 10),
    ("climate", 10),
    ("binary_sensor", 10),
]
_DOMAIN_CYCLE: list[str] = [domain for domain, weight in _DOMAIN_WEIGHTS for _ in range(weight)]

_DEVICE_CLASS_BY_DOMAIN = {
    "sensor": "temperature",
    "binary_sensor": "window",
}
_UNIT_BY_DOMAIN = {"sensor": "°C"}


def _domain_for_index(i: int) -> str:
    return _DOMAIN_CYCLE[i % len(_DOMAIN_CYCLE)]


def _capabilities_for_domain(domain: str) -> frozenset[str]:
    return {
        "light": frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
        "switch": frozenset({"TURN_ON", "TURN_OFF"}),
        "cover": frozenset({"POSITION"}),
        "climate": frozenset({"TURN_ON", "TURN_OFF", "TEMPERATURE"}),
        "fan": frozenset({"TURN_ON", "TURN_OFF"}),
    }.get(domain, frozenset())


def _synthetic_entity(i: int) -> EntitySnapshot:
    domain = _domain_for_index(i)
    area_id, area_name, floor_id = _AREAS[i % len(_AREAS)]
    floor_name, floor_level = _FLOOR_BY_ID[floor_id]
    object_id = f"{domain}_{area_id}_{i}"
    friendly_name = f"{area_name} {domain.replace('_', ' ').title()} {i}"
    attributes = {"temperature": 20} if domain == "climate" else {}
    return EntitySnapshot(
        entity_id=f"{domain}.{object_id}",
        friendly_name=friendly_name,
        domain=domain,
        state="off" if domain not in ("sensor",) else "20.0",
        area_id=area_id,
        area_name=area_name,
        floor_id=floor_id,
        floor_name=floor_name,
        floor_level=floor_level,
        unit=_UNIT_BY_DOMAIN.get(domain),
        device_class=_DEVICE_CLASS_BY_DOMAIN.get(domain),
        capabilities=_capabilities_for_domain(domain),
        attributes=attributes,
    )


# Fixed "anchor" entities with names/areas the benchmark utterances below
# reference by exact friendly name - included in *every* generated scale
# (in addition to the bulk-generated filler above) so the same utterances
# stay valid regardless of N, and so the timing differences across scales
# are purely a function of list size, not of which entity happens to match.
ANCHOR_LIGHT = EntitySnapshot(
    "light.wohnzimmer_hauptlicht", "Wohnzimmer Hauptlicht", "light", "off",
    area_id="wohnzimmer", area_name="Wohnzimmer", floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
)
ANCHOR_CLIMATE = EntitySnapshot(
    "climate.heizung_buero", "Heizung Büro", "climate", "heat",
    area_id="buero", area_name="Büro", floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "TEMPERATURE"}), attributes={"temperature": 20},
)
ANCHOR_SENSOR = EntitySnapshot(
    "sensor.aussentemperatur", "Außentemperatur", "sensor", "18.4",
    unit="°C", device_class="temperature",
)
ANCHOR_COVER = EntitySnapshot(
    "cover.rollladen_buero", "Rollladen Büro", "cover", "closed",
    area_id="buero", area_name="Büro", floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
    capabilities=frozenset({"POSITION"}),
)
ANCHORS: list[EntitySnapshot] = [ANCHOR_LIGHT, ANCHOR_CLIMATE, ANCHOR_SENSOR, ANCHOR_COVER]


def generate_entities(n: int) -> list[EntitySnapshot]:
    """``n`` synthetic entities plus the fixed anchor entities above, spread
    across multiple domains/areas/floors (see module docstring)."""
    bulk = [_synthetic_entity(i) for i in range(n)]
    return ANCHORS + bulk


# ---------------------------------------------------------------------------
# Representative utterances (v2 plan's own "one utterance per pipeline
# shape" spread: plain on/off, climate set-temperature, sensor state query,
# area-scoped quantifier command, percentage/cover command - touches five of
# the thirteen separately-compiled hassil grammars plus entity/area
# resolution and ServiceCallPlan construction for each).
# ---------------------------------------------------------------------------

BENCHMARK_UTTERANCES: list[tuple[str, str]] = [
    ("light_on", "Mach Wohnzimmer Hauptlicht an"),
    ("light_off", "Mach Wohnzimmer Hauptlicht aus"),
    ("climate_set_temperature", "stelle die Heizung Büro auf 21 Grad"),
    ("sensor_query", "wie hoch ist die Außentemperatur?"),
    ("area_quantifier", "Mach alle Lichter im Wohnzimmer aus"),
    ("cover_percentage", "Fahre Rollladen Büro auf 30 Prozent runter"),
    ("semantic_free_order_query", "Im Erdgeschoss geschlossen, welche Fenster sind das?"),
]

SCALES: list[int] = [100, 500, 1000, 5000]
ITERATIONS = 50
WARMUP_ITERATIONS = 10


@dataclass(frozen=True)
class Stats:
    label: str
    scale: int
    iterations: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile - no numpy/statistics-percentile dependency
    needed (Python's ``statistics`` module only gained ``quantiles`` cleanly
    usable for this in 3.8+, but a manual nearest-rank calc keeps this file
    dependency-free of any subtlety around interpolation methods)."""
    if not sorted_values:
        return 0.0
    index = max(0, min(len(sorted_values) - 1, int(round(pct * (len(sorted_values) - 1)))))
    return sorted_values[index]


def _time_call(fn, iterations: int) -> list[float]:
    """Returns per-call durations in milliseconds."""
    durations = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        end = time.perf_counter()
        durations.append((end - start) * 1000.0)
    return durations


def benchmark_engine_construction(repeats: int = 5) -> Stats:
    """One-time cost of ``NluEngine()`` - compiling all 13 separately-loaded
    hassil ``Intents`` grammars from YAML. Paid once at HA integration
    startup (``__init__.py``), not per conversation turn - measured
    separately from the per-utterance figures below so the two costs aren't
    conflated."""
    durations = _time_call(lambda: NluEngine(), repeats)
    durations.sort()
    return Stats(
        label="engine_construction",
        scale=0,
        iterations=repeats,
        mean_ms=statistics.mean(durations),
        p50_ms=_percentile(durations, 0.50),
        p95_ms=_percentile(durations, 0.95),
        min_ms=min(durations),
        max_ms=max(durations),
    )


def benchmark_utterance(engine: NluEngine, label: str, text: str, entities: list[EntitySnapshot], scale: int) -> Stats:
    world_model = build_world_model(entities, [])
    # Warmup: first call(s) into a fresh entity list pay for any incidental
    # cold-path cost (e.g. first regex compile cache fill) - excluded from
    # the measured sample so steady-state per-call cost is what's reported.
    for _ in range(WARMUP_ITERATIONS):
        engine.match(text, entities, world_model)

    durations = _time_call(lambda: engine.match(text, entities, world_model), ITERATIONS)
    durations.sort()
    return Stats(
        label=label,
        scale=scale,
        iterations=ITERATIONS,
        mean_ms=statistics.mean(durations),
        p50_ms=_percentile(durations, 0.50),
        p95_ms=_percentile(durations, 0.95),
        min_ms=min(durations),
        max_ms=max(durations),
    )


def run_all() -> tuple[Stats, list[Stats]]:
    construction_stats = benchmark_engine_construction()
    engine = NluEngine()

    results: list[Stats] = []
    for scale in SCALES:
        entities = generate_entities(scale)
        for label, text in BENCHMARK_UTTERANCES:
            results.append(benchmark_utterance(engine, label, text, entities, scale))
    return construction_stats, results


def _print_stats(stats: Stats) -> None:
    print(
        f"  {stats.label:22s} n={stats.scale:5d}  iters={stats.iterations:4d}  "
        f"mean={stats.mean_ms:8.4f}ms  p50={stats.p50_ms:8.4f}ms  p95={stats.p95_ms:8.4f}ms  "
        f"min={stats.min_ms:8.4f}ms  max={stats.max_ms:8.4f}ms"
    )


if __name__ == "__main__":
    construction_stats, results = run_all()
    print("Engine construction (one-time, hassil YAML compile):")
    _print_stats(construction_stats)
    print()
    print("Per-utterance NluEngine.match() timings:")
    for scale in SCALES:
        print(f" -- scale={scale} --")
        for stats in results:
            if stats.scale == scale:
                _print_stats(stats)
