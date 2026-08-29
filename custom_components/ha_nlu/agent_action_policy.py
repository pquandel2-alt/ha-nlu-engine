"""Closed validation contract for proactive-agent service plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .nlu.automation_operations import validate_registered_operation
from .service_call import ServiceCallPlan


@dataclass(frozen=True)
class AgentActionSpec:
    """One explicitly supported agent action and its accepted payload."""

    target_domains: frozenset[str]
    optional_data: frozenset[str] = frozenset()


CORE_AGENT_ACTIONS: dict[tuple[str, str], AgentActionSpec] = {
    ("homeassistant", "turn_on"): AgentActionSpec(
        frozenset({"light", "switch", "fan", "climate", "humidifier", "input_boolean"})
    ),
    ("homeassistant", "turn_off"): AgentActionSpec(
        frozenset({"light", "switch", "fan", "climate", "humidifier", "input_boolean"})
    ),
    ("homeassistant", "toggle"): AgentActionSpec(
        frozenset({"light", "switch", "fan", "input_boolean"})
    ),
    ("cover", "open_cover"): AgentActionSpec(frozenset({"cover"})),
    ("cover", "close_cover"): AgentActionSpec(frozenset({"cover"})),
    ("cover", "stop_cover"): AgentActionSpec(frozenset({"cover"})),
    ("lock", "lock"): AgentActionSpec(frozenset({"lock"})),
    ("lock", "unlock"): AgentActionSpec(frozenset({"lock"})),
    ("alarm_control_panel", "alarm_disarm"): AgentActionSpec(
        frozenset({"alarm_control_panel"}), frozenset({"code"})
    ),
}

# Target selection belongs exclusively to ``ServiceCallPlan.entity_id``.  HA
# service data may never replace or broaden the target after policy evaluation.
RESERVED_TARGET_DATA_KEYS = frozenset(
    {"entity_id", "device_id", "area_id", "floor_id", "label_id", "target"}
)


def validate_agent_service_plan(plan: ServiceCallPlan) -> str | None:
    """Return an error for a plan outside the proactive agent's closed contract."""
    target_ids = (plan.entity_id,) if isinstance(plan.entity_id, str) else tuple(plan.entity_id)
    if not target_ids or any(not isinstance(item, str) or "." not in item for item in target_ids):
        return "Die vorgeschlagene Aktion enthält kein gültiges Ziel."
    target_domains = frozenset(item.split(".", 1)[0] for item in target_ids)
    data: Mapping[str, object] = plan.data
    if RESERVED_TARGET_DATA_KEYS & frozenset(data):
        return "Aktionsdaten dürfen das validierte Ziel nicht ersetzen."

    core_spec = CORE_AGENT_ACTIONS.get((plan.domain, plan.service))
    if core_spec is not None:
        if not target_domains <= core_spec.target_domains:
            return "Die Ziel-Domain ist für diese Agentenaktion nicht freigegeben."
        if not frozenset(data) <= core_spec.optional_data:
            return "Die Agentenaktion enthält nicht freigegebene Aktionsdaten."
        if not _data_values_are_safe(data):
            return "Die Agentenaktion enthält ungültige Aktionsdaten."
        return None

    if validate_registered_operation(
        plan.domain,
        plan.service,
        data,
        target_domains=target_domains,
    ):
        return None
    return "Die vorgeschlagene Aktion ist nicht freigegeben."


def _data_values_are_safe(data: Mapping[str, object]) -> bool:
    for value in data.values():
        if not isinstance(value, (str, int, float, bool)):
            return False
        if isinstance(value, str) and len(value) > 1000:
            return False
    return True
