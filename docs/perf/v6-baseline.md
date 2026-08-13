# V6 Performance Baseline (Wave 1, "Independent Foundations")

Measures the **current** pipeline (13 separately-compiled `hassil` intent
grammars, regex-based parser routing in `engine.py`/`parsers.py`, linear-scan
entity/area resolution in `entities.py`/`areas.py`) *before* the "Semantic
Composer" (Semantic Frame → Resolution → Reasoning → Command → Validation →
ServiceMapper → Execution) is layered on top in a later wave. Purpose: give
later waves a number to diff their own measurements against, so a latency
regression (or improvement) from the new architecture is visible rather than
assumed.

Produced by `scripts/benchmark_v6_baseline.py` (stdlib `time.perf_counter`
only — no new dependencies; `hassil`/`pytest` were already in the venv, no
`pytest-benchmark` or similar was added). Re-run it any time with:

```bash
source /home/philipp/ha-nlu-engine-venv/bin/activate
python scripts/benchmark_v6_baseline.py
```

## Scope

- Measures `NluEngine.match(text, entities)` end-to-end: hassil sentence
  matching → parser routing (`engine.py::_select_parser`) → entity/area
  resolution (`entities.py::resolve_entity_scored`,
  `areas.py::resolve_area_name`) → `ServiceCallPlan` construction
  (`service_call.py`, `nlu/service_mapper.py`).
- **Stops before** the actual Home Assistant `hass.services.async_call`. That
  call crosses into HA's own event bus/state machine and isn't meaningfully
  mockable/measurable from this repo in isolation — explicit scope boundary,
  not an oversight.
- `NluEngine()` construction (compiling all 13 YAML-defined hassil grammars)
  is measured separately, since it is a one-time cost paid once at
  integration startup, not per conversation turn.

## Test conditions

- **Hardware**: this run was executed on the current dev/agent container, **not**
  a Raspberry Pi. `/proc/cpuinfo` reports a `QEMU Virtual CPU version 2.5+`
  (i.e. a virtualized x86_64 host, 4 vCPUs, ~9.4 GiB RAM) — this is
  meaningfully faster and more consistent (no thermal throttling, no SD-card
  I/O, no ARM vs. x86 instruction-set differences) than the target Raspberry-Pi-class
  platform. **This is the single biggest caveat on every number below**: treat
  these as relative/scaling numbers (how does cost grow with entity count,
  which utterance shapes are cheap vs. expensive), not as absolute
  milliseconds a real device will see. A real Pi 4/5 measurement is still
  outstanding (see Open Issues).
- OS: Linux 6.8.0-136-generic (Ubuntu), Python 3.12.3.
- Repo: `ha-nlu-engine`, commit `b188cab394aaa0135ba5a78594551981eebe1119` (Wave 1 start).
- `hassil==3.11.0`, `pytest==9.1.1` — no other perf-relevant deps.
- 200 measured iterations per (utterance, scale) pair, preceded by 10
  discarded warmup iterations. One shared `NluEngine` instance reused across
  all measurements (matches real usage — the engine is built once at HA
  startup and `match()` is called per turn).

## Synthetic entity generation

Four scales — 100 / 500 / 1000 / 5000 `EntitySnapshot` objects — spread
across 6 domains (`light` 30%, `sensor` 25%, `switch` 15%, `cover` 10%,
`climate` 10%, `binary_sensor` 10%) and 12 areas across 3 floors (Keller/
Erdgeschoss/Obergeschoss), so area-/domain-filtering is exercised against
real multi-area, multi-floor data rather than one flat bucket. Four fixed
"anchor" entities (`Wohnzimmer Hauptlicht`, `Heizung Büro`, `Außentemperatur`,
`Rollladen Büro`) are included at every scale so the same benchmark
utterances stay valid regardless of N.

## Benchmark utterances

| Label | Utterance | Pipeline shape exercised |
|---|---|---|
| `light_on` | "Mach Wohnzimmer Hauptlicht an" | SingleTargetParser, name resolution |
| `light_off` | "Mach Wohnzimmer Hauptlicht aus" | SingleTargetParser, name resolution |
| `climate_set_temperature` | "stelle die Heizung Büro auf 21 Grad" | ClimateExtendedParser, name resolution |
| `sensor_query` | "wie hoch ist die Außentemperatur?" | SingleTargetParser (query), name resolution |
| `area_quantifier` | "Mach alle Lichter im Wohnzimmer aus" | QuantifierParser, **domain+area filtering** (`resolve_entities_by_domain`), no name resolution |
| `cover_percentage` | "Fahre Rollladen Büro auf 30 Prozent runter" | PercentageParser, name resolution |

## Results

All values in milliseconds, 200 iterations per cell.

### Engine construction (one-time)

