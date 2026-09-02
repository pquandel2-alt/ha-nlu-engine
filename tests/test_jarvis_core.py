from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ha_nlu.adapters import (
    FrigateMetadataAdapter,
    HomeAssistantSourceAdapter,
    LocalDocumentIndex,
)
from ha_nlu.agent_config_validation import (
    parse_event_categories,
    validate_documents_directory,
    validate_quiet_time,
)
from ha_nlu.dialog_manager import (
    DialogManager,
    DialogPriority,
    DialogTaskKind,
)
from ha_nlu.document_intent import interpret_document_search
from ha_nlu.devices import DeviceSnapshot
from ha_nlu.entities import EntitySnapshot
from ha_nlu.execution_policy import PolicyDecision, PolicyOutcome
from ha_nlu.house_graph import (
    ConfidenceClass,
    FactProvenance,
    RelationKind,
    RelationSpec,
    build_house_graph,
    parse_relation_specs,
)
from ha_nlu.goal_intent import interpret_goal
from ha_nlu.memory import MemoryKind, MemoryStore
from ha_nlu.memory_intent import MemoryOperation, interpret_memory_intent
from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.planner import (
    Goal,
    GoalKind,
    PlanExecutor,
    PlanStatus,
    materialize_goal,
)
from ha_nlu.proactive_decision import ProactiveDecisionEngine
from ha_nlu.response_planner import (
    DialogAct,
    GermanResponseRealizer,
    PersonaStyle,
    ResponsePlan,
    Urgency,
)
from ha_nlu.risk import RiskLevel
from ha_nlu.situation import (
    EventQuality,
    EventType,
    NormalizedEvent,
    RoutineFeedback,
    RoutineStatistics,
    Situation,
    SituationEvaluator,
    SituationSeverity,
    normalize_state_change,
)
from ha_nlu.world_model import build_world_model


class _ExecutionResult:
    def __init__(self, executed: bool, decision: PolicyDecision, error: str | None = None):
        self.executed = executed
        self.decision = decision
        self.error = error


NOW = datetime(2026, 9, 1, 23, 30, tzinfo=timezone.utc)


def _entities() -> list[EntitySnapshot]:
    return [
        EntitySnapshot(
            "light.floor",
            "Stehlampe",
            "light",
            "on",
            area_id="living",
            area_name="Wohnzimmer",
            floor_id="ground",
            floor_name="Erdgeschoss",
            capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
        ),
        EntitySnapshot(
            "binary_sensor.cellar_window",
            "Kellerfenster",
            "binary_sensor",
            "on",
            area_id="cellar",
            area_name="Keller",
            floor_id="cellar",
            floor_name="Kellergeschoss",
            device_class="window",
        ),
    ]


def test_house_graph_uses_world_model_ids_and_configured_relations():
    entities = _entities()
    devices = [
        DeviceSnapshot("lamp-device", "Stehlampe", entity_ids=("light.floor",))
    ]
    world = build_world_model(entities, devices)
    graph = build_house_graph(
        world,
        [
            RelationSpec(
                "area:living", RelationKind.ADJACENT_TO, "area:cellar"
            )
        ],
    )

    assert graph.node("entity:light.floor") is not None
    relation = graph.evidence(
        "area:living", RelationKind.ADJACENT_TO, "area:cellar"
    )
    assert relation is not None
    assert relation.provenance is FactProvenance.CONFIGURED
    assert graph.related("area:cellar", RelationKind.ADJACENT_TO)[0].node_id == "area:living"
    assert "light.floor" not in repr(graph.redacted_diagnostics())


def test_statistical_graph_relation_is_not_a_fact():
    world = build_world_model(_entities(), [])
    graph = build_house_graph(world)
    relation = graph.add_relation(
        "area:living",
        RelationKind.INFLUENCES,
        "area:cellar",
        provenance=FactProvenance.STATISTICAL,
        confidence=ConfidenceClass.ESTIMATE,
    )
    assert not relation.is_asserted_fact
    assert graph.related(
        "area:living", RelationKind.INFLUENCES, asserted_only=True
    ) == ()


def test_house_relation_configuration_is_typed_and_bounded():
    specs = parse_relation_specs(
        "area:living | adjacent_to | area:cellar\n"
        "entity:light.floor | preferred_device | area:living"
    )
    assert specs[0].kind is RelationKind.ADJACENT_TO
    with pytest.raises(ValueError, match="Beziehungstyp"):
        parse_relation_specs("area:a | guesses | area:b")


