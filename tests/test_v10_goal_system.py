from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from homeintent.entities import EntitySnapshot
from homeintent.goal_intent import classify_intent, interpret_goal
from homeintent.goal_model import (
    DesiredState,
    GoalCondition,
    GoalKind,
    GoalLifecycle,
    GoalModel,
    GoalProvenance,
    GoalScope,
    GoalTrigger,
    IntentClass,
    NotificationSeverity,
)
from homeintent.goal_run import (
    CausalityLevel,
    FailureCode,
    GoalRun,
    GoalRunStatus,
    GoalRunStore,
    StepExecutionRecord,
    VerificationRecord,
    explain_goal_run,
)
from homeintent.monitor_goal import (
    MonitorGoalRuntime,
    MonitorGoalStore,
    MonitorRecord,
)
from homeintent.nlu.language_frontend import analyse_language
from homeintent.plan_modification import apply_plan_modification
from homeintent.retry_policy import RetryPolicy, may_retry
from homeintent.planner import (
    Goal,
    MaterializedPlan,
    PlanExecutor,
    PlanStatus,
    PlanStep,
    PlanningLimits,
    StepKind,
    materialize_comfort_profile,
    materialize_routine,
    effect_satisfied,
    observed_effect,
    validate_plan_graph,
)
from homeintent.profiles import (
    ComfortProfile,
    RoutineDefinition,
    RoutineStepDefinition,
)
from homeintent.risk import RiskLevel
from homeintent.service_call import ServiceCallPlan
from homeintent.user_context import (
    BindingStatus,
    NotificationTarget,
    UserContextStore,
)


def _monitor_goal(goal_id: str = "goal_windows") -> GoalModel:
    return GoalModel(
        GoalKind.MONITOR_AND_NOTIFY,
        goal_id=goal_id,
        trigger=GoalTrigger(
            "person_leaves_zone", "person.philipp", "home", "home", "not_home"
        ),
        conditions=(
            GoalCondition(
                "open_entities",
                GoalScope(domain="binary_sensor", device_class="window"),
                "non_empty",
                True,
                True,
            ),
        ),
        recipient_person_ids=("person.philipp",),
        notification_severity=NotificationSeverity.WARNING,
        provenance=GoalProvenance(
            "Wenn ich gehe, prüf bitte, ob noch Fenster offen sind und sag mir Bescheid.",
            "user-1",
            confirmed=True,
        ),
        lifecycle=GoalLifecycle.MONITOR,
    )


def test_goal_is_distinct_from_temperature_command():
    result_goal = analyse_language(
        "Sorge dafür, dass es morgen um 7 Uhr im Wohnzimmer 21 Grad hat."
    )
    command = analyse_language("Stell morgen um 7 Uhr die Heizung auf 21 Grad.")
    assert classify_intent(result_goal) is IntentClass.GOAL
    assert classify_intent(command) is IntentClass.COMMAND
    goal = interpret_goal(result_goal)
    assert goal is not None and goal.kind is GoalKind.SCHEDULED
    assert goal.temporal is not None and goal.temporal.must_be_achieved_by_deadline
    assert goal.failure_handling == "clarify_without_thermal_model"
    assert interpret_goal(command) is None


def test_leave_home_goal_requires_explicit_person_mapping():
    goal = interpret_goal(
        analyse_language(
            "Wenn ich gehe, prüf bitte, ob noch Fenster offen sind und sag mir Bescheid."
        ),
        current_user_id="user-1",
    )
    assert goal is not None and goal.kind is GoalKind.MONITOR_AND_NOTIFY
    assert goal.trigger is not None and goal.trigger.person_entity_id is None
    assert not goal.recipient_person_ids


