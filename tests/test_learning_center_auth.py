"""7.1 Learning Center authorization matrix: filtering happens server-side."""

from __future__ import annotations

import json

from learning_center_harness import (
    ADMIN,
    USER_A,
    USER_B,
    habit_model,
    make_env,
    preference_model,
    run,
    thermal_model,
)

from homeintent.learning_policy import KnowledgeState
from homeintent.model_registry import LearnedKind, LearnedModel, ModelHealth
from homeintent.learning_center import model_ref

from learning_center_harness import NOW


async def _seed(env):
    await env.registry.async_upsert(preference_model(USER_A))
    await env.registry.async_upsert(habit_model(USER_B))
    await env.registry.async_upsert(thermal_model())


def _refs(listing):
    return {item["ref"]: item for item in listing["models"]}


def test_owner_sees_own_personal_preference(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        listing, _ = await env.call(USER_A, "models/list")
        kinds = sorted(item["kind"] for item in listing["models"])
        assert kinds == ["preference", "thermal_model"]
    run(_go())


def test_other_user_never_receives_personal_models_from_backend(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        listing, _ = await env.call(USER_B, "models/list")
        kinds = sorted(item["kind"] for item in listing["models"])
        assert kinds == ["habit", "thermal_model"]
        raw = json.dumps(listing)
        assert "lampe" not in raw and USER_A not in raw and "Stehlampe" not in raw
        summary, _ = await env.call(USER_B, "summary")
        assert summary["preference_count"] == 0
        assert "lampe" not in json.dumps(summary)
        pref_ref = model_ref(preference_model(USER_A).model_id)
        for command in ("models/get", "models/evidence"):
            result, error = await env.call(USER_B, command, ref=pref_ref)
            assert result is None and error[0] == "not_found"
    run(_go())


def test_user_a_cannot_see_user_b_personal_habit(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        listing, _ = await env.call(USER_A, "models/list")
        assert all(item["kind"] != "habit" for item in listing["models"])
        assert "LIGHT_TURN_ON@" not in json.dumps(listing)
    run(_go())


def test_admin_can_inspect_household_and_manage_but_not_read_personal_content(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        listing, _ = await env.call(ADMIN, "models/list")
        items = {item["kind"]: item for item in listing["models"]}
        assert set(items) == {"preference", "habit", "thermal_model"}
        assert items["thermal_model"]["redacted"] is False
        habit = items["habit"]
        assert habit["redacted"] is True and habit["owner_label"] == "Ben"
        assert habit["actions"] == ["forget"]
        assert items["preference"]["subject_label"] == ""
        assert items["preference"]["headline"] is None
        detail, _ = await env.call(ADMIN, "models/get", ref=habit["ref"])
        assert detail["model"]["habit_steps"] == []
        assert detail["model"]["facts"] == []
        assert detail["model"]["technical"]["model_id"] == habit_model(USER_B).model_id
        _result, error = await env.call(ADMIN, "models/evidence", ref=habit["ref"])
        assert error[0] == "not_authorized"
        summary, _ = await env.call(ADMIN, "summary")
        assert not any(item["kind"] == "habit_pending" for item in summary["attention"])
    run(_go())


def test_technical_model_id_is_admin_only(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await env.registry.async_upsert(thermal_model())
        ref = model_ref("thermal:living")
        user_view, _ = await env.call(USER_A, "models/get", ref=ref)
        admin_view, _ = await env.call(ADMIN, "models/get", ref=ref)
        assert user_view["model"]["technical"]["model_id"] is None
        assert admin_view["model"]["technical"]["model_id"] == "thermal:living"
    run(_go())


def test_system_models_are_admin_only(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        fact = LearnedModel(
            "fact:x", LearnedKind.FACT, "x", {}, {}, KnowledgeState.OBSERVED, 0.5, 3,
            NOW, NOW, (), health=ModelHealth.VALID,
        )
        await env.registry.async_upsert(fact)
        user_list, _ = await env.call(USER_A, "models/list")
        admin_list, _ = await env.call(ADMIN, "models/list")
        assert user_list["models"] == []
        assert [item["visibility"] for item in admin_list["models"]] == ["system"]
    run(_go())


def test_non_admin_cannot_reset_all_models(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        result, error = await env.call(USER_A, "models/reset", confirm=True)
        assert result is None and error[0] == "admin_required"
        assert len(await env.registry.async_list()) == 3
        _result, error = await env.call(ADMIN, "models/reset")
        assert error[0] == "invalid_format"  # explicit confirmation is mandatory
        _result, error = await env.call(ADMIN, "models/reset", confirm=False)
        assert error[0] == "invalid_format"
    run(_go())


def test_wrong_user_cannot_confirm_or_reject_another_users_preference(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        ref = model_ref(preference_model(USER_A).model_id)
        for user in (USER_B, ADMIN):
            for command in ("preferences/confirm", "preferences/reject"):
                result, error = await env.call(user, command, ref=ref)
                assert result is None
                assert error[0] in {"not_found", "wrong_owner"}
        model = await env.registry.async_get(preference_model(USER_A).model_id)
        assert model.knowledge_state is KnowledgeState.INFERRED
        assert model.parameters["suggestion_status"] == "new"
    run(_go())


def test_wrong_user_cannot_accept_or_reject_another_users_habit(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        ref = model_ref(habit_model(USER_B).model_id)
        for command in ("habits/accept", "habits/reject", "habits/preview"):
            _result, error = await env.call(USER_A, command, ref=ref)
            assert error[0] == "not_found"
            _result, error = await env.call(ADMIN, command, ref=ref)
            assert error[0] == "wrong_owner"
        assert await env.registry.async_get(habit_model(USER_B).model_id) is not None
        assert not await env.registry.async_is_suppressed(habit_model(USER_B).model_id)
    run(_go())


def test_owner_can_forget_own_personal_model(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        ref = model_ref(preference_model(USER_A).model_id)
        result, error = await env.call(USER_A, "models/forget", ref=ref)
        assert error is None and result["forgotten"] is True
        assert await env.registry.async_get(preference_model(USER_A).model_id) is None
    run(_go())


def test_household_model_forget_requires_admin(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        ref = model_ref("thermal:living")
        _result, error = await env.call(USER_A, "models/forget", ref=ref)
        assert error[0] == "admin_required"
        assert await env.registry.async_get("thermal:living") is not None
        result, error = await env.call(ADMIN, "models/forget", ref=ref)
        assert error is None and result["forgotten"] is True
        assert await env.registry.async_get("thermal:living") is None
    run(_go())


def test_admin_can_forget_other_users_personal_model(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        ref = model_ref(habit_model(USER_B).model_id)
        result, error = await env.call(ADMIN, "models/forget", ref=ref)
        assert error is None and result["forgotten"]
        _result, error = await env.call(USER_A, "models/forget", ref=model_ref(habit_model(USER_B).model_id))
        assert error[0] == "not_found"
    run(_go())


def test_unauthenticated_connection_is_rejected(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        for command in ("summary", "models/list", "permissions/list", "history/list"):
            result, error = await env.call(None, command)
            assert result is None and error[0] == "not_authorized"
    run(_go())


def test_browser_supplied_user_id_is_not_accepted(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        _result, error = await env.call(USER_B, "models/list", user_id=USER_A)
        assert error[0] == "invalid_format"
        _result, error = await env.call(
            USER_B, "preferences/confirm", ref=model_ref(preference_model(USER_A).model_id),
            owner_user_id=USER_B,
        )
        assert error[0] == "invalid_format"
    run(_go())


def test_tombstones_are_admin_only(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        await env.call(USER_A, "models/forget", ref=model_ref(preference_model(USER_A).model_id))
        _result, error = await env.call(USER_A, "tombstones/list")
        assert error[0] == "admin_required"
        result, error = await env.call(ADMIN, "tombstones/list")
        assert error is None
        assert result["tombstones"][0]["suppression_kind"] == "forget"
        assert result["tombstones"][0]["durable"] is False
    run(_go())


def test_denied_mutation_is_audited_without_content(tmp_path):
    async def _go():
        env = await make_env(tmp_path)
        await _seed(env)
        await env.call(USER_B, "preferences/confirm", ref=model_ref(preference_model(USER_A).model_id))
        entries = env.runtime.learning_center_audit.entries()
        assert entries[-1].action == "confirm_preference"
        assert entries[-1].result.startswith("denied:")
        assert USER_B not in entries[-1].actor
        assert env.service_calls() == 0
    run(_go())
