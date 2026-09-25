# HomeIntent V12 architecture — Proactive Context Intelligence

V12 lets HomeIntent notice a relevant situation, decide whether it is worth an
interruption, pick the right person and channel, keep the question open across
turns and — only after an explicit answer or a previously confirmed standing
permission — hand a desired *state* to the unchanged V10 pipeline.

V12 is additive. It adds no second language pipeline, world model, planner,
executor, effect monitor, experience store, prediction model, presence system,
timer engine, automation writer or push transport.

```text
Home Assistant state_changed ──► existing SituationRuntime (single listener)
                                        │
                                        ▼
                       SituationDetector ─► SituationStore (stable lifecycle)
                                        │
          V11 PredictiveHouseModel ─►  ContextForecastEngine  (consumes, no training)
          V11 habit LearnedModels  ─►        │
                                        ▼
                    PriorityPolicy · PrivacyPolicy · QuietHoursPolicy
                                        │
       StandingPermission + AutoExecutionPolicy (NEVER_AUTO) ──► V10 runner (opt-in)
                                        │
                                  OpportunityPolicy     "worth interrupting?"
                                        │
                                  AttentionPolicy       budget / dedupe / grouping
                                        │
     person.* (home) + RoomPresenceResolver + SatelliteRegistry
                                        │
                                 CommunicationRouter    VOICE / PUSH / HISTORY
                                        │
                    PendingProposal + ActiveGoalSession (no action yet)
                                        │
                     AgentDelivery (push, TTS)  ·  assist_satellite
                                        │
          reply (voice / text / interactive push) ── DialogManager arbitration
                                        │
   V10: materialize_target_states → Validator → ExecutionPolicy →
        ExecutionCoordinator → PlanExecutor → policy-gated executor →
        effect verification → GoalRun ──► V11 Experience / Reliability
```

Invariants: PREDICTION != EXECUTION, SITUATION != GOAL, OPPORTUNITY !=
PERMISSION, PRIORITY != AUTHORIZATION, ATTENTION != SAFETY, CONFIDENCE !=
CONSENT, HABIT != AUTOMATION, HOME PRESENCE != ROOM PRESENCE, ROOM PRESENCE !=
SPEAKER IDENTITY, COMMUNICATION != DEVICE EXECUTION, SAFE CLASSIFICATION !=
STANDING PERMISSION, PROACTIVE != AUTONOMOUS, NO-OP != DEVICE ACTION.

## Pre-V12 gate: action evidence

V12 relies on V11 Reliability, so the evidence boundary was fixed first.
`StepResult.service_accepted` is authoritative and propagated unchanged into
`StepExecutionRecord` by `planner.goal_run_from_plan_result` (now the single
GoalRun builder for conversation plans and V12):

| Case | `success` | `service_accepted` | `attempted_at` | `service_accepted_at` | Experience |
|---|---|---|---|---|---|
| desired state already satisfied (no-op) | True | None | None | None | none |
| service rejected / raised | False | False | set | None | none (SERVICE_ERROR, no effect record) |
| accepted + effect verified | True | True | set | set | VERIFIED_SUCCESS |
| accepted + effect not observed | False | True | set | set | VERIFIED_FAILURE |
| scheduled for later | True | None | None | None | none until the real run |

`extract_goal_run_experiences` only considers steps with `service_accepted is
True`. 8 accepted successes + 1 accepted failure + 10 no-ops + 3 unverified
runs yield `sample_count = 9`, `success_rate = 8/9`.

## Authority matrix

