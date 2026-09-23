# HomeIntent V11 architecture

V11 adds local, deterministic adaptive intelligence to the frozen V8–V10
pipeline. It does not replace an authoritative component:

```text
V8 LanguageDocument / SemanticGraph
  -> V9 reasoning / WorldModel / HouseGraph (NOW)
  -> V10 GoalModel / Planner
  -> V11 advisory timing and ranking
  -> V10 Validator / ExecutionPolicy / ServiceMapper / Executor
  -> V10 EffectMonitor / GoalRun
  -> V11 compact Experience / transparent model update
```

The invariant is **observation is not permission**. No V11 type exposes an
execution method or creates a `ServiceCallPlan`. Predictions only reach the
existing planner as `AdaptivePlanningAdvice`; policy, confirmation and effect
verification remain mandatory.

## Audit and ownership

| Concept | Existing implementation | V11 extension | Authority |
|---|---|---|---|
| durable confirmed preference | `MemoryStore`, `ProfileStore` | inferred contextual candidate and confirmation state | existing stores after confirmation |
| execution evidence | `GoalRun`, `EffectMonitor` | compact feature extraction | GoalRun/verified state |
| current state | `WorldModel` | no change | WorldModel |
| house facts | `HouseGraph` | optional `STATISTICAL` relation | asserted V9 edges only by default |
| planning | `planner.py` | optional timing advice | V10 planner/policy |
| routines | `RoutineDefinition` | habit candidate/suggestion | V10 confirmed routine pipeline |

## Experience model and store

`ExperienceRecord` contains only one typed action, its narrow context, the
relevant before/after measurements, expected/observed effect, latency,
quality and provenance. It deliberately excludes arbitrary HA state and raw
conversation transcripts. `extract_goal_run_experiences()` consumes completed
V10 run evidence. Thermal cycles use the same record with normalized Celsius
features and exact measurement IDs.

`ExperienceStore` is a schema-versioned JSON store. Writes use a same-directory
temporary file, `fsync` and atomic replace. IDs deduplicate records; count and
age retention are central policy values. Invalid JSON, unknown schemas and bad
individual records fail closed. It is not a recorder replacement.

## Knowledge states and registry

Every learned item is `OBSERVED`, `INFERRED` or `CONFIRMED`. A number in
`confidence` is always clamped conceptually to 0–1 and never grants permission.
`ModelRegistry` is the single schema-versioned store for thermal, timing,
reliability, preference, habit, duration, energy and battery models. It records
scope, parameters, sample count, validation metrics, provenance, version,
health and invalidation reason. Persistent tombstones prevent a deleted model
from being silently rebuilt from old evidence.

The registry exposes only redacted diagnostics: counts by kind and health.
Personal values and evidence IDs are omitted.

## Learning policy and confidence

`LearningPolicy` owns all thresholds. Defaults are conservative:

- fewer than 5 usable samples: no model;
- 5–14: low-confidence model, not planning-authoritative;
- 15 or more: potentially usable, subject to validation;
- planning confidence: at least 0.75;
- thermal MAE: at most 15 minutes;
- preference: at least 8 observations and 75% support;
- habit: at least 10 occurrences and 70% support;
- stale age: 180 days;
- experience/model bounds: 5,000/1,000.

Five samples are enough to expose an explicitly low-confidence statistic but
not enough to schedule a deadline. Fifteen gives basic residual validation a
meaningful minimum while remaining practical for a local household. These
thresholds are settings/policy, not feature-local constants.

Learning modes are `OFF`, `SILENT_LEARN` and `ASK`. There is no learning
`AUTO_EXECUTE` mode. Habit discovery and proactive suggestions default off.

## PredictiveHouseModel and PredictionResult

The `WorldModel` is present state. `PredictiveHouseModel` is a separate,
read-only future-estimate facade. Every `PredictionResult` includes status,
value, interval, confidence, model ID/version, sample count, based-on time,
validity, training range, input feature names and a factual explanation.
Statuses include insufficient data, low confidence, stale, incompatible,
unreliable, invalid and drift detected.

## Thermal model

A `ThermalBinding` explicitly binds one area to one room measurement and one
climate entity, with an optional outdoor measurement. Automatic binding is
valid only outside this model when there is exactly one candidate; production
planning requires `confirmed=True`. Friendly-name scoring is never used.

The lifecycle-owned `ThermalExperienceTracker` starts only after an accepted
HomeIntent `climate.set_temperature` call and only when the climate area has
exactly one temperature sensor. It associates the cycle with the authoritative
`GoalRun`, observes state changes through the existing event runtime, and
stores one compact terminal record. It never subscribes to arbitrary history.

Training rejects missing/naive/reversed timestamps, unsuccessful service
calls, missed targets, open-window cycles, measurement-source changes,
concurrent actions, implausible deltas and durations. The deterministic model
uses fixed-order least squares over temperature delta and, only with at least
15 complete samples, outdoor temperature gap. It reports MAE, median residual,
MAD and p90 absolute residual. There is no random state.