def test_leave_home_goal_uses_person_and_fresh_condition_scope():
    goal = interpret_goal(
        analyse_language(
            "Wenn ich gehe, prüf bitte, ob noch Fenster offen sind und sag mir Bescheid."
        ),
        current_user_id="user-1",
        current_person_entity_id="person.philipp",
    )
    assert goal is not None and goal.trigger is not None
    assert goal.trigger.from_state == "home" and goal.trigger.to_state == "not_home"
    assert goal.conditions[0].evaluate_at_trigger
    assert goal.conditions[0].scope.device_class == "window"
    assert goal.recipient_person_ids == ("person.philipp",)


def test_named_person_arrival_and_pronoun_recipient_are_grounded_explicitly():
    goal = interpret_goal(
        analyse_language(
            "Wenn Julia nach Hause kommt und die Garage offen ist, sag ihr Bescheid."
        ),
        person_name_bindings={"julia": ("person.julia",)},
    )
    assert goal is not None and goal.trigger is not None
    assert goal.trigger.kind == "person_arrives_zone"
    assert goal.trigger.person_entity_id == "person.julia"
    assert goal.recipient_person_ids == ("person.julia",)


def test_ambiguous_named_person_is_not_guessed():
    goal = interpret_goal(
        analyse_language(
            "Wenn Alex nach Hause kommt und ein Fenster offen ist, sag Alex Bescheid."
        ),
        person_name_bindings={"alex": ("person.alex_one", "person.alex_two")},
    )
    assert goal is not None and goal.trigger is not None
    assert goal.trigger.kind == "person_reference_ambiguous"
    assert goal.parameters["ambiguous_person_name"] == "alex"


def test_user_context_never_guesses_and_rejects_ambiguous_push(tmp_path):
    store = UserContextStore(tmp_path / "users.json")
    asyncio.run(store.async_load())
    assert store.resolve_current_person("user-1").status is BindingStatus.MISSING
    asyncio.run(
        store.async_set_user(
            "user-1",
            person_entity_id="person.philipp",
            notification_targets=(
                NotificationTarget("notify.mobile_app_phone"),
                NotificationTarget("notify.mobile_app_tablet"),
            ),
            confirmed=True,
        )
    )
    assert store.resolve_current_person("user-1").person_entity_id == "person.philipp"
    assert (
        store.resolve_notification_targets("person.philipp").status
        is BindingStatus.AMBIGUOUS
    )


def test_preferred_notification_target_is_unambiguous(tmp_path):
    store = UserContextStore(tmp_path / "users.json")
    asyncio.run(
        store.async_set_user(
            "user-1",
            person_entity_id="person.philipp",
            notification_targets=(
                NotificationTarget("notify.mobile_app_phone", preferred=True),
                NotificationTarget("notify.mobile_app_tablet"),
            ),
            confirmed=True,
        )
    )
    result = store.resolve_notification_targets("person.philipp")
    assert result.status is BindingStatus.RESOLVED
    assert result.targets[0].target_id == "notify.mobile_app_phone"