| Concept | Existing authority | V12 extension | Final authority |
|---|---|---|---|
| Language | V8 | none (V12 adds only closed reply/command patterns for its own dialogs) | V8 |
| World state | V9 WorldModel / entity snapshots | reads fresh snapshots | V9 |
| Planning | V10 planner | `materialize_target_states` (explicit desired states, existing closed operators) | V10 |
| Validation | V10 `validate_agent_service_plan` | none | V10 |
| Execution policy | V10 `evaluate_service_plan` | auto path runs with `confirmed=False` | V10 |
| Execution | V10 `PlanExecutor` + `async_execute_service_plan` | none | V10 |
| Conflicts | V10 `ExecutionCoordinator` | read-only view of reserved targets | V10 |
| Effect verification | V10 | none | V10 |
| Execution evidence | V10 `GoalRun` | proactive provenance in `evidence` | V10 |
| Experience / learning | V11 | proactive GoalRuns feed the existing listener | V11 |
| Prediction | V11 `PredictiveHouseModel`, habit models | `ContextForecastEngine` consumes | V11 |
| Home presence | `person.*` via `UserContextStore` | none | existing |
| Room presence | — | `RoomPresenceResolver` | V12 |
| Satellite ↔ area | HA area/device registry | `SatelliteRegistry` (+ explicit config) | V12 |
| Notification transport | `AgentDelivery` | typed opaque actions, satellite speech | existing `AgentDelivery` |
| Dialog arbitration | `DialogManager` + pending context | three V12 task kinds | `DialogManager` |
| Automation storage | `AutomationExecutor` | none | existing |
| Timers | `NativeTimerRuntime` | observes expiry for history only | NativeTimer |
| Legacy agent rules | `ProactiveAgentRuntime` (5.x) | forwards `HOMEINTENT_V12_*` push actions | unchanged |

The pre-existing `situation.SituationEvaluator` (stateless categories for the
5.x agent) remains untouched; `ProactiveSituation` is the lifecycle model for
V12 and is fed by the same `SituationRuntime` listener.

## Situation lifecycle

`SituationDetector.is_relevant()` rejects unrelated entities with a set/prefix
check before any snapshot scan. Initial kinds:

| Kind | Source | Stable identity |
|---|---|---|
| `ENTRY_LEFT_OPEN` | cover `garage`/`garage_door`/`gate`/`door`, binary_sensor `door`/`garage_door` | `entry_left_open:<entity>` |
| `APPLIANCE_FINISHED` | configured program-state entity, running → finished | `appliance_finished:<entity>` |
| `DEVICE_LEFT_ON_WHEN_LEAVING` | lights on while `person.*` says nobody home | `device_left_on_when_leaving:<area>` |
| `THERMAL_GOAL_AT_RISK` | V11 intermediate thermal checkpoint `LIKELY_LATE` | `thermal_goal_at_risk:<goal>` |
| `DEVICE_EFFECT_ANOMALY` | V10 `EffectMonitor` expiry | `device_effect_anomaly:<entity>` |
| `HABIT_OPPORTUNITY` | first step of exactly one valid V11 habit of the only home owner | `habit_opportunity:<model>:<date>` |
| `PENDING_GOAL_REQUIRES_ATTENTION` | unattended (monitor/scheduled/thermal) GoalRun failure | `pending_goal_requires_attention:<run>` |
| `CRITICAL_SAFETY_EVENT` | binary_sensor `smoke`, `carbon_monoxide`, `gas`, `moisture` | `critical_safety_event:<entity>` |
| `TIMER_FINISHED` | NativeTimer (history only) | — |

States: `DETECTED → ACTIVE → COMMUNICATED → ACKNOWLEDGED/SNOOZED → RESOLVED`,
plus `EXPIRED` and `SUPPRESSED`. Repeated identical events never create a new
situation; a condition that ends resolves the situation and cancels its open
proposals. A new occurrence after resolution is a new situation. Kinds
without a live resolution signal expire after a bounded age (appliance 4 h,
habit 30 min, thermal risk 6 h, effect anomaly 1 h, pending goal 12 h).

## ContextForecast / V11 boundary

`ContextForecastEngine.anticipate()` returns `AnticipationResult(kind,
model reference, usable, reasons)` — no action field exists. Thermal risk and
effect anomalies query `PredictiveHouseModel`; habit opportunities read the
habit `LearnedModel` health, expiry and suggestion status. Any status other
than `OK` (insufficient, low confidence, stale, out of distribution, invalid)
makes the result unusable and the OpportunityPolicy downgrades the situation
to history.

