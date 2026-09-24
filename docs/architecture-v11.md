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

Effect latency is measured from `StepExecutionRecord.service_accepted_at` to
the verified observation, never from the pre-call attempt or GoalRun start.
`attempted_at` records the attempt; `executed_at` remains readable for
compatibility. Old records containing only the ambiguous `executed_at`, and
missing, naive, malformed or reversed timestamps, produce no latency.

`EffectEvidenceState` is the reliability authority: `VERIFIED_SUCCESS`,
`VERIFIED_FAILURE`, `UNVERIFIED` or `INVALID`. The compatibility success Boolean
does not define the denominator. Partial, cancelled and never-verified actions
therefore cannot silently reduce reliability. Old records migrate
conservatively from quality, observation and success without rewriting history.

`ExperienceStore` is a schema-versioned JSON store. Writes use a flushed and
closed same-directory temporary file followed by atomic replace. It deliberately
does not force a synchronous device flush for every advisory sample, so a slow
storage backend cannot stall a GoalRun callback. IDs deduplicate records; count and
age retention are central policy values. Invalid JSON, unknown schemas and bad
individual records fail closed. It is not a recorder replacement.

## Knowledge states and registry

Every learned item is `OBSERVED`, `INFERRED` or `CONFIRMED`. A number in
`confidence` is always clamped conceptually to 0–1 and never grants permission.
`ModelRegistry` is the single schema-versioned store for thermal, timing,
reliability, preference, habit, duration, energy and battery models. It records
scope, parameters, sample count, validation metrics, provenance, version,
health and invalidation reason. Timestamped tombstones prevent a deleted model
from being silently rebuilt from old evidence. Ordinary `FORGET` tombstones are
collectable only after all evidence at or before their `source_cutoff` has left
retention. The bounded learning pass performs this conservative GC using the
oldest globally retained Experience timestamp. Evidence created after deletion
may form a new model only after that cutoff is safe to collect; retained old
evidence can never recreate it. Rejected-habit suppression is durable. Legacy string tombstones load
conservatively as durable because their deletion chronology cannot be proven.

Every upsert returns an explicit `STORED`, `SUPPRESSED` or `REJECTED` result.
The registry owns the bound in-memory prediction view lifecycle under the same
async lock: only a stored model is activated, while suppression, deletion,
bounded eviction and reset deactivate it. Restart restoration is serialized by
the registry as well. Consequently a tombstone is authoritative in persistent
storage and memory, including when retained Experience evidence triggers a
later retraining attempt.

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
unreliable, invalid, drift detected and `OUT_OF_DISTRIBUTION`.

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
unexpected thermostat setpoint/HVAC-mode changes, ambiguous control ownership,
implausible deltas and durations. A known accepted HomeIntent operation is not
mistaken for an external override. Outdoor input comes only from the exact
configured binding; multiple friendly candidates are never guessed.

The deterministic model uses fixed-order least squares. Once the central
minimum is met, the oldest 80% train and newest 20% validate. Training
residuals and holdout MAE/median/p90 are stored separately. A non-positive
temperature-delta coefficient invalidates the model. Persisted training
domains include delta, start temperature and optional outdoor-gap ranges.
Only the central 10% extrapolation margin is allowed; unsupported inputs return
`OUT_OF_DISTRIBUTION` and cannot produce adaptive advice.

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
The intermediate checkpoint rereads measurement, target, deadline and model
health. It reports `ON_TRACK`, `LIKELY_LATE`, `TARGET_ALREADY_REACHED`,
`INSUFFICIENT_EVIDENCE` or `MODEL_INVALID`, and refreshes ETA when usable. It
records bounded evidence but performs zero device calls. The final checkpoint reads the confirmed measurement binding, changes the
same scheduled `GoalRun` to `SUCCESS` or `FAILURE`, and closes the compact
thermal Experience. If the start marker was not observed (for example because
the climate service failed and stopped the automation), the final check does
not attribute the room state causally to that action and records a service
failure. Every generated checkpoint has an opaque ID and strong token backed
by a persistent pending record. The service validates token, goal/run, phase,
model, entities, expiry and consumption, so forged/replayed calls cannot alter
GoalRun or Experience. No checkpoint can change a setpoint or invoke a device
service.