def test_monitor_runtime_queries_windows_at_trigger_time_and_deduplicates(tmp_path):
    contexts = UserContextStore(tmp_path / "users.json")
    asyncio.run(
        contexts.async_set_user(
            "user-1",
            person_entity_id="person.philipp",
            notification_targets=(
                NotificationTarget("notify.mobile_app_iphone", preferred=True),
            ),
            confirmed=True,
        )
    )
    monitor_store = MonitorGoalStore(tmp_path / "goals.json")
    run_store = GoalRunStore(tmp_path / "runs.json")
    asyncio.run(monitor_store.async_save(MonitorRecord(_monitor_goal(), cooldown_seconds=60)))
    query_count = 0
    delivered: list[tuple[str, str]] = []

    async def fresh():
        nonlocal query_count
        query_count += 1
        return [
            EntitySnapshot("person.philipp", "Philipp", "person", "not_home"),
            EntitySnapshot(
                "binary_sensor.kitchen", "Küchenfenster", "binary_sensor", "on",
                device_class="window", area_id="kitchen", area_name="Küche",
            ),
            EntitySnapshot(
                "binary_sensor.bedroom", "Schlafzimmerfenster", "binary_sensor", "off",
                device_class="window", area_id="bedroom", area_name="Schlafzimmer",
            ),
        ]

    async def deliver(model, rendered):
        delivered.append((rendered.title, rendered.message))
        assert model.target_id == "notify.mobile_app_iphone"
        return True

    runtime = MonitorGoalRuntime(monitor_store, run_store, contexts, fresh, deliver)
    now = datetime(2026, 9, 19, 18, 0, tzinfo=timezone.utc)
    first = asyncio.run(
        runtime.async_process_person_transition(
            "person.philipp", "home", "not_home", occurred_at=now,
            occurrence_id="context-1",
        )
    )
    second = asyncio.run(
        runtime.async_process_person_transition(
            "person.philipp", "home", "not_home", occurred_at=now,
            occurrence_id="context-1",
        )
    )
    assert query_count == 1
    assert len(first) == 1 and second == ()
    assert delivered == [
        ("Fenster noch offen", "Du hast das Haus verlassen. Küchenfenster ist noch offen.")
    ]


def test_monitor_runtime_sends_nothing_for_empty_runtime_result(tmp_path):
    contexts = UserContextStore(tmp_path / "users.json")
    asyncio.run(
        contexts.async_set_user(
            "user-1",
            person_entity_id="person.philipp",
            notification_targets=(NotificationTarget("notify.mobile_app_iphone"),),
            confirmed=True,
        )
    )
    goals = MonitorGoalStore(tmp_path / "goals.json")
    runs = GoalRunStore(tmp_path / "runs.json")
    asyncio.run(goals.async_save(MonitorRecord(_monitor_goal())))
    delivered = 0

    async def fresh():
        return [
            EntitySnapshot(
                "binary_sensor.kitchen", "Küchenfenster", "binary_sensor", "off",
                device_class="window",
            )
        ]

    async def deliver(_model, _rendered):
        nonlocal delivered
        delivered += 1
        return True

    runtime = MonitorGoalRuntime(goals, runs, contexts, fresh, deliver)
    result = asyncio.run(
        runtime.async_process_person_transition(
            "person.philipp", "home", "not_home",
            occurred_at=datetime.now(timezone.utc), occurrence_id="closed",
        )
    )
    assert result[0].status is GoalRunStatus.SUCCESS
    assert result[0].evidence == ("fresh_runtime_query_empty",)
    assert delivered == 0


def test_all_household_away_waits_for_last_person(tmp_path):
    contexts = UserContextStore(tmp_path / "users.json")
    asyncio.run(
        contexts.async_set_user(
            "user-1", person_entity_id="person.philipp",
            notification_targets=(NotificationTarget("notify.phone"),), confirmed=True,
        )
    )
    asyncio.run(contexts.async_set_household(("person.philipp", "person.julia"), confirmed=True))
    goal = replace(
        _monitor_goal("goal_lights"),
        trigger=GoalTrigger(
            "nobody_home", zone_id="home",
            household_person_ids=("person.philipp", "person.julia"),
        ),
        conditions=(GoalCondition("lights_on", GoalScope(domain="light"), "non_empty", True),),
    )
    goals = MonitorGoalStore(tmp_path / "goals.json")
    runs = GoalRunStore(tmp_path / "runs.json")
    asyncio.run(goals.async_save(MonitorRecord(goal)))
    states = {"person.philipp": "not_home", "person.julia": "home"}
    delivered: list[str] = []

    async def fresh():
        return [
            *(EntitySnapshot(key, key, "person", value) for key, value in states.items()),
            EntitySnapshot("light.kitchen", "Küchenlicht", "light", "on"),
        ]

    async def deliver(_model, rendered):
        delivered.append(rendered.message)
        return True

    runtime = MonitorGoalRuntime(goals, runs, contexts, fresh, deliver)
    first = asyncio.run(
        runtime.async_process_person_transition(
            "person.philipp", "home", "not_home",
            occurred_at=datetime(2026, 9, 19, 18, 0, tzinfo=timezone.utc),
            occurrence_id="philipp-left",
        )
    )
    states["person.julia"] = "not_home"
    second = asyncio.run(
        runtime.async_process_person_transition(
            "person.julia", "home", "not_home",
            occurred_at=datetime(2026, 9, 19, 18, 5, tzinfo=timezone.utc),
            occurrence_id="julia-left",
        )
    )
    assert first == ()
    assert len(second) == 1 and delivered


