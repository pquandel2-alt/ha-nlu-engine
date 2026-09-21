# HomeIntent V10 architecture

HomeIntent V10 extends the completed V8/V9 pipeline without introducing a
second NLU, planner, executor, automation engine, world model, presence system,
or notification engine.

```
Natural language
  -> V8 LanguageDocument / structure / SemanticGraph
  -> V9 grounding / HouseGraph / query algebra / ReasoningTrace
  -> V10 GoalModel
  -> existing bounded Planner / PlanModel dependency graph
  -> existing ExecutionPolicy and service executor
  -> existing EffectMonitor plus GoalRun verification evidence
  -> factual result or proactive typed notification
```

## Goal understanding

`goal_model.py` is the authoritative outcome model. `IntentClass` separates
`COMMAND`, `QUERY`, `AUTOMATION`, and `GOAL`. A `GoalModel` can carry a typed
goal kind, scope, desired properties, deadline, trigger, runtime conditions,
exclusions, confirmed routine/profile references, recipients, channel,
severity, success criteria, failure handling, provenance, and a reference to
the V8 semantic analysis. It contains no service name.

`goal_intent.py` consumes the shared `LanguageDocument`: token features,
clause structure, speech act, and temporal expressions. It is not a fallback
parser and cannot execute. In particular, a requested result such as “um 7
Uhr 21 Grad haben” becomes a deadline goal. A concrete “um 7 Uhr den Sollwert
setzen“ remains an action. Without a configured thermal model HomeIntent asks
which meaning is intended and never invents a preheating time.

The question is represented as a typed
`GOAL_SEMANTIC_CLARIFICATION` task containing the complete original
`GoalModel`, requesting user, conversation ID, area, desired temperature,
deadline, provenance, and the two closed choices `SETPOINT_AT_TIME` and
`ACHIEVE_BY_DEADLINE`. A follow-up such as „Ersteres“ is interpreted only in
that open task. The setpoint choice materializes through the sole planner,
validator, execution policy, confirmation, and persistent date-bound one-shot
automation path. The deadline choice creates no service or automation while
no confirmed thermal model exists.

## Planner and PlanModel

`planner.py` remains the sole planner and `PlanExecutor` remains its sole plan
execution boundary. `MaterializedPlan` is a directed graph of typed
`PlanStep`s (`CHECK`, `QUERY`, `ACTION`, `WAIT_FOR_EVENT`, `WAIT_UNTIL`,
`CONDITION`, `NOTIFY`, `VERIFY`, `BRANCH`, `SUBPLAN`). Actions are selected
from closed operators and represented by the existing `ServiceCallPlan`;
arbitrary services or code cannot be generated.

`PlanningLimits` bounds depth, candidates, expansions, and steps. Graph
validation rejects dangling dependencies, cycles, and oversized plans.
`PlanningTrace` records structured facts, selected operators, skipped steps,
and active bounds—never hidden chain-of-thought. Planning removes already
satisfied steps, applies exclusions to every routine step, and validates the
resulting graph again.

Immediately before each action the executor rebuilds the entity snapshot,
checks availability and dependencies, skips newly satisfied effects, and
executes only through the existing policy/service path. A changed state can
only simplify or safely stop the same goal; it cannot change the goal's
meaning.

## Preconditions, policy, effects, and retries

Each step declares preconditions, invariants, expected effects, risk,
idempotency, and verification data. `execution_policy.py` and `risk.py` remain
authoritative at actual execution time. Persisting or confirming a goal does
not grant future permission for a critical action.

`effect_monitor.py` remains the single asynchronous state-effect observer.
The plan executor also performs a fresh read after action completion.
`GoalRun` stores whether the service was accepted and whether the expected
effect was observed. Service acceptance alone never means goal success.

`retry_policy.py` defaults to one attempt. A retry can only be enabled with a
bounded maximum of three, an idempotent low-risk operator, and an explicitly
allowed transient failure. Unlock, opening, alarm disarm, button presses, and
scripts are never automatically retried.

## GoalRun and failure explanation

`goal_run.py` defines bounded, local `GoalRun` history: goal/run IDs, source,
actor, typed goal, plan ID, selected targets, preconditions, confirmation,
step outcomes, expected/observed effects, notifications, failure codes, and
final status (`SUCCESS`, `PARTIAL_FAILURE`, `FAILURE`, or policy/cancelled
states). The store has a configurable retention count and no movement log.

Failure explanations have three causality levels:

- `DIRECTLY_OBSERVED`: an expected and observed state differ or time out;
- `DERIVED_FROM_TRACE`: a recorded trigger, condition, policy, service, or
  delivery fact proves the explanation;
