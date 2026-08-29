"""One policy-gated HA write path shared by conversation and the agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from homeassistant.core import HomeAssistant

from .audit_log import AuditTrail
from .entities import EntitySnapshot
from .execution_policy import PolicyDecision, PolicyOutcome, evaluate_service_plan
from .service_call import ServiceCallPlan


@dataclass(frozen=True)
class ExecutionResult:
    executed: bool
    decision: PolicyDecision
    error: str | None = None


async def async_execute_service_plan(
    hass: HomeAssistant,
    plan: ServiceCallPlan,
    entities: list[EntitySnapshot] | tuple[EntitySnapshot, ...],
    options: Mapping[str, object],
    *,
    is_admin: bool,
    user_id: str | None,
    confirmed: bool,
    audit_trail: AuditTrail | None = None,
    audit_actor_id: str | None = None,
) -> ExecutionResult:
    """Re-evaluate policy immediately before the only physical write."""
    decision = evaluate_service_plan(
        plan, entities, options, is_admin=is_admin, user_id=user_id
    )
    if decision.outcome is PolicyOutcome.DENY:
        return ExecutionResult(False, decision, decision.reason)
    if decision.outcome is PolicyOutcome.CONFIRM and not confirmed:
        return ExecutionResult(False, decision, "Die Aktion benötigt eine Bestätigung.")
    target_ids = (plan.entity_id,) if isinstance(plan.entity_id, str) else tuple(plan.entity_id)
    available_ids = {entity.entity_id for entity in entities}
    if not target_ids or any(entity_id not in available_ids for entity_id in target_ids):
        return ExecutionResult(
            False, decision, "Mindestens ein Ziel ist nicht mehr verfügbar oder freigegeben."
        )
    try:
        await hass.services.async_call(
            plan.domain,
            plan.service,
            {"entity_id": plan.entity_id, **plan.data},
            blocking=True,
        )
    except Exception as err:  # noqa: BLE001 - HA service failures are heterogeneous
        return ExecutionResult(False, decision, str(err))
    if audit_trail is not None:
        from homeassistant.util import dt as dt_util

        audit_trail.record(dt_util.now(), audit_actor_id, plan)
    return ExecutionResult(True, decision)
