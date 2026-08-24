from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.execution_policy import PolicyOutcome, evaluate_service_plan
from ha_nlu.service_call import ServiceCallPlan
from ha_nlu.nlu.context import PendingServiceConfirmation


def test_critical_action_can_be_restricted_to_admins():
    lock = EntitySnapshot("lock.front", "Haustür", "lock", "locked")
    plan = ServiceCallPlan("lock", "unlock", lock.entity_id)

    denied = evaluate_service_plan(
        plan, [lock], {"allow_non_admin_critical": False}, is_admin=False
    )
    allowed = evaluate_service_plan(plan, [lock], {}, is_admin=True)

    assert denied.outcome is PolicyOutcome.DENY
    assert allowed.outcome is PolicyOutcome.CONFIRM


def test_confirmation_threshold_is_configurable():
    cover = EntitySnapshot("cover.office", "Bürorollo", "cover", "closed")
    plan = ServiceCallPlan("cover", "open_cover", cover.entity_id)

    assert evaluate_service_plan(
        plan, [cover], {"confirmation_level": "medium"}, is_admin=True
    ).outcome is PolicyOutcome.CONFIRM
    assert evaluate_service_plan(
        plan, [cover], {"confirmation_level": "high"}, is_admin=True
    ).outcome is PolicyOutcome.ALLOW


def test_target_limit_denies_before_execution():
    entities = [
        EntitySnapshot(f"light.{index}", f"Licht {index}", "light", "off")
        for index in range(4)
    ]
    plan = ServiceCallPlan("homeassistant", "turn_on", [item.entity_id for item in entities])

    decision = evaluate_service_plan(
        plan, entities, {"max_action_targets": 3}, is_admin=True
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert "3 Ziele" in decision.reason


def test_policy_denies_control_of_read_only_entity():
    plan = ServiceCallPlan("light", "turn_on", "light.lesen", {})
    decision = evaluate_service_plan(
        plan,
        [],
        {"read_only_entities": ["light.lesen"]},
        is_admin=True,
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert "nur zum Lesen" in (decision.reason or "")


def test_pending_confirmation_carries_requesting_actor():
    pending = PendingServiceConfirmation(
        ServiceCallPlan("lock", "unlock", "lock.front"),
        "Haustür entriegeln.",
        requested_by_user_id="user-1",
    )
    assert pending.requested_by_user_id == "user-1"
