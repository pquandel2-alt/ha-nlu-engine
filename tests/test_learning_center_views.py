"""7.1 Learning Center presentation: status mapping, kinds, facts, evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from learning_center_harness import (
    NOW,
    USER_A,
    habit_model,
    learn_reliability,
    make_env,
    preference_model,
    run,
    thermal_model,
)

from homeintent.learning_center import (
    LearningCenterService,
    LearningCenterSources,
    ModelStatus,
    StaticLabels,
    Viewer,
    action_key,
    model_category,
    model_ref,
    model_status,
    reliability_counts,
)
from homeintent.learning_policy import KnowledgeState
from homeintent.model_registry import LearnedKind, LearnedModel, ModelHealth


def _model(health: ModelHealth, state: KnowledgeState = KnowledgeState.OBSERVED, **changes) -> LearnedModel:
    base = LearnedModel(
        "reliability:LIGHT_TURN_ON:light.kitchen", LearnedKind.RELIABILITY, "light.kitchen",
        {"operator_id": "LIGHT_TURN_ON"}, {"success_rate": 0.9}, state, 0.8, 20,
        NOW - timedelta(days=3), NOW - timedelta(days=1), ("x",), health=health,
    )
    return replace(base, **changes)


@pytest.mark.parametrize(("health", "state", "expected"), [
    (ModelHealth.VALID, KnowledgeState.OBSERVED, ModelStatus.VALID),
    (ModelHealth.VALID, KnowledgeState.INFERRED, ModelStatus.INFERRED),
    (ModelHealth.VALID, KnowledgeState.CONFIRMED, ModelStatus.CONFIRMED),
    (ModelHealth.LOW_CONFIDENCE, KnowledgeState.OBSERVED, ModelStatus.LEARNING),
    (ModelHealth.LOW_CONFIDENCE, KnowledgeState.INFERRED, ModelStatus.LEARNING),
    (ModelHealth.LOW_CONFIDENCE, KnowledgeState.CONFIRMED, ModelStatus.CONFIRMED),
    (ModelHealth.UNRELIABLE, KnowledgeState.OBSERVED, ModelStatus.UNRELIABLE),
    (ModelHealth.STALE, KnowledgeState.OBSERVED, ModelStatus.STALE),
    (ModelHealth.DRIFT_DETECTED, KnowledgeState.OBSERVED, ModelStatus.DRIFT),
    (ModelHealth.INVALID, KnowledgeState.CONFIRMED, ModelStatus.INVALID),
])
def test_every_health_and_knowledge_state_maps_deterministically(health, state, expected):
    assert model_status(_model(health, state), NOW) is expected


def test_health_and_knowledge_authority_are_separate_fields():
    labels = StaticLabels({"light.kitchen": "Küchenlicht"}, {}, {})
    sources = LearningCenterSources(None, None, None, None, None)
    service = LearningCenterService("e", sources, labels, now=NOW)
    item = service.list_item(_model(ModelHealth.LOW_CONFIDENCE, KnowledgeState.INFERRED), Viewer("u", False))
    assert item.health == "low_confidence"
    assert item.knowledge_state == "inferred"
    assert item.status is ModelStatus.LEARNING


def test_expired_model_is_stale_and_invalidation_reason_is_invalid():
    assert model_status(_model(ModelHealth.VALID, expires_at=NOW - timedelta(seconds=1)), NOW) is ModelStatus.STALE
    assert model_status(_model(ModelHealth.VALID, invalidation_reason="binding_changed"), NOW) is ModelStatus.INVALID


def test_unknown_future_health_falls_back_gracefully():
    class FutureHealth(str):
        pass

    model = _model(ModelHealth.VALID)
    object.__setattr__(model, "health", FutureHealth("future_state"))
    assert model_status(model, NOW) is ModelStatus.UNKNOWN


@pytest.mark.parametrize("kind", list(LearnedKind))
def test_every_learned_kind_has_a_category_and_renders(kind):
    labels = StaticLabels({}, {}, {})
    service = LearningCenterService("e", LearningCenterSources(None, None, None, None, None), labels, now=NOW)
    model = replace(_model(ModelHealth.VALID), kind=kind, model_id=f"{kind.value}:x", parameters={})
    viewer = Viewer("admin", True)
    detail = service.detail(model, viewer).to_dict()
    assert detail["category"] == model_category(kind).value
    assert detail["kind"] == kind.value


def test_operator_ids_map_to_closed_action_vocabulary():
    assert action_key("LIGHT_TURN_ON") == "turn_on"
    assert action_key("COVER_OPEN_COVER") == "open_cover"
    assert action_key("climate.set_temperature") == "set_temperature"
    assert action_key("WEIRD_THING") == "other"
    assert action_key(None) == "other"


def test_model_ref_is_opaque_and_url_safe():
    ref = model_ref("reliability:LIGHT_TURN_ON:light.kitchen")
    assert len(ref) == 24 and ref.isalnum()
    assert "light" not in ref


# -- schema-only kinds are never shown as product features ---------------------------

def test_empty_registry_shows_no_categories(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        summary, error = await env.call(USER_A, "summary")
        assert error is None
        assert summary["total_models"] == 0
        assert summary["category_counts"] == {}
        listing, _ = await env.call(USER_A, "models/list")
        assert listing["models"] == []
        assert listing["learning_enabled"] is True
    run(_go())


# -- reliability (real V11 service-acceptance semantics) ----------------------------------

def test_reliability_counts_only_accepted_verified_actions(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await learn_reliability(env, successes=8, failures=1, noops=10, unverified=3)
        listing, _ = await env.call(USER_A, "models/list")
        card = next(item for item in listing["models"] if item["kind"] == "reliability")
        assert card["subject_label"] == "Küchenlicht"
        assert card["action_key"] == "turn_on"
        assert card["sample_count"] == 9  # NOT 22: no-ops and unverified excluded
        assert card["headline"]["key"] == "success_rate"
        assert round(card["headline"]["value"] * 100, 1) == 88.9
        detail, _ = await env.call(USER_A, "models/get", ref=card["ref"])
        facts = {fact["key"]: fact["value"] for fact in detail["model"]["facts"]}
        assert facts["observed_actions"] == 9
        assert facts["verified_successes"] == 8
        assert facts["verified_failures"] == 1
        evidence, error = await env.call(USER_A, "models/evidence", ref=card["ref"])
        assert error is None
        ev = evidence["evidence"]
        assert ev["basis"] == "verified_actions"
        assert {row["evidence_state"] for row in ev["rows"]} <= {"verified_success", "verified_failure"}
        assert len(ev["rows"]) == 9
        assert env.service_calls() == 0
    run(_go())


def test_reliability_counts_helper():
    model = _model(ModelHealth.VALID, sample_count=9, parameters={"success_rate": 8 / 9})
    assert reliability_counts(model) == (8, 1)
    assert reliability_counts(replace(model, parameters={})) is None


def test_valid_reliability_card_shows_valid(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await env.registry.async_upsert(_model(ModelHealth.VALID, sample_count=19,
                                               parameters={"success_rate": 18 / 19}))
        listing, _ = await env.call(USER_A, "models/list")
        card = listing["models"][0]
        assert card["status"] == "valid"
        assert round(card["headline"]["value"] * 100, 1) == 94.7
    run(_go())


# -- effect timing ----------------------------------------------------------------------

def test_effect_timing_detail_shows_observed_quantiles(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await learn_reliability(env, successes=6, failures=0)
        listing, _ = await env.call(USER_A, "models/list")
        card = next(item for item in listing["models"] if item["kind"] == "effect_timing")
        detail, _ = await env.call(USER_A, "models/get", ref=card["ref"])
        keys = {fact["key"] for fact in detail["model"]["facts"]}
        assert {"observations", "median_seconds", "p90_seconds", "p95_seconds"} <= keys
        evidence, _ = await env.call(USER_A, "models/evidence", ref=card["ref"], limit=3)
        assert evidence["evidence"]["basis"] == "verified_timings"
        assert len(evidence["evidence"]["rows"]) == 3
        assert evidence["evidence"]["truncated"] is True
        assert all(row["latency_seconds"] == 2.0 for row in evidence["evidence"]["rows"])
    run(_go())


# -- thermal --------------------------------------------------------------------------

def test_thermal_detail_shows_real_metrics_and_range(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await env.registry.async_upsert(thermal_model())
        listing, _ = await env.call(USER_A, "models/list")
        card = listing["models"][0]
        assert card["category"] == "heating"
        assert card["status"] == "valid"
        detail, _ = await env.call(USER_A, "models/get", ref=card["ref"])
        facts = {fact["key"]: fact for fact in detail["model"]["facts"]}
        assert facts["heating_cycles"]["value"] == 43
        assert facts["holdout_mae_seconds"]["value"] == 192.0
        assert facts["holdout_p90_absolute_error_seconds"]["value"] == 300.0
        assert facts["min_start_temperature"]["value"] == 19.0
        assert facts["max_start_temperature"]["unit"] == "celsius"
        assert detail["model"]["last_observed"]
        evidence, _ = await env.call(USER_A, "models/evidence", ref=card["ref"])
        assert evidence["evidence"]["basis"] == "heating_cycles"
    run(_go())


def test_thermal_missing_optional_metrics_are_omitted_not_zero(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await env.registry.async_upsert(thermal_model(holdout=False))
        listing, _ = await env.call(USER_A, "models/list")
        card = listing["models"][0]
        assert card["headline"] is None
        detail, _ = await env.call(USER_A, "models/get", ref=card["ref"])
        keys = {fact["key"] for fact in detail["model"]["facts"]}
        assert "holdout_mae_seconds" not in keys
        assert "validation_sample_count" not in keys
    run(_go())


@pytest.mark.parametrize(("kwargs", "status"), [
    ({"health": ModelHealth.DRIFT_DETECTED}, "drift"),
    ({"health": ModelHealth.INVALID, "invalidation": "measurement_binding_changed"}, "invalid"),
    ({"expires_at": NOW - timedelta(days=1)}, "stale"),
])
def test_thermal_states(tmp_path, kwargs, status):
    async def _go():
        env = await make_env(tmp_path)
        await env.registry.async_upsert(thermal_model(**kwargs))
        listing, _ = await env.call(USER_A, "models/list")
        assert listing["models"][0]["status"] == status
    run(_go())


# -- habit -------------------------------------------------------------------------------

def test_habit_detail_shows_persisted_sequence_and_opportunities(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await env.registry.async_upsert(habit_model(USER_A))
        listing, _ = await env.call(USER_A, "models/list")
        card = listing["models"][0]
        assert card["kind"] == "habit"
        assert card["subject_label"] == "morning"
        assert set(card["actions"]) == {"accept_habit", "reject_habit", "forget"}
        detail, _ = await env.call(USER_A, "models/get", ref=card["ref"])
        model = detail["model"]
        assert [step["entity_label"] for step in model["habit_steps"]] == [
            "Küchenlicht", "Rollladen Küche", "Kaffeemaschine",
        ]
        facts = {fact["key"]: fact["value"] for fact in model["facts"]}
        assert facts["occurrences"] == 12
        assert facts["opportunities"] == 15
        assert round(facts["support"], 2) == 0.8
    run(_go())


def test_habit_without_optional_metadata_stays_useful(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await env.registry.async_upsert(habit_model(USER_A, sequence="", with_opportunities=False,
                                                    health=ModelHealth.LOW_CONFIDENCE))
        listing, _ = await env.call(USER_A, "models/list")
        card = listing["models"][0]
        assert card["status"] == "learning"
        assert "accept_habit" not in card["actions"]  # no sequence -> no routine
        detail, _ = await env.call(USER_A, "models/get", ref=card["ref"])
        keys = {fact["key"] for fact in detail["model"]["facts"]}
        assert "opportunities" not in keys
        assert detail["model"]["habit_steps"] == []
    run(_go())


# -- preference --------------------------------------------------------------------------

def test_preference_detail_shows_scope_and_support(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await env.registry.async_upsert(preference_model(USER_A))
        listing, _ = await env.call(USER_A, "models/list")
        card = listing["models"][0]
        assert card["status"] == "inferred"
        assert card["knowledge_state"] == "inferred"
        assert card["area_label"] == "living"
        assert card["owner_label"] == "Anna"
        detail, _ = await env.call(USER_A, "models/get", ref=card["ref"])
        choices = detail["model"]["preference_choices"]
        assert choices[0] == {"entity_label": "Stehlampe", "entity_missing": False, "count": 8, "preferred": True}
        facts = {fact["key"]: fact["value"] for fact in detail["model"]["facts"]}
        assert facts["selections"] == 10
        assert facts["support_count"] == 8
    run(_go())


def test_moved_or_deleted_entity_is_not_an_actionable_valid_preference(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await env.registry.async_upsert(preference_model(
            USER_A, entity_id="light.removed", counts={"light.removed": 9, "light.living": 1},
        ))
        summary, _ = await env.call(USER_A, "summary")
        kinds = {item["kind"] for item in summary["attention"]}
        assert "entity_missing" in kinds
        assert "preference_pending" not in kinds
        listing, _ = await env.call(USER_A, "models/list")
        card = listing["models"][0]
        assert card["subject_missing"] is True
    run(_go())


def test_one_malformed_model_does_not_break_the_list(tmp_path, monkeypatch):
    async def _go():
        env = await make_env(tmp_path)
        await env.registry.async_upsert(thermal_model())
        await env.registry.async_upsert(preference_model(USER_A))
        from homeintent import learning_center

        original = learning_center.LearningCenterService.list_item

        def _explode(self, model, viewer):
            if model.kind is LearnedKind.THERMAL_MODEL:
                raise ValueError("broken")
            return original(self, model, viewer)

        monkeypatch.setattr(learning_center.LearningCenterService, "list_item", _explode)
        listing, error = await env.call(USER_A, "models/list")
        assert error is None
        assert [item["kind"] for item in listing["models"]] == ["preference"]
    run(_go())


def test_confidence_is_never_presented_as_probability(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await env.registry.async_upsert(thermal_model())
        listing, _ = await env.call(USER_A, "models/list")
        detail, _ = await env.call(USER_A, "models/get", ref=listing["models"][0]["ref"])
        model = detail["model"]
        assert model["quality_band"] in {"very_low", "low", "medium", "high"}
        assert "probability" not in str(model)
        assert "confidence" not in model  # only as technical quality_score
        assert model["technical"]["quality_score"] == 0.9
    run(_go())


def test_list_pagination_is_bounded(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        for index in range(12):
            await env.registry.async_upsert(replace(
                _model(ModelHealth.VALID), model_id=f"reliability:X:light.l{index}",
                subject=f"light.l{index}", last_observed=NOW - timedelta(minutes=index),
            ))
        page, _ = await env.call(USER_A, "models/list", limit=5)
        assert len(page["models"]) == 5 and page["total"] == 12 and page["next_offset"] == 5
        last, _ = await env.call(USER_A, "models/list", limit=5, offset=10)
        assert len(last["models"]) == 2 and last["next_offset"] is None
        _result, error = await env.call(USER_A, "models/list", limit=1_000_000)
        assert error[0] == "invalid_format"
        _result, error = await env.call(USER_A, "models/evidence", ref="x", limit=51)
        assert error[0] == "invalid_format"
    run(_go())
