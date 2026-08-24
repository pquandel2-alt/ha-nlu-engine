"""Central, configurable authorization policy for concrete service plans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Mapping

from .const import (
    CONF_ADMIN_ONLY_ENTITIES,
    CONF_ALLOW_NON_ADMIN_CRITICAL,
    CONF_CONFIRMATION_LEVEL,
    CONF_CONTROL_USER_IDS,
    CONF_MAX_ACTION_TARGETS,
    CONF_READ_ONLY_ENTITIES,
)
from .entities import EntitySnapshot
from .risk import RiskLevel, classify_service_plan
from .service_call import ServiceCallPlan


class PolicyOutcome(Enum):
    ALLOW = auto()
    CONFIRM = auto()
    DENY = auto()


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    risk: RiskLevel
    reason: str | None = None


_RISK_BY_OPTION = {
    "medium": RiskLevel.MEDIUM,
    "high": RiskLevel.HIGH,
    "critical": RiskLevel.CRITICAL,
}


def evaluate_service_plan(
    plan: ServiceCallPlan,
    entities: list[EntitySnapshot] | tuple[EntitySnapshot, ...],
    options: Mapping[str, object],
    *,
    is_admin: bool,
    user_id: str | None = None,
) -> PolicyDecision:
    """Evaluate one already-resolved plan; callers must not bypass it."""
    risk = classify_service_plan(plan, entities)
    target_ids = (plan.entity_id,) if isinstance(plan.entity_id, str) else tuple(plan.entity_id)
    configured_users = options.get(CONF_CONTROL_USER_IDS, ())
    allowed_users = (
        set(configured_users)
        if isinstance(configured_users, (list, tuple, set))
        else set()
    )
    if allowed_users and user_id not in allowed_users:
        return PolicyDecision(
            PolicyOutcome.DENY,
            risk,
            "Dieser Benutzer darf HomeIntent nicht zur Gerätesteuerung verwenden.",
        )
    configured_admin_only = options.get(CONF_ADMIN_ONLY_ENTITIES, ())
    admin_only_ids = (
        set(configured_admin_only)
        if isinstance(configured_admin_only, (list, tuple, set))
        else set()
    )
    if not is_admin and set(target_ids) & admin_only_ids:
        return PolicyDecision(
            PolicyOutcome.DENY,
            risk,
            "Mindestens ein Ziel darf nur von Administratoren gesteuert werden.",
        )
    configured_max = options.get(CONF_MAX_ACTION_TARGETS, 50)
    max_targets = configured_max if isinstance(configured_max, int) else 50
    if max_targets < 1:
        max_targets = 1
    if len(set(target_ids)) > max_targets:
        return PolicyDecision(
            PolicyOutcome.DENY,
            risk,
            f"Diese Aktion betrifft mehr als die erlaubten {max_targets} Ziele.",
        )
    configured_read_only = options.get(CONF_READ_ONLY_ENTITIES, ())
    read_only_ids = (
        set(configured_read_only)
        if isinstance(configured_read_only, (list, tuple, set))
        else set()
    )
    if set(target_ids) & read_only_ids:
        return PolicyDecision(
            PolicyOutcome.DENY,
            risk,
            "Mindestens ein Ziel ist in HomeIntent nur zum Lesen freigegeben.",
        )
    if (
        risk is RiskLevel.CRITICAL
        and not is_admin
        and not bool(options.get(CONF_ALLOW_NON_ADMIN_CRITICAL, True))
    ):
        return PolicyDecision(
            PolicyOutcome.DENY,
            risk,
            "Diese sicherheitskritische Aktion ist nur für Administratoren erlaubt.",
        )
    configured_level = options.get(CONF_CONFIRMATION_LEVEL, "high")
    confirmation_level = _RISK_BY_OPTION.get(str(configured_level), RiskLevel.HIGH)
    if risk >= confirmation_level:
        return PolicyDecision(PolicyOutcome.CONFIRM, risk)
    return PolicyDecision(PolicyOutcome.ALLOW, risk)


def validate_automation_action_targets(
    target_ids: frozenset[str] | set[str],
    options: Mapping[str, object],
    *,
    is_admin: bool = True,
    user_id: str | None = None,
) -> str | None:
    """Validate the concrete write scope of a confirmed automation."""
    configured_users = options.get(CONF_CONTROL_USER_IDS, ())
    allowed_users = (
        set(configured_users)
        if isinstance(configured_users, (list, tuple, set))
        else set()
    )
    if allowed_users and user_id not in allowed_users:
        return "Dieser Benutzer darf HomeIntent nicht zur Gerätesteuerung verwenden."

    configured_admin_only = options.get(CONF_ADMIN_ONLY_ENTITIES, ())
    admin_only_ids = (
        set(configured_admin_only)
        if isinstance(configured_admin_only, (list, tuple, set))
        else set()
    )
    if not is_admin and target_ids & admin_only_ids:
        return "Die Automation würde ein nur für Administratoren freigegebenes Ziel steuern."

    configured_max = options.get(CONF_MAX_ACTION_TARGETS, 50)
    max_targets = configured_max if isinstance(configured_max, int) else 50
    max_targets = max(1, max_targets)
    if len(target_ids) > max_targets:
        return f"Die Automation würde mehr als die erlaubten {max_targets} Ziele steuern."

    configured_read_only = options.get(CONF_READ_ONLY_ENTITIES, ())
    read_only_ids = (
        set(configured_read_only)
        if isinstance(configured_read_only, (list, tuple, set))
        else set()
    )
    if target_ids & read_only_ids:
        return "Die Automation würde mindestens ein nur lesbar freigegebenes Ziel steuern."
    return None