def test_monitor_goal_survives_store_reload(tmp_path):
    path = tmp_path / "goals.json"
    asyncio.run(MonitorGoalStore(path).async_save(MonitorRecord(_monitor_goal())))
    loaded = asyncio.run(MonitorGoalStore(path).async_load())
    assert len(loaded) == 1
    assert loaded[0].goal.trigger is not None
    assert loaded[0].goal.trigger.person_entity_id == "person.philipp"


def test_routine_plan_skips_satisfied_and_excludes_whole_area():
    entities = [
        EntitySnapshot(
            "light.living", "Wohnzimmerlicht", "light", "off", area_id="living",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
        EntitySnapshot(
            "light.child", "Kinderzimmerlicht", "light", "on", area_id="child",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
        EntitySnapshot(
            "cover.child", "Kinderzimmerrollladen", "cover", "open", area_id="child",
            capabilities=frozenset({"POSITION"}),
        ),
        EntitySnapshot(
            "cover.living", "Wohnzimmerrollladen", "cover", "open", area_id="living",
            capabilities=frozenset({"POSITION"}),
        ),
    ]
    routine = RoutineDefinition(
        "filmabend", "Filmabend", "user-1",
        (
            RoutineStepDefinition("a", GoalScope(entity_ids=("light.living",)), DesiredState("state", "off")),
            RoutineStepDefinition("b", GoalScope(entity_ids=("light.child",)), DesiredState("state", "off")),
            RoutineStepDefinition("c", GoalScope(entity_ids=("cover.child",)), DesiredState("state", "closed")),
            RoutineStepDefinition("d", GoalScope(entity_ids=("cover.living",)), DesiredState("state", "closed")),
        ),
        True,
    )
    goal = GoalModel(
        GoalKind.PREPARE_MOVIE, goal_id="movie", routine_id="filmabend",
        exclusions=GoalScope(excluded_area_ids=("child",)),
    )
    plan = materialize_routine(
        goal, routine, entities, options={}, is_admin=True, user_id="user-1"
    )
    targets = [step.action.entity_id for step in plan.steps if step.action is not None]
    assert targets == ["cover.living"]
    assert plan.trace is not None
    assert "light.living:already_satisfied" in plan.trace.skipped
    assert "light.child:excluded" in plan.trace.skipped
    assert "cover.child:excluded" in plan.trace.skipped


def test_comfort_profile_only_changes_out_of_range_values():
    profile = ComfortProfile(
        "living", "user-1", "living", 21, 22, 40, 60, confirmed=True
    )
    entities = [
        EntitySnapshot(
            "light.living", "Wohnzimmerlicht", "light", "on", area_id="living",
            capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
            attributes={"brightness": 230},
        ),
        EntitySnapshot(
            "climate.living", "Heizung", "climate", "heat", area_id="living",
            attributes={"current_temperature": 21.5, "temperature": 21.5},
        ),
    ]
    goal = GoalModel(GoalKind.COMFORT, goal_id="comfort", scope=GoalScope(area_id="living"))
    plan = materialize_comfort_profile(
        goal, profile, entities, options={}, is_admin=True, user_id="user-1"
    )
    actions = [step.action for step in plan.steps if step.action is not None]
    assert len(actions) == 1
    assert actions[0].entity_id == "light.living"
    assert actions[0].data == {"brightness_pct": 50}


def test_missing_comfort_profile_is_not_invented():
    goal = interpret_goal(analyse_language("Mach es hier angenehmer."), voice_area_id="living")
    assert goal is not None and goal.kind is GoalKind.COMFORT
    assert goal.profile_id == "comfort:living"
    assert not goal.desired_states


def test_goal_run_round_trip_and_fact_grounded_effect_explanation(tmp_path):
    goal = GoalModel(
        GoalKind.ACHIEVE_STATE, goal_id="goal_light",
        provenance=GoalProvenance("Mach das Licht aus", "user-1"),
    )
    run = replace(
        GoalRun.start(goal, user_id="user-1", person_entity_id="person.philipp"),
        status=GoalRunStatus.FAILURE,
        failures=(FailureCode.WRONG_STATE,),
        steps=(
            StepExecutionRecord(
                "turn-off", "HOMEASSISTANT_TURN_OFF", ("light.living",),
                ("entity_available",), True,
                (
                    VerificationRecord(
                        "light.living", "off", "on", False,
                        FailureCode.WRONG_STATE,
                    ),
                ),
            ),
        ),
    )
    store = GoalRunStore(tmp_path / "runs.json", limit=5)
    asyncio.run(store.async_append(run))
    loaded = asyncio.run(store.async_latest(user_id="user-1", failed_only=True))
    explanation = explain_goal_run(loaded)
    assert explanation.causality is CausalityLevel.DIRECTLY_OBSERVED
    assert "blieb" not in explanation.message or "on" in explanation.message
    assert "light.living" in explanation.message


def test_attribute_effect_verification_uses_fresh_target_attribute():
    climate = EntitySnapshot(
        "climate.living", "Heizung", "climate", "heat",
        attributes={"temperature": 21.0, "current_temperature": 19.0},
    )
    assert effect_satisfied(climate, "temperature=21.0")
    assert not effect_satisfied(climate, "temperature=22.0")
    assert observed_effect(climate, "temperature=21.0") == "temperature=21.0"


def test_no_notification_explanation_uses_recorded_empty_runtime_query():
    goal = GoalModel(GoalKind.MONITOR_AND_NOTIFY, goal_id="monitor")
    run = replace(
        GoalRun.start(goal, user_id="user-1", person_entity_id="person.philipp"),
        status=GoalRunStatus.SUCCESS,
        evidence=("fresh_runtime_query_empty",),
    )
    explanation = explain_goal_run(run)
    assert explanation.causality is CausalityLevel.DERIVED_FROM_TRACE
    assert "frisch geprüfte Bedingung" in explanation.message


def test_unknown_failure_cause_is_not_invented():
    explanation = explain_goal_run(None)
    assert explanation.causality is CausalityLevel.POSSIBLE_BUT_UNPROVEN
    assert "nicht sicher" in explanation.message


def test_plan_graph_rejects_cycles_and_size_bound():
    goal = Goal(GoalKind.ACHIEVE_STATE)
    cycle = MaterializedPlan(
        "plan", goal,
        (
            PlanStep("a", StepKind.CHECK, "a", dependencies=("b",)),
            PlanStep("b", StepKind.CHECK, "b", dependencies=("a",)),
        ),
        RiskLevel.LOW, False, "cycle",
    )
    try:
        validate_plan_graph(cycle)
    except ValueError as err:
        assert "cycle" in str(err)
    else:
        raise AssertionError("cycle was accepted")
    oversized = replace(cycle, steps=tuple(PlanStep(str(i), StepKind.CHECK, "x") for i in range(3)))
    try:
        validate_plan_graph(oversized, limits=PlanningLimits(max_steps=2))
    except ValueError as err:
        assert "bound" in str(err)
    else:
        raise AssertionError("oversized plan was accepted")


def test_verified_earlier_step_plus_later_effect_failure_is_partial_failure():
    entities = [
        EntitySnapshot("light.one", "Licht eins", "light", "on"),
        EntitySnapshot("light.two", "Licht zwei", "light", "on"),
    ]
    goal = GoalModel(GoalKind.PREPARE_ROUTINE, goal_id="partial")
    plan = MaterializedPlan(
        "plan-partial",
        goal,
        (
            PlanStep("check", StepKind.CHECK, "check"),
            PlanStep(
                "one", StepKind.ACTION, "one", dependencies=("check",),
                action=ServiceCallPlan("homeassistant", "turn_off", "light.one", {}),
                verification={"light.one": "off"},
            ),
            PlanStep(
                "two", StepKind.ACTION, "two", dependencies=("one",),
                action=ServiceCallPlan("homeassistant", "turn_off", "light.two", {}),
                verification={"light.two": "off"},
            ),
        ),
        RiskLevel.LOW,
        True,
        "partial",
    )

    async def refresh():
        return entities

    async def execute(_action, _fresh, _confirmed):
        return type("Outcome", (), {"executed": True, "error": None})()

    async def verify(entity_id, _expected):
        return entity_id == "light.one"

    result = asyncio.run(PlanExecutor(refresh, execute, verify).execute(plan, confirmed=True))
    assert result.status is PlanStatus.PARTIAL_FAILURE


def test_structured_plan_modification_removes_every_child_room_step():
    goal = GoalModel(GoalKind.PREPARE_MOVIE, goal_id="movie")
    plan = MaterializedPlan(
        "plan", goal,
        (
            PlanStep("check", StepKind.CHECK, "check"),
            PlanStep(
                "light", StepKind.ACTION, "Kinderlicht", dependencies=("check",),
                action=ServiceCallPlan("homeassistant", "turn_off", "light.child", {}),
            ),
            PlanStep(
                "cover", StepKind.ACTION, "Kinderrollladen", dependencies=("light",),
                action=ServiceCallPlan("cover", "close_cover", "cover.child", {}),
            ),
            PlanStep(
                "living", StepKind.ACTION, "Wohnzimmer", dependencies=("cover",),
                action=ServiceCallPlan("homeassistant", "turn_off", "light.living", {}),
            ),
        ),
        RiskLevel.LOW, True, "preview",
    )
    entities = [
        EntitySnapshot("light.child", "Kinderlicht", "light", "on", area_id="child", area_name="Kinderzimmer"),
        EntitySnapshot("cover.child", "Kinderrollladen", "cover", "open", area_id="child", area_name="Kinderzimmer"),
        EntitySnapshot("light.living", "Wohnzimmer", "light", "on", area_id="living", area_name="Wohnzimmer"),
    ]
    modified = apply_plan_modification(
        plan, analyse_language("Aber das Kinderzimmer nicht."), entities
    )
    assert modified is not None
    assert [step.step_id for step in modified.steps] == ["check", "living"]
    assert modified.steps[1].dependencies == ("check",)


def test_structured_plan_modification_persistently_reschedules_climate_step():
    goal = GoalModel(GoalKind.PREPARE_NIGHT, goal_id="sleep")
    plan = MaterializedPlan(
        "plan", goal,
        (
            PlanStep("check", StepKind.CHECK, "check"),
            PlanStep(
                "light", StepKind.ACTION, "Licht aus", dependencies=("check",),
                action=ServiceCallPlan("homeassistant", "turn_off", "light.living", {}),
                verification={"light.living": "off"},
            ),
            PlanStep(
                "climate", StepKind.ACTION, "Heizung auf 19 Grad", dependencies=("light",),
                action=ServiceCallPlan(
                    "climate", "set_temperature", "climate.living", {"temperature": 19.0}
                ),
                verification={"climate.living": "temperature=19.0"},
            ),
        ),
        RiskLevel.LOW, True, "preview",
    )
    entities = [
        EntitySnapshot("light.living", "Licht", "light", "on", area_id="living"),
        EntitySnapshot("climate.living", "Heizung", "climate", "heat", area_id="living"),
    ]
    modified = apply_plan_modification(
        plan, analyse_language("Und die Heizung erst um 22 Uhr."), entities
    )
    assert modified is not None
    assert [step.step_id for step in modified.steps] == ["check", "light", "climate"]
    assert modified.steps[2].execute_at_local_time == "22:00"
    assert modified.goal.temporal is not None
    assert modified.goal.temporal.day_part == "22:00"


def test_plan_executor_reports_persistently_scheduled_actions():
    goal = GoalModel(GoalKind.PREPARE_NIGHT, goal_id="sleep")
    step = PlanStep(
        "climate", StepKind.ACTION, "Heizung", action=ServiceCallPlan(
            "climate", "set_temperature", "climate.living", {"temperature": 19.0}
        ),
        verification={"climate.living": "temperature=19.0"},
        execute_at_local_time="22:00",
    )
    plan = MaterializedPlan("plan", goal, (step,), RiskLevel.LOW, True, "preview")
    entities = [EntitySnapshot("climate.living", "Heizung", "climate", "heat")]
    calls: list[str] = []

    async def refresh():
        return entities

    async def execute(_action, _fresh, _confirmed):
        raise AssertionError("scheduled actions must not execute immediately")

    async def verify(_entity_id, _expected):
        raise AssertionError("future effects cannot be verified while scheduling")

    async def schedule(scheduled_step, _fresh, _confirmed):
        calls.append(scheduled_step.step_id)
        return type("Outcome", (), {"executed": True, "error": None})()

    result = asyncio.run(
        PlanExecutor(refresh, execute, verify, schedule).execute(plan, confirmed=True)
    )
    assert result.status is PlanStatus.SCHEDULED
    assert calls == ["climate"]


def test_goal_model_serialization_preserves_monitor_semantics():
    goal = _monitor_goal()
    assert GoalModel.from_dict(goal.to_dict()) == goal


def test_persisted_goal_does_not_encode_policy_bypass():
    goal = GoalModel(
        GoalKind.MONITOR_AND_NOTIFY,
        goal_id="unsafe",
        trigger=GoalTrigger("person_leaves_zone", "person.philipp", "home"),
        provenance=GoalProvenance("Wenn ich gehe, entriegle die Haustür", "user-1", confirmed=True),
        lifecycle=GoalLifecycle.MONITOR,
    )
    assert not hasattr(goal, "policy_override")
    assert not goal.confirmation_required


def test_multiple_runs_have_independent_ids():
    goal = _monitor_goal()
    left = GoalRun.start(goal, user_id="user-1", person_entity_id="person.philipp")
    right = GoalRun.start(goal, user_id="user-1", person_entity_id="person.philipp")
    assert left.run_id != right.run_id


def test_retry_policy_is_bounded_idempotent_and_low_risk_only():
    safe = PlanStep(
        "light", StepKind.ACTION, "Licht aus",
        action=ServiceCallPlan("homeassistant", "turn_off", "light.living", {}),
        idempotent=True,
        risk=RiskLevel.LOW,
    )
    policy = RetryPolicy(max_attempts=2)
    assert may_retry(
        safe, FailureCode.EFFECT_TIMEOUT, completed_attempts=1, policy=policy
    )
    assert not may_retry(
        safe, FailureCode.EFFECT_TIMEOUT, completed_attempts=2, policy=policy
    )
    unsafe = replace(
        safe,
        action=ServiceCallPlan("lock", "unlock", "lock.front", {}),
        risk=RiskLevel.HIGH,
    )
    assert not may_retry(
        unsafe, FailureCode.SERVICE_ERROR, completed_attempts=1, policy=policy
    )


def test_retry_policy_rejects_unbounded_attempt_counts():
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=4)