Only bounded active-cycle metadata is persisted. Startup restores a cycle only
while young, uncontaminated, linked to a sensible GoalRun and still compatible
with existing entities, binding, HVAC mode and setpoint. Restore executes no
action.

Runtime forecast correction may replace an ETA and warn about likely delay;
it never raises a setpoint or expands authority.

## Effect timing, reliability and anomalies

Effect timing uses median, p90, p95 and MAD. Timing and reliability models use
the central stale age through first/last observation and expiry metadata. Stale
timing cannot change EffectMonitor timeout; stale reliability has no planning
authority. New verified evidence refreshes them. Adaptive verification selects a
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

Personal preferences remain separate by exact user, concept and area/context.
The live comfort path derives presence only from confirmed HA-user ↔ `person.*`
bindings and current `person.*` states, then calls the typed conflict resolver.
One present user gets that user's profile. Conflicting present users get a
clarification; a confirmed shared answer is scoped to the exact area and user
set. Owner priority is never the default and values are never averaged.
Removed/moved targets lose authority; temporary unavailability follows normal
entity availability semantics without rewriting the preference.

## Habit discovery and suggestions

Habit input defaults to HomeIntent-owned GoalRuns. The learning manager updates
abstract multi-step sequence candidates incrementally and stores them in the
central registry; it never materializes an automation. Recorder input requires
explicit opt-in. Sequences are abstract action IDs rather than movement
history. A `HabitCandidate` records sequence, context, weekdays, support,
evidence range and suggestion status. It explicitly has
`creates_automation=False`.

Statuses are `NEW`, `SHOWN`, `ACCEPTED`, `REJECTED`, `SNOOZED`, `EXPIRED`.
Opportunities are comparable only within the same user, time band and typed
sequence family. Unrelated single actions or another action family do not
dilute support. Rejected signatures are durably suppressed. Acceptance only starts the existing V10
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
sample count, training range, heuristic confidence and validation metrics—not
internal reasoning. Confidence is a quality score, not a calibrated
probability, and is never worded as “87% probability”. Whole-registry reset is administrator-only and confirmation-bound.
Deletes are persistent and tombstoned; the in-memory predictive view is also
evicted immediately.

## Privacy, lifecycle and performance

All data stays local. V11 stores no camera/face data, full movement trace,
arbitrary state dump or external export. Source utterances are not copied into
experiences. Learning runs from bounded GoalRun callbacks scheduled through
Home Assistant and has no unmanaged process. Duplicate experience IDs stop a
second model update. Config-entry runtime owns tasks and the listener; unload
removes the listener, cancels/joins work, and rebuild exceptions are logged
without breaking conversation. Model updates are incremental or bounded.

`LearnedKind.DURATION`, `ENERGY` and `BATTERY_TREND` are schema placeholders,
not predictive implementations. Existing point-in-time/history sensor queries
remain supported, while predictive “normally/how long until empty” questions
receive an explicit no-model answer.

Ordinary lookups are dictionary/one bounded-file operations. V11 has a
separate benchmark gate with a 100 ms p95 ceiling. Existing V8/V9/V10 gates
and HACS packaging remain unchanged; `custom_components/` contains only
`homeintent`.

## Safety summary

- inferred habit → no `ServiceCallPlan` and no automation;
- inferred preference → no authoritative risky disambiguation;
- low-confidence/stale/drifted/out-of-distribution prediction → no deadline start;
- unverified effect → excluded from reliability;
- intermediate/forged/restored thermal observation → zero device calls;
- statistical graph edge → not asserted;
- anomaly → observation/warning only;
- learned timeout → capped by absolute policy deadline;
- deletion → immediate eviction plus persistent tombstone;
- every action still follows Planner → Validator → ExecutionPolicy →
  confirmation → Executor → verification.