- `POSSIBLE_BUT_UNPROVEN`: HomeIntent explicitly says the cause is unknown.

Recorder history is read only through the existing central `history_query.py`
adapter. For a missing monitor notification, HomeIntent may use its bounded
transition-evidence API to prove that the configured person transition did
not occur. If Recorder data, a matching monitor goal, or an unambiguous time
range is missing, the cause remains unknown. Missing evidence is never
replaced with a guess.

Historical selection is centralized in typed `GoalRunQuery` filtering over
the bounded store. It composes user/person, half-open local-HA-time bounds,
status, goal kind, routine, goal/run ID, and concrete entity. Supported history
windows include today, yesterday, the day before yesterday, morning/evening,
and last night. An explicit yesterday window is applied before recency, so a
newer run from today cannot displace it. Multiple plausible runs create a
typed clarification task; no latest-wins shortcut chooses among them.

## Persons and presence

Home Assistant `person.*` entities are the only presence authority. The local
`UserContextStore` persists explicit, confirmed bindings:

```
HA user id -> person.* -> one explicitly preferred notify.* target
```

No person-to-device name similarity is used. An explicitly spoken configured
person name is grounded only when exactly one `person.*` entity matches.
“ich” is unresolved until the authenticated HA
user is linked. Multiple push targets without exactly one preferred target
remain ambiguous. A separately confirmed household scope defines „niemand
zuhause“; arbitrary guest/test persons and device trackers are excluded.
Zones use HA person states and configured HA zones rather than a new geofence.

Notification targets carry a typed kind. `ENTITY` is delivered to the exact
bound `notify.*` entity through `notify.send_message`; `SERVICE` invokes the
exact registered classic `notify.<service>` action (including Companion App
services). Bindings are validated against the corresponding live registry.
There is no name inference and no broadcast fallback for missing or ambiguous
goal-notification targets. This follows Home Assistant's documented split
between [`notify.send_message` for notify entities and legacy notify
actions](https://www.home-assistant.io/integrations/notify/).

## Monitor goals and proactive notifications

`monitor_goal.py` is a persistent goal layer over the existing HA event and
delivery infrastructure—not a second automation engine. It receives HA state
transitions from `SituationRuntime`; it contains no sleep or polling loop.
After restart `MonitorGoalStore` reloads typed goals.

At a matching trigger the runtime rebuilds the WorldModel snapshot. Window,
light, door, or garage selections are evaluated then, never frozen when the
goal is created. An empty window result produces no warning. Typed
`NotificationModel` data is rendered by a closed renderer and delivered by
the existing `AgentDelivery` boundary to the explicit recipient target.
Arbitrary Jinja/user templates are not accepted.

Dedupe keys combine goal, trigger occurrence, condition/category, recipient,
and target. A bounded cooldown suppresses presence flapping without disabling
future occurrences. GoalRun idempotency keys prevent duplicate one-shot work.
`ExecutionCoordinator` lets unrelated goals run concurrently while rejecting
simultaneous writes to the same concrete entity deterministically.

## Routines, procedures, comfort, and plan edits

`ProfileStore` persists only explicitly confirmed `RoutineDefinition` and
`ComfortProfile` objects. Words such as “Schlafengehen”, “Filmabend”, and
“angenehm” have no built-in household meaning. A missing definition produces
a clarification. Comfort changes use the unambiguous Assist origin area and
only profile dimensions outside their confirmed range.

Administrators can commit the resulting reviewed definitions through the
typed `homeintent.save_routine` and `homeintent.save_comfort_profile` service
boundaries. These accept stable entity IDs and closed properties, never
services, YAML, Jinja, or arbitrary code. Monitor goals can be removed through
`homeintent.delete_monitor_goal`.

`plan_modification.py` applies follow-up exclusions, removals, or timing
changes to the pending typed goal/plan. It never reconstructs and reparses the
original utterance. Dependencies are rewired and the graph is revalidated.

## Persistence, privacy, diagnostics, and limits

User/person/notification bindings, profiles, monitor goals, and bounded run
history remain local under `.storage`. Diagnostics expose counts and statuses,
not utterances, notification bodies, person IDs, or movement history. There is
no runtime LLM, cloud NLU, model download, external profile transfer, or silent
learning. Unsupported, ambiguous, unsafe, or insufficiently evidenced goals
end in clarification or a typed failure, never a best-effort action.

Version 5.0.2 is the V10 completion/hardening release. This architecture is
frozen as **V10 COMPLETE**; later architectural expansion belongs to a
separate V11 project and is not implied by this document.