| | mean | p50 | p95 | min | max |
|---|---|---|---|---|---|
| `NluEngine()` (5 iterations) | 40.11 | 40.21 | 41.52 | 37.44 | 41.52 |

### scale = 100 entities

| Utterance | mean | p50 | p95 | min | max |
|---|---|---|---|---|---|
| light_on | 1.00 | 0.96 | 1.19 | 0.89 | 1.79 |
| light_off | 0.95 | 0.92 | 1.07 | 0.88 | 1.28 |
| climate_set_temperature | 0.98 | 0.98 | 1.01 | 0.94 | 1.08 |
| sensor_query | 1.07 | 1.00 | 1.37 | 0.91 | 3.06 |
| area_quantifier | 4.76 | 4.50 | 6.09 | 4.25 | 9.62 |
| cover_percentage | 1.30 | 1.19 | 1.99 | 1.12 | 2.46 |

### scale = 500 entities

| Utterance | mean | p50 | p95 | min | max |
|---|---|---|---|---|---|
| light_on | 3.86 | 3.79 | 4.28 | 3.67 | 4.90 |
| light_off | 4.27 | 3.90 | 7.15 | 3.59 | 12.09 |
| climate_set_temperature | 4.11 | 3.95 | 5.08 | 3.68 | 8.17 |
| sensor_query | 4.64 | 4.02 | 7.70 | 3.57 | 10.29 |
| area_quantifier | 5.74 | 4.78 | 10.90 | 4.40 | 24.39 |
| cover_percentage | 4.80 | 4.28 | 8.00 | 3.88 | 9.20 |

### scale = 1000 entities

| Utterance | mean | p50 | p95 | min | max |
|---|---|---|---|---|---|
| light_on | 7.33 | 7.12 | 8.05 | 6.98 | 13.31 |
| light_off | 7.43 | 7.23 | 8.75 | 7.01 | 12.23 |
| climate_set_temperature | 8.06 | 7.47 | 12.17 | 7.14 | 15.28 |
| sensor_query | 8.26 | 7.57 | 13.45 | 7.05 | 14.48 |
| area_quantifier | 6.10 | 5.18 | 10.73 | 4.68 | 17.64 |
| cover_percentage | 9.22 | 8.29 | 14.09 | 7.34 | 15.12 |

### scale = 5000 entities

| Utterance | mean | p50 | p95 | min | max |
|---|---|---|---|---|---|
| light_on | 39.23 | 36.43 | 53.43 | 33.79 | 125.38 |
| light_off | 36.20 | 34.72 | 42.72 | 33.54 | 74.94 |
| climate_set_temperature | 35.12 | 34.08 | 39.38 | 33.16 | 48.50 |
| sensor_query | 38.36 | 34.98 | 52.37 | 33.17 | 157.41 |
| area_quantifier | 7.11 | 6.64 | 9.48 | 6.23 | 13.25 |
| cover_percentage | 38.69 | 36.37 | 55.25 | 33.66 | 92.25 |

Raw script output archived alongside this report's numbers is reproducible
by re-running `scripts/benchmark_v6_baseline.py` — not committed as a
separate artifact since the numbers above already are that output.

## Interpretation

- **Name-resolution utterances scale roughly linearly with entity count, and
  are already the dominant cost by 1000+ entities.** `light_on`/`light_off`/
  `climate_set_temperature`/`sensor_query`/`cover_percentage` all go through
  `entities.py::resolve_entity_scored`, which does a full O(n) scan of the
  entity list and — critically — calls `generate_aliases()` (building the
  entity-id/humanized-entity-id/configured-alias candidate list) for **every**
  entity on **every** call, not just the eventual match. That cost is what
  dominates: ~1ms at 100 entities → ~4ms at 500 → ~7-9ms at 1000 → **~35-39ms
  at 5000**, a ~35-40x increase for a 50x entity increase (consistent with
  near-linear scaling, small constant-factor caching effects at the low end).
- **`area_quantifier` scales far more gently** (4.8ms → 5.7ms → 6.1ms → 7.1ms
  across the same 100→5000 range, <1.5x total) because
  `resolve_entities_by_domain()` does a single cheap list-comprehension scan
  with no per-entity `generate_aliases()` call — it never does name matching
  at all, just domain/area/floor equality checks. This is the clearest signal
  in the data: **the expensive part of the current pipeline is per-entity
  alias generation during name resolution, not entity-list iteration itself.**
- `entities.py` already contains an unused optimization for exactly this:
  `EntityIndex`/`build_entity_index()` (v2 plan Phase 23, "Performance") groups
  entities by domain/area/normalized-name/normalized-alias in O(n) *once*, but
  its own docstring says it is "not yet [any parser's] consumer" — every
  parser today still calls `resolve_entity`/`resolve_entity_scored` directly,
  rebuilding candidate aliases from scratch on every single utterance.