def test_memory_requires_confirmation_and_rejects_transcripts(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.sqlite", enabled=True)
    with pytest.raises(ValueError, match="Bestätigung"):
        asyncio.run(
            store.async_remember(
                MemoryKind.PREFERENCE,
                {"temperature": 21},
                provenance=FactProvenance.CONFIRMED_MEMORY,
                confirmed=False,
                person_id="person:owner",
            )
        )
    with pytest.raises(ValueError, match="Sprachtranskripte"):
        asyncio.run(
            store.async_remember(
                MemoryKind.HOUSEHOLD_FACT,
                {"raw_text": "merk dir alles"},
                provenance=FactProvenance.CONFIRMED_MEMORY,
                confirmed=True,
            )
        )


def test_memory_survives_restart_expires_and_forgets_person(tmp_path: Path):
    path = tmp_path / "memory.sqlite"

    async def scenario():
        first = MemoryStore(path, enabled=True)
        kept = await first.async_remember(
            MemoryKind.PREFERENCE,
            {"activity": "television", "light": "entity:light.floor", "brightness": 30},
            provenance=FactProvenance.CONFIRMED_MEMORY,
            confirmed=True,
            person_id="person:owner",
        )
        await first.async_remember(
            MemoryKind.EPISODE,
            {"event_type": "state_changed"},
            provenance=FactProvenance.OBSERVED,
            confirmed=True,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        restarted = MemoryStore(path, enabled=True)
        loaded = await restarted.async_list()
        deleted = await restarted.async_forget_person("person:owner")
        tombstones = await restarted.async_list(include_deleted=True)
        return kept, loaded, deleted, await restarted.async_list(), tombstones

    kept, loaded, deleted, remaining, tombstones = asyncio.run(scenario())
    assert [item.memory_id for item in loaded] == [kept.memory_id]
    assert deleted == 1
    assert remaining == ()
    assert tombstones[0].content == {}
    assert tombstones[0].person_id is None


def test_memory_redacted_export_has_no_content_or_person(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.sqlite", enabled=True)

    async def scenario():
        await store.async_remember(
            MemoryKind.PREFERENCE,
            {"secret": "private"},
            provenance=FactProvenance.CONFIRMED_MEMORY,
            confirmed=True,
            person_id="person:private",
        )
        return await store.async_redacted_export()

    exported = asyncio.run(scenario())
    assert "private" not in repr(exported)
    assert exported["contains_transcripts"] is False


def test_memory_correction_retention_reset_and_working_memory(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.sqlite", enabled=True)
    working = store.working("conv")
    working.remember("selection", "light.floor")
    assert working.facts["selection"] == "light.floor"
    working.forget("selection")
    store.clear_working("conv")

    async def scenario():
        record = await store.async_remember(
            MemoryKind.HOUSEHOLD_FACT,
            {"area": "living"},
            provenance=FactProvenance.CONFIGURED,
            confirmed=True,
        )
        corrected = await store.async_correct(
            record.memory_id, {"area": "cellar"}, confirmed=True
        )
        expired = await store.async_apply_retention({MemoryKind.HOUSEHOLD_FACT: 0})
        second = await store.async_remember(
            MemoryKind.PROCEDURE,
            {"name": "night"},
            provenance=FactProvenance.CONFIRMED_MEMORY,
            confirmed=True,
        )
        reset = await store.async_reset()
        return corrected, expired, second, reset

    corrected, expired, _second, reset = asyncio.run(scenario())
    assert corrected is not None and corrected.content["area"] == "cellar"
    assert expired == 1 and reset == 1


def test_memory_disabled_and_invalid_structured_values_are_safe(tmp_path: Path):
    disabled = MemoryStore(tmp_path / "off.sqlite", enabled=False)
    assert asyncio.run(disabled.async_list()) == ()
    with pytest.raises(RuntimeError, match="deaktiviert"):
        asyncio.run(
            disabled.async_remember(
                MemoryKind.EPISODE,
                {"event": "x"},
                provenance=FactProvenance.OBSERVED,
                confirmed=True,
            )
        )
    enabled = MemoryStore(tmp_path / "on.sqlite", enabled=True)
    with pytest.raises(ValueError, match="JSON"):
        asyncio.run(
            enabled.async_remember(
                MemoryKind.EPISODE,
                {"bad": object()},
                provenance=FactProvenance.OBSERVED,
                confirmed=True,
            )
        )
    with pytest.raises(ValueError, match="Zeitzone"):
        asyncio.run(
            enabled.async_remember(
                MemoryKind.EPISODE,
                {"event": "x"},
                provenance=FactProvenance.OBSERVED,
                confirmed=True,
                expires_at=datetime(2026, 1, 1),
            )
        )


def test_memory_store_applies_configured_default_retention(tmp_path: Path):
    store = MemoryStore(tmp_path / "retention.sqlite", enabled=True, retention_days=7)
    record = asyncio.run(
        store.async_remember(
            MemoryKind.HOUSEHOLD_FACT,
            {"fact": "configured"},
            provenance=FactProvenance.CONFIGURED,
            confirmed=True,
        )
    )
    assert record.expires_at is not None
    lifetime = record.expires_at - record.created_at
    assert timedelta(days=6, hours=23) < lifetime <= timedelta(days=7)


def test_memory_preference_is_structured_after_shared_language_frontend():
    entities = _entities()
    document = analyse_language(
        "Merk dir, dass ich beim Fernsehen nur die Stehlampe auf 30 Prozent möchte.",
        entities,
    )
    request = interpret_memory_intent(document, entities)
    assert request is not None
    assert request.operation is MemoryOperation.REMEMBER_PREFERENCE
    assert request.target_entity_id == "light.floor"
    assert request.content == {"activity": "television", "brightness_percent": 30}


def test_memory_intent_has_no_service_plan_and_scoped_forget_is_typed():
    request = interpret_memory_intent(
        analyse_language("Vergiss alles über meine persönlichen Routinen.", _entities()),
        _entities(),
    )
    assert request is not None and request.operation is MemoryOperation.FORGET_ROUTINES
    assert not hasattr(request, "plan")


def test_event_normalization_and_window_heating_rule():
    window = _entities()[1]
    climate = EntitySnapshot(
        "climate.cellar", "Heizung Keller", "climate", "heating", area_id="cellar"
    )
    event = normalize_state_change(
        window, "off", occurred_at=NOW, occupied=False, operating_mode="away"
    )
    situations = SituationEvaluator().evaluate(event, [window, climate])
    categories = {item.category for item in situations}
    assert event.event_type is EventType.OPENED
    assert {"opening_while_away", "window_heating"} <= categories


@pytest.mark.parametrize("device_class", ["smoke", "carbon_monoxide", "moisture"])
def test_critical_sensor_short_circuits_comfort(device_class: str):
    sensor = EntitySnapshot(
        f"binary_sensor.{device_class}", device_class, "binary_sensor", "on", device_class=device_class
    )
    event = normalize_state_change(sensor, "off", occurred_at=NOW)
    situations = SituationEvaluator().evaluate(event, [sensor])
    assert len(situations) == 1
    assert situations[0].severity is SituationSeverity.CRITICAL


def test_routine_statistics_never_claims_certainty_before_minimum():
    event = NormalizedEvent(
        "evt", EventType.ACTIVATED, "light.floor", "off", "on", NOW,
        "living", (), True, "normal", "home_assistant", EventQuality.GOOD,
    )
    stats = RoutineStatistics(minimum_observations=3)
    stats.observe(event)
    assessment = stats.assess(event)
    assert not assessment.unusual
    assert assessment.confidence == 0
    assert "fehlen" in assessment.uncertainty


def test_response_persona_is_suppressed_for_critical_alarm():
    plan = ResponsePlan(
        DialogAct.WARN,
        "Rauch erkannt. Verlasse das Gebäude.",
        urgency=Urgency.CRITICAL,
        safety_level="critical",
        banter_level=3,
        category="smoke",
    )
    response = GermanResponseRealizer().realize(plan, style=PersonaStyle.JARVIS)
    assert response == plan.result
    assert "gewünscht" not in response.casefold()


def test_explanation_only_uses_supplied_grounded_facts():
    plan = ResponsePlan(
        DialogAct.EXPLAIN, "Ich frage nach.", facts=("presence", "missing")
    )
    response = GermanResponseRealizer().realize(
        plan, grounded_facts={"presence": "Niemand ist als anwesend erfasst."}
    )
    assert "Niemand" in response
    assert "missing" not in response


def test_proactive_auto_is_off_without_explicit_allowlist():
    event = NormalizedEvent(
        "evt", EventType.ACTIVATED, "light.floor", "off", "on", NOW,
        "living", (), False, "away", "home_assistant", EventQuality.GOOD,
    )
    situation = Situation(
        "sit", "light_unoccupied", SituationSeverity.INFO, "Licht an", (), "evt"
    )
    from ha_nlu.agent_event import AgentMode
    from ha_nlu.service_call import ServiceCallPlan

    decision = ProactiveDecisionEngine().decide(
        event,
        situation,
        entities=_entities(),
        options={"agent_auto_enabled": False},
        proposed_action=ServiceCallPlan("homeassistant", "turn_off", "light.floor", {}),
        requested_mode=AgentMode.AUTO,
        now=NOW,
    )
    assert decision.mode is AgentMode.ASK
    assert decision.action is not None


def test_proactive_decision_rejects_stale_duplicate_and_unreachable_observations():
    engine = ProactiveDecisionEngine()
    event = NormalizedEvent(
        "evt", EventType.ACTIVATED, "light.floor", "off", "on", NOW,
        "living", (), False, "away", "home_assistant", EventQuality.GOOD,
    )
    situation = Situation("sit", "comfort", SituationSeverity.INFO, "Info", (), "evt")
    assert not engine.decide(
        event, situation, entities=_entities(), options={}, now=NOW + timedelta(hours=1)
    ).deliver
    assert not engine.decide(
        event, situation, entities=_entities(), options={}, now=NOW, deduplicated=True
    ).deliver
    assert not engine.decide(
        event, situation, entities=_entities(), options={}, now=NOW, reachable=False
    ).deliver


def test_proactive_auto_requires_low_reversible_policy_and_explicit_target():
    from ha_nlu.agent_event import AgentMode
    from ha_nlu.service_call import ServiceCallPlan

    event = NormalizedEvent(
        "evt", EventType.ACTIVATED, "light.floor", "off", "on", NOW,
        "living", (), False, "away", "home_assistant", EventQuality.GOOD,
    )
    situation = Situation("sit", "comfort", SituationSeverity.INFO, "Info", (), "evt")
    decision = ProactiveDecisionEngine().decide(
        event,
        situation,
        entities=_entities(),
        options={"agent_auto_enabled": True, "agent_auto_entity_ids": ["light.floor"]},
        proposed_action=ServiceCallPlan("homeassistant", "turn_off", "light.floor", {}),
        requested_mode=AgentMode.AUTO,
        now=NOW,
    )
    assert decision.mode is AgentMode.AUTO


def test_dialog_manager_priority_user_binding_correction_and_replacement():
    manager = DialogManager()
    now = datetime.now(timezone.utc)
    manager.create(
        "conv",
        "select-light",
        DialogTaskKind.ENTITY_SELECTION,
        DialogPriority.SELECTION,
        candidates=("Stehlampe links", "Stehlampe rechts"),
        missing_slots=("selection",),
        reason="Zwei Geräte passen gleich gut.",
        requested_by_user_id="owner",
        now=now,
    )
    assert "führe" in manager.explain("conv")
    assert manager.select("conv", 2, user_id="guest").completed is False
    selected = manager.select("conv", 2, user_id="owner")
    assert selected.completed
    manager.create(
        "conv", "value", DialogTaskKind.MISSING_SLOT, DialogPriority.FOLLOWUP,
        missing_slots=("value",), now=now,
    )
    corrected = manager.correct("conv", {"value": 40})
    assert corrected.task is not None and corrected.task.slots["value"] == 40
    assert manager.replace_with_complete_command("conv").replaced


def test_planner_materializes_policy_checked_plan_and_revalidates_each_step():
    entities = _entities()
    plan = materialize_goal(
        Goal(GoalKind.PREPARE_NIGHT, {"entity_ids": ["light.floor"]}),
        entities,
        options={},
        is_admin=True,
        user_id="owner",
    )
    refreshes = 0
    executed = 0

    async def refresh():
        nonlocal refreshes
        refreshes += 1
        return _entities()

    async def execute(_plan, _fresh, _confirmed):
        nonlocal executed
        executed += 1
        return _ExecutionResult(
            True, PolicyDecision(PolicyOutcome.ALLOW, RiskLevel.LOW)
        )

    async def verify(_entity_id, expected):
        return expected == "off"

    result = asyncio.run(PlanExecutor(refresh, execute, verify).execute(plan, confirmed=True))
    assert result.status is PlanStatus.COMPLETED
    assert refreshes == len(plan.steps)
    assert executed == 1


def test_planner_stops_after_failed_verification():
    entities = _entities()
    plan = materialize_goal(
        Goal(GoalKind.PREPARE_NIGHT, {"entity_ids": ["light.floor"]}),
        entities,
        options={},
        is_admin=True,
        user_id="owner",
    )
    calls: list[str] = []

    async def refresh():
        return _entities()

    async def execute(action, _fresh, _confirmed):
        calls.append(action.service)
        return _ExecutionResult(True, PolicyDecision(PolicyOutcome.ALLOW, RiskLevel.LOW))

    async def verify(_entity_id, _expected):
        return False

    result = asyncio.run(PlanExecutor(refresh, execute, verify).execute(plan, confirmed=True))
    assert result.status is PlanStatus.STOPPED
    assert calls == ["turn_off", "turn_on"]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Bereite einen Filmabend vor", GoalKind.PREPARE_MOVIE),
        ("Bereite das Haus auf Abwesenheit vor", GoalKind.PREPARE_AWAY),
        ("Schalte unbesetzte Bereiche energiesparend", GoalKind.SAVE_UNOCCUPIED),
        ("Untersuche die Ursache des Zustands", GoalKind.INVESTIGATE_STATE),
    ],
)
def test_closed_goal_interpreter(text: str, kind: GoalKind):
    goal = interpret_goal(analyse_language(text))
    assert goal is not None and goal.kind is kind


def test_local_document_adapter_is_disabled_and_path_safe(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "manual.md").write_text("# Heizung\nDer Filter ist im Keller.", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("privat", encoding="utf-8")
    try:
        (root / "escape.txt").symlink_to(outside)
    except OSError:
        pass
    disabled = LocalDocumentIndex(root, tmp_path / "off.sqlite", enabled=False)
    assert asyncio.run(disabled.async_reindex()) == 0
    index = LocalDocumentIndex(root, tmp_path / "docs.sqlite", enabled=True)
    assert asyncio.run(index.async_reindex()) == 1
    hits = asyncio.run(index.async_search("Filter"))
    assert hits and hits[0].relative_path == "manual.md"
    assert "secret" not in repr(hits)


def test_document_search_is_explicit_and_read_only():
    query = interpret_document_search(
        analyse_language("Suche in meinen lokalen Dokumenten nach Heizungsfilter.")
    )
    assert query == "heizungsfilter"
    assert interpret_document_search(analyse_language("Schalte die Heizung ein")) is None


def test_local_document_adapter_extracts_bounded_pdf_literal_text(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "manual.pdf").write_bytes(
        b"%PDF-1.4\n1 0 obj\n<< /Length 48 >>\nstream\n"
        b"BT /F1 12 Tf 72 720 Td (Heizungsfilter Keller) Tj ET\n"
        b"endstream\nendobj\n%%EOF"
    )
    index = LocalDocumentIndex(root, tmp_path / "index.sqlite", enabled=True)
    assert asyncio.run(index.async_reindex()) == 1
    hits = asyncio.run(index.async_search("Heizungsfilter"))
    assert hits and hits[0].relative_path == "manual.pdf"


def test_frigate_adapter_keeps_detection_as_estimate():
    evidence = FrigateMetadataAdapter().normalize(
        {"id": "123", "label": "person", "camera": "door", "score": 0.81}
    )
    assert evidence is not None
    assert evidence.quality.value == "estimate"
    assert "image" not in evidence.content


def test_adapter_rejects_unknown_metadata_and_ha_source():
    assert FrigateMetadataAdapter().normalize({"id": "1", "label": "dragon"}) is None
    adapter = HomeAssistantSourceAdapter()
    evidence = adapter.wrap(
        "weather", "forecast", {"temperature": 18}, observed_at=NOW
    )
    assert evidence.quality.value == "direct"
    with pytest.raises(ValueError, match="Quelle"):
        adapter.wrap("internet", "x", {}, observed_at=NOW)


def test_agent_options_are_closed_and_path_safe():
    assert validate_quiet_time("22:30") == "22:30"
    assert validate_documents_directory("homeintent/docs") == "homeintent/docs"
    assert parse_event_categories("safety, light_unoccupied") == {
        "safety",
        "light_unoccupied",
    }
    for invalid in ("24:00", "22", "text"):
        with pytest.raises(ValueError):
            validate_quiet_time(invalid)
    for invalid in ("../private", "/etc", "."):
        with pytest.raises(ValueError):
            validate_documents_directory(invalid)
    with pytest.raises(ValueError):
        parse_event_categories("unknown_category")


def test_routine_feedback_suppresses_without_granting_authority():
    stats = RoutineStatistics(minimum_observations=1, anomaly_threshold=0.5)
    stats.record_feedback(RoutineFeedback.LATER, now=NOW)
    event = NormalizedEvent(
        "event:feedback",
        EventType.OPENED,
        "binary_sensor.window",
        "off",
        "on",
        NOW + timedelta(days=1),
        "cellar",
        (),
        False,
        "away",
        "home_assistant",
        EventQuality.GOOD,
        "window",
    )
    assessment = stats.assess(event)
    assert not assessment.unusual
    assert "spaeter" in assessment.relevance
    assert stats.feedback_counts() == {"later": 1}

    stats.record_feedback(RoutineFeedback.IGNORE, now=NOW)
    assessment = stats.assess(event)
    assert not assessment.unusual
    assert "ignoriert" in assessment.normal