## Decisions

**PriorityPolicy** — explicit mapping: appliance/anomaly INFO, habit and
lights-left-on SUGGESTION, entry/thermal/pending goal IMPORTANT, water leak
URGENT, smoke/CO/gas CRITICAL. Only an authoritative safety `device_class`
reaches CRITICAL; a V11 anomaly can never promote itself.

**PrivacyPolicy** — safety PUBLIC; entry, appliance, lights, thermal, anomaly
HOUSEHOLD; habits and personal goal failures PERSONAL; SENSITIVE is never
spoken.

**OpportunityPolicy** — SUPPRESS / HISTORY_ONLY / COMMUNICATE / ESCALATE with
reason codes: resolved, snoozed, acknowledged, duration below threshold (then
exactly one duration check is scheduled), goal already active, already
communicated (cooldown), unusable model evidence, muted by confirmed
preference, no reachable recipient, quiet hours. URGENT/CRITICAL escalate even
when acknowledged, snoozed, muted or in quiet hours; one ongoing alarm is not
re-broadcast more than every five minutes.

**AttentionPolicy** — per recipient: dedupe within the group window, budget
(4 per hour), grouping of low-priority items into one digest, dismissal for
the *current occurrence* only; URGENT/CRITICAL bypass everything.
`AttentionStateStore` is bounded in every dimension.

**Quiet hours** — per user (`proactive_user_quiet_hours`), default from the
existing agent quiet window; evaluated on HA-local wall-clock minutes, so a
DST switch never moves the window. INFO → history, SUGGESTION → suppressed,
IMPORTANT → private push, CRITICAL → immediate.

## Room presence and satellites

`RoomPresenceResolver` combines only explicit, *fresh* evidence:

- configured person room sensors (`person.x = sensor.y`, e.g. Bermuda/BLE area
  sensors) whose state maps to exactly one HA area → EXACT,
- a recent (5 min) authenticated satellite turn of that user → STRONG,
- occupancy/presence sensors when the person is the only one home and exactly
  one area is occupied → STRONG.

Conflicts and unmapped values give AMBIGUOUS; nothing gives UNKNOWN.

Freshness (7.0.1): every source carries its own `observed_at` — the later of
HA's `last_changed`/`last_updated` for sensors, the turn time for a satellite
turn — and is valid until `observed_at + TTL` (10 min for sensors and
occupancy, 5 min for satellite turns). Validity is never `now + TTL`, so
resolving again never refreshes old evidence. A source without a timezone-aware
timestamp, or with one more than a minute in the future, is not evidence.
Expired sources are dropped, so a stale room sensor yields UNKNOWN, never
EXACT. A fresh room sensor and a fresh satellite turn naming different rooms
give AMBIGUOUS. The combined result is valid only until the earliest
`valid_until` of the sources behind it. Room presence and satellite turns are
kept in memory only; after a restart there is no room evidence until a new
fresh observation arrives.

Limitation: HA's `last_updated` changes on any attribute update, so an
integration that rewrites attributes without re-measuring the room can keep a
sensor "fresh". HomeIntent cannot tell these apart and trusts HA's
timestamps.
`person.x = home` alone never yields a room, and room evidence is never used as
speaker identity.

`SatelliteRegistry` maps `assist_satellite.*` entities to areas from the HA
entity/device registry, overridable by explicit configuration. Zero or several
satellites in an area produce no voice target. Friendly names are never
matched.

## CommunicationRouter

| Situation | Channel |
|---|---|
| home, room EXACT (or STRONG for household/public), unique satellite | VOICE |
| away / room ambiguous or unknown / no or several satellites | (INTERACTIVE_)PUSH |
| PERSONAL and another household member home, or room not EXACT | PUSH |
| SENSITIVE | PUSH |
| quiet hours (non-critical) | PUSH |
| no private channel | HISTORY_ONLY |
| URGENT/CRITICAL | PUSH + VOICE where possible (MULTI_CHANNEL); configured house speakers only for PUBLIC safety content |
| URGENT/CRITICAL without any reachable recipient | household fallback: HA persistent notification (+ configured house speakers) |