- At the *current* production entity counts most real HA installs have
  (typically well under 500, per `tests/conftest.py`'s ~25-entity fixture and
  `tests/golden_fixtures.py`), the current pipeline's absolute latency
  (~1-5ms on this dev VM) is not a concern even before accounting for the Pi
  vs. VM hardware gap. It becomes a real concern for installs at the upper
  end of the tested range (5000 entities is a large but not implausible
  install) or for any future architecture that resolves names *more than
  once per turn* (e.g. a multi-stage Semantic Composer that re-resolves the
  same entity list at Frame, Resolution, and Command stages) — see
  recommendation below.

## Open Issues / Measurement Limits

- **No real Raspberry Pi measurement yet.** All numbers above are from a
  virtualized x86_64 dev container (QEMU Virtual CPU), not the actual target
  hardware. CPython on ARM (Pi 4/5) with SD-card-backed I/O and no host-level
  virtualization overhead will differ, likely by a constant multiplicative
  factor rather than a different scaling shape — but that has not been
  verified. Anyone continuing this baseline in a later wave should re-run
  `scripts/benchmark_v6_baseline.py` directly on Pi-class hardware before
  treating the absolute-millisecond numbers as load-bearing.
- Only 6 of the ~13+ hassil grammars / parser paths are exercised
  (`SingleTargetParser`, `ClimateExtendedParser`, `QuantifierParser`,
  `PercentageParser`); `LightExtendedParser`, `FanExtendedParser`,
  `ComparisonQueryParser`, `TemporalParser`, `AreaQueryParser`,
  `ContextFollowupParser`, `ReferenceParser`, `QueryFollowupParser`,
  `StateQueryParser` are not individually timed. The chosen six were picked
  to cover the cheapest (`area_quantifier`) and most expensive (single-name
  resolution) pipeline shapes identified above; the remaining grammars are
  structurally similar to one of these two shapes (either they resolve one
  name, or they filter by domain/area), so are expected to fall in the same
  two bands, but that is an inference, not a direct measurement.
- Multi-step ("und"-joined) sentences (`engine.py::_match_multi`) are not
  benchmarked — cost there is expected to be roughly N × single-command cost
  (each segment re-enters the same `match()` pipeline), not separately
  verified.
- The full HA `hass.services.async_call` execution step is out of scope by
  design (see Scope section) — this baseline says nothing about end-to-end
  voice-command latency as experienced by a user, only about the NLU layer's
  own processing time.
- Numbers reported are from a single benchmark run; no repeated-run
  variance/confidence-interval analysis was done (the p50/p95/min/max spread
  within each run is reported instead, which already shows the VM's own
  jitter, e.g. `light_on` at 5000 entities: p50 36.4ms vs. max 125.4ms).

## Recommendation for the Architect (Semantic Composer)

The current bottleneck is unambiguous and localized: **`resolve_entity_scored()`
regenerates every entity's alias candidates from scratch on every single
call**, with no caching across calls and no use of the already-built-but-unused
`EntityIndex`. This has two direct implications for the Semantic Composer
design:

1. **Do not resolve the same entity list more than once per conversation
   turn without reusing work.** If the new pipeline's stages (Semantic Frame
   → Resolution → Reasoning → Command → Validation → ServiceMapper) each
   independently call into entity resolution, the current linear-scan/
   alias-regeneration cost multiplies by the number of stages that resolve.
   At 5000 entities, today's *single* resolution already costs ~35ms on
   dev hardware (expect meaningfully more on a real Pi) — N resolution calls
   per turn would make that N×.
2. **Wiring up the existing `EntityIndex`/`build_entity_index()` (already
   built and unit-tested, just unused) before or alongside the Semantic
   Composer would very likely flatten the `light_on`/`climate_set_temperature`/
   etc. curves to look like `area_quantifier`'s (near-flat, <1.5x growth
   100→5000) instead of the current ~35-40x growth** — since it precomputes
   normalized-name/alias/domain/area lookups once per entity list rather than
   per call. This is a pre-existing, independent opportunity (not something
   the Composer itself needs to build), but it is the single highest-leverage
   fix visible in this baseline, and doing it once (used by *every* stage
   that needs to resolve a name) is strictly better than each future
   Composer stage inventing its own caching.

In short: the current 13-grammar/regex-routing pipeline itself is cheap and
scales fine (`area_quantifier`'s near-flat curve proves routing + domain/area
filtering isn't the problem); the cost is entirely in unindexed name
resolution. Whatever the Semantic Composer's Resolution stage ends up looking
like, it should resolve each entity list against an index built once per
turn — not re-scan/re-alias the raw entity list per stage.