Deadline planning is enabled only for `PredictionStatus.OK`. The start time is:

```text
deadline - predicted duration - (upper prediction bound - estimate)
```

Thus the reserve is derived from observed p90 residuals, never invented. The
existing V10 planner still resolves the climate entity, validates capability
and policy, previews the plan and requires confirmation. Missing, stale,
low-confidence, unreliable or drifted models retain the V10 clarification
path. HA-aware datetimes are preserved, including DST transitions.

After confirmation, the existing V10 one-shot automation performs the
setpoint action. V11 adds one typed observation-only start marker and two
separate date-guarded one-shots at the model-derived intermediate time and
the original deadline. Keeping the checks separate makes them restart-safe.
The final checkpoint reads the confirmed measurement binding, changes the
same scheduled `GoalRun` to `SUCCESS` or `FAILURE`, and closes the compact
thermal Experience. If the start marker was not observed (for example because
the climate service failed and stopped the automation), the final check does
not attribute the room state causally to that action and records a service
failure. No checkpoint can change the setpoint or invoke a device service.

Runtime forecast correction may replace an ETA and warn about likely delay;
it never raises a setpoint or expands authority.

## Effect timing, reliability and anomalies

Effect timing uses median, p90, p95 and MAD. Adaptive verification selects a
learned deadline only within the configured absolute maximum. Reliability records
verified successes and failures with a Wilson-width confidence measure. It is
a plan-ranking signal only between semantically and policy-equivalent plans.

Latency anomalies exceed `p95 + max(3*MAD, p95-median, 1 second)`. The result is
an `AnomalyObservation` marked advisory-only. It cannot diagnose a broken
motor or trigger a service. Notifications require the existing opt-in monitor
pipeline.

## Preferences and multi-user conflicts

Preference keys include only relevant dimensions: user, concept and optional
area/floor/routine/time-band/presence set. Repeated choices create `INFERRED`
candidates and suggestions. Only explicit confirmation creates authority in
the existing memory/profile path. An inferred preference never hides a risky
ambiguity.

Personal preferences remain separate. With multiple present users, V11 uses
an explicitly confirmed shared preference or configured owner policy; the
default is clarification. Values are never averaged implicitly.

## Habit discovery and suggestions

Habit input defaults to HomeIntent-owned GoalRuns. The learning manager updates
abstract multi-step sequence candidates incrementally and stores them in the
central registry; it never materializes an automation. Recorder input requires
explicit opt-in. Sequences are abstract action IDs rather than movement
history. A `HabitCandidate` records sequence, context, weekdays, support,
evidence range and suggestion status. It explicitly has
`creates_automation=False`.

Statuses are `NEW`, `SHOWN`, `ACCEPTED`, `REJECTED`, `SNOOZED`, `EXPIRED`.
Rejected signatures are suppressed. Acceptance only starts the existing V10
RoutineDefinition preview/confirmation pipeline; it does not activate a
routine.

## Drift, invalidation and causality

Five consecutive same-direction residuals whose median exceeds 15 minutes
mark thermal drift. Drifted models cannot advise a deadline and require a
deterministic retrain. Removal/replacement of a bound sensor, area/HVAC change,
staleness or systematic error invalidates the registry record with a reason.

Statistical correlations are described as historical associations. Only a
verified controllable GoalRun action/effect pair is an observed action-effect
relation, never a universal causal claim. Statistical HouseGraph edges use
`FactProvenance.STATISTICAL`, for which `is_asserted_fact` is false; default
traversal remains `asserted_only=True`.

## Explainability, review and forgetting

Conversation management supports learned-model summaries, evidence-based
explanations and model deletion/reset. Explanations show model ID/version,
sample count, training range, confidence and validation metrics—not internal
reasoning. Whole-registry reset is administrator-only and confirmation-bound.
Deletes are persistent and tombstoned; the in-memory predictive view is also
evicted immediately.

## Privacy, lifecycle and performance

All data stays local. V11 stores no camera/face data, full movement trace,
arbitrary state dump or external export. Source utterances are not copied into
experiences. Learning runs from bounded GoalRun callbacks scheduled through
Home Assistant and has no unmanaged process. Model updates are incremental or
explicit bounded rebuilds, not per-sensor-event full retraining.

Ordinary lookups are dictionary/one bounded-file operations. V11 has a
separate benchmark gate with a 100 ms p95 ceiling. Existing V8/V9/V10 gates
and HACS packaging remain unchanged; `custom_components/` contains only
`homeintent`.

## Safety summary

- inferred habit → no `ServiceCallPlan` and no automation;
- inferred preference → no authoritative risky disambiguation;
- low-confidence/stale/drifted prediction → no deadline start;
- statistical graph edge → not asserted;
- anomaly → observation/warning only;
- learned timeout → capped by absolute policy deadline;
- deletion → immediate eviction plus persistent tombstone;
- every action still follows Planner → Validator → ExecutionPolicy →
  confirmation → Executor → verification.