The router checks room validity itself against the explicit decision time
`now`: room evidence without `valid_until` (`room_evidence_unbounded`) or with
`now > valid_until` (`room_evidence_expired`) never selects a room satellite,
at any priority or privacy level, so stale evidence can never send PERSONAL or
SENSITIVE content to a speaker. (The only room-independent voice route remains
PUBLIC safety content on explicitly configured house speakers.) Unknown or ambiguous rooms never pick a satellite.

Voice uses `assist_satellite.start_conversation` for questions (the satellite
keeps listening, no wake word) and `assist_satellite.announce` otherwise.
There is never a global broadcast for non-critical content.

## Proposals and sessions

A proposal stores an opaque id, the situation, the recipients, a
`ProposedGoal` (explicit entity ids + closed desired states: on/off/open/
closed — `unlocked` is not representable), channel, privacy, expiry (30 min)
and — for voice — the satellite device that asked. `ActiveGoalSession` holds
the continuation context. Creating either performs no device action.

Binding:

- an authenticated user may answer any proposal listing them as recipient,
  on any channel (voice ↔ push, room A ↔ room B);
- an anonymous voice turn may answer only a PUBLIC/HOUSEHOLD proposal voiced
  on that exact satellite;
- another user on the asking satellite gets "gehört zu einem anderen
  Benutzer";
- several eligible proposals + a bare "Ja" produce a clarification ("Meinst du
  das Licht in der Küche oder die Garage?"); nothing executes;
- `claim_for_execution` is an atomic PENDING → EXECUTING transition, so a
  repeated "Ja" or push tap never runs twice.

Before execution the situation is re-checked against live state; a closed
garage makes the stored "Ja" a no-op.

## Interactive push

Actions are `HOMEINTENT_V12_{ACCEPT|LATER|IGNORE}_<proposal id>_<device token>`.
The payload contains no domain, service, entity or plan.

Device binding (7.0.1). Home Assistant's `mobile_app` fires
`mobile_app_notification_action` with the app's event data and a context
carrying the authenticated HA `user_id`. Core adds no device id, so an event
`device_id` cannot prove which phone tapped. HomeIntent therefore binds the
buttons to a device when it sends them:

1. Buttons are attached only for a `notify.mobile_app_*` target that belongs
   to the recipient in the HomeIntent user binding **and** resolves to a
   device through the HA entity registry. Device ownership is never inferred
   from names.
2. For each such target HomeIntent generates a random 64-bit token
   (`t` + 16 hex digits), puts it only into that target's action ids, and stores
   `PushActionBinding(token, user_id, device_id)` on the proposal (persisted,
   at most 8 per proposal). If the send fails, the binding is discarded.
3. Without an authoritative binding (legacy `notify.*` service, no registry
   device, unbound user) the push is still sent as an **informational message
   without buttons**. The question can then be answered through
   authenticated Assist.

A push action is rejected — without any change to the proposal, situation,
GoalRun, experience, standing permissions or devices — when the reference is
malformed or unknown, the proposal is expired or already resolved (replay),
the HA user is not a recipient, the action carries no token, the token is not
bound to that proposal, the token was bound for another user, or the event
carries a `device_id` different from the bound one. An event without a
`device_id` is accepted only through a valid token. ACCEPT enters the V10
pipeline, LATER snoozes, IGNORE acknowledges the current occurrence.

What this proves, and what not: the tap came from an authenticated HA user who
is a recipient and who knew a token that was delivered only to the bound
Companion device. A token that leaked off the device (e.g. copied from a
notification log) is usable by that same HA user only, never by another user.
Informational pushes never need a binding.

## Dialog priority

A reply belongs to exactly one dialog:

1. pending legacy dialogs (timer naming, timer choice, delete-all timers,
   automation drafts/confirmations, security/service confirmations, alias,
   clarification) — answered by their owner;
2. open `DialogManager` tasks of other features (plan, routine, habit,
   preference, learning) — answered by their owner;
3. V12 tasks (proposal clarification, standing-permission preview, mute
   preview) — answered by V12;
4. only then a bare reply may address a V12 proposal; if the 5.x agent also
   has an open spoken question, V12 asks which one is meant.

"Nein" is therefore contextual: it cancels the routine, discards the
automation draft, keeps the timers, rejects the proposal or cancels the
security action — never all of them.

## StandingPermission and NEVER_AUTO

A permission is created only from a complete supported sentence, e.g. "Wenn
niemand zuhause ist und im Wohnzimmer noch Licht an ist, darfst du es
automatisch ausschalten.", followed by a preview and an explicit "Ja". It
stores the owner, situation kind, closed operator, explicit entity ids (no
wildcards), area, condition `nobody_home`, expiry (180 days) and a daily
attempt limit. Nothing exists by default and the feature is disabled by
default.

Automatic execution requires all of: exact single matching permission,
confirmed, not revoked, not expired, owner is a bound household user,
situation kind auto-eligible and still active, area match, daily attempt
limit, fresh
`nobody_home`, every lit subject covered by the permission, every target
allowed by `AutoExecutionPolicy`, a five-minute persistence window; then V10
materialization, Validator, ExecutionPolicy **without** a confirmation flag,
ExecutionCoordinator, PlanExecutor and effect verification. Any failure means
no execution — V12 asks instead.

`AutoExecutionPolicy` never allows locks, alarm panels, sirens, valves, covers
(incl. garages, gates, doors), climate, buttons, scripts, automations,
vacuums, mowers, cameras, humidifiers, stove/oven-like or security-named
switches, or any unknown actuator. Even a tampered permission record for the
garage is refused, and V10 would still classify the garage close as
confirmation-required.

Counters (7.0.1). Every automatic V10 run is an *attempt*; only a run whose
effect V10 verified (`EXECUTED`) is a *verified execution*. Rejected services,
failed effect verification, stale state and coordinator conflicts are attempts
without an execution. The daily limit counts attempts, so a failing run can
retry at most `max_executions_per_day` times per 24 h (the stored field keeps
its name for compatibility; the refusal reason is `daily_attempt_limit`). The
store keeps attempts under the existing `executions` key, so 7.0.0 storage
loads unchanged and a 7.0.0 downgrade still sees every attempt, and adds
`verified_executions`. Engine diagnostics expose `auto_attempts` and
`auto_verified_executions`.

## Snooze, dismiss, mute, history

"Später" / "Erinnere mich in 20 Minuten" snoozes the situation; at expiry one
callback re-evaluates *live* state — a closed garage stays silent. "Ignorieren"
and "Nein" acknowledge only the current occurrence. "Sag mir das künftig nicht
mehr." asks for confirmation before a persistent per-user mute is stored;
safety warnings cannot be muted.

`ProactiveHistoryStore` (500 records) keeps decisions, channels, priorities,
reason codes and evidence codes — never transcripts or audio. "Warum hast du
mich wegen der Garage angesprochen?" and "Welche Hinweise gab es heute?" are
answered from these records; personal records are only shown to their
recipient.

## Timer integration

NativeTimer remains the only announcer: name first, then the chime. V12
records `TIMER_FINISHED` as history with reason `announced_by_native_timer`;
the OpportunityPolicy always returns HISTORY_ONLY for that kind, so one
expiry yields exactly one announcement.

## Persistence and restart

One document (`.storage/homeintent_proactive.json`) with bounded sections:
situations (256), attention state, proposals/sessions (64), permissions (32),
history (500), desired-state goals. Writes are built on the event loop,
performed in a worker thread and ordered by generation, so an older write can
never replace a newer one. Unknown schemas, malformed records, unconfirmed or
non-eligible permissions and proposals with non-closed target states are
dropped (fail closed).

On restart V12 restores state, then revalidates against live HA state:
resolved situations are closed, proposals are kept only when unexpired, still
backed by a live situation and addressed to known users; snoozes and duration
checks are re-scheduled; the restore pass never executes and never runs the
auto path.

## Event-driven runtime and performance

No polling loop exists. Duration checks, snoozes and digests use one
`async_track_point_in_utc_time` callback per stable key (at most 600). A storm
of 1000 unrelated state changes creates no situation, task, notification or
write. `scripts/benchmark_v12.py` (5000 entities) budgets p95: situation
evaluation 100 ms, opportunity 50 ms, priority 20 ms, routing 20 ms, room
presence 50 ms, session lookup 20 ms.

## Configuration

All options are in the HomeIntent options flow: `proactive_context_enabled`
(default off), `voice_proactive_enabled`, `push_proactive_enabled`,
`room_aware_voice_enabled`, `attention_budget_enabled`,
`quiet_hours_enabled`, `standing_permissions_enabled` (default off),
`critical_multi_channel_enabled`, `proactive_entry_open_minutes` (15),
`proactive_appliance_entities`, `proactive_person_room_sensors`,
`proactive_satellite_areas`, `proactive_user_quiet_hours`. Recipients and push
targets come from the existing `homeintent.bind_user_context` and
`homeintent.set_household` services. Room sensors must be selected in
HomeIntent's entity list so their state is visible.

## Privacy and local-only guarantee

V12 runs entirely inside Home Assistant: no cloud API, no runtime LLM, no
model download, no remote prediction and no external service. It persists no
state-machine copy, no transcript, no audio and no movement history; room
evidence is evaluated on demand and kept only as a five-minute in-memory
interaction marker.

## Verification

- `tests/test_v11_action_evidence_semantics.py`, `tests/test_conversation_action_evidence.py` — evidence boundary
- `tests/test_v12_garage_e2e.py` — mandatory garage scenario
- `tests/test_v12_behavior.py` — room, privacy, proposals, push, permissions, priority, attention, quiet hours, snooze
- `tests/test_v12_conversation.py` — timer/automation/security collisions through `conversation.py`
- `tests/test_v12_ood_corpus.py` + `tests/data/v12_ood_de.json` — 296 handwritten cases in 48 categories
- `tests/test_v12_persistence_restart.py`, `tests/test_v12_decision_matrix.py`, `tests/test_v12_runtime.py`, `tests/test_v12_units.py`, `tests/test_v12_policies.py`, `tests/test_v12_room_attention_routing.py`
- `tests/test_v12_push_authentication.py` — push actions through the real `mobile_app_notification_action` → agent runtime → proactive runtime → engine path (7.0.1)
- `tests/test_v12_room_freshness.py` — per-source evidence expiry, conflicts, router enforcement (7.0.1)
- `tests/test_v12_auto_counters.py` — attempts vs. verified executions, daily attempt budget (7.0.1)

Every behavioral safety assertion counts calls at an instrumented
`hass.services` sink behind the real policy-gated executor; positive controls
(`sp-01`, `ip-01`, the garage E2E) prove the sink records real executions.

## Known limitations

- Speaker identity comes only from HA's authenticated conversation user; most
  voice satellites are anonymous, so anonymous answers are limited to
  household proposals on the satellite that asked, and V10 policy then applies
  non-admin rules.
- Room presence is only as good as the configured sensors; without them V12
  routes to push. Freshness relies on HA's `last_changed`/`last_updated`.
- Interactive push buttons need a Companion app notify entity that is bound to
  the user and registered to a device; other push targets get the text
  without buttons. The push token proves delivery to the bound device, not
  physical possession at tap time.
- Guests are not household members: "others home" only knows bound `person.*`
  entities.
- Grouped digests are delivered by push only.
- Standing permissions support exactly one sentence family (lights left on
  while nobody is home); other rules remain regular automations.
