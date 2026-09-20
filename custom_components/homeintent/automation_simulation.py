"""Read-only explanation of an existing HomeIntent automation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, cast

from .automation_summary import AutomationSummary
from .entities import EntitySnapshot


@dataclass(frozen=True)
class AutomationSimulation:
    """Bounded dry-run result; it never represents executable work."""

    ready: bool | None
    condition_details: tuple[str, ...]
    action_details: tuple[str, ...]


def _entity_label(entity_id: str, index: Mapping[str, EntitySnapshot]) -> str:
    entity = index.get(entity_id)
    return entity.friendly_name if entity is not None else entity_id


def _entity_ids(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        values = cast(list[object], value)
        return tuple(item for item in values if isinstance(item, str))
    return ()


def simulate_automation(
    automation: AutomationSummary,
    entities: list[EntitySnapshot],
) -> AutomationSimulation:
    """Evaluate supported conditions and describe actions without executing."""
    index = {entity.entity_id: entity for entity in entities}
    condition_results: list[bool | None] = []
    condition_details: list[str] = []
    for condition in automation.conditions:
        kind = condition.get("condition")
        entity_ids = _entity_ids(condition.get("entity_id"))
        if kind == "state" and entity_ids and isinstance(condition.get("state"), str):
            expected = str(condition["state"])
            matched = all(
                entity_id in index and index[entity_id].state == expected
                for entity_id in entity_ids
            )
            condition_results.append(matched)
            labels = ", ".join(_entity_label(item, index) for item in entity_ids)
            condition_details.append(
                f"{labels} ist {'wie gefordert' if matched else 'nicht'} {expected}"
            )
        elif kind == "numeric_state" and len(entity_ids) == 1:
            entity = index.get(entity_ids[0])
            try:
                actual = float(entity.state) if entity is not None else None
                above = float(condition["above"]) if "above" in condition else None
                below = float(condition["below"]) if "below" in condition else None
            except (TypeError, ValueError):
                actual = above = below = None
            matched = (
                (above is None or actual > above)
                and (below is None or actual < below)
            ) if actual is not None else None
            condition_results.append(matched)
            condition_details.append(
                f"{_entity_label(entity_ids[0], index)} hat den Wert {actual:g}"
                if actual is not None
                else f"{_entity_label(entity_ids[0], index)} ist numerisch nicht auswertbar"
            )
        else:
            condition_results.append(None)
            condition_details.append(
                f"Bedingung vom Typ {kind or 'unbekannt'} kann ich offline nicht sicher bewerten"
            )

    action_details: list[str] = []
    for action in automation.actions:
        service = action.get("action", action.get("service"))
        target = action.get("target")
        if isinstance(target, Mapping):
            target_mapping = cast(Mapping[str, object], target)
            target_ids = _entity_ids(target_mapping.get("entity_id"))
        else:
            target_ids = _entity_ids(action.get("entity_id"))
        if isinstance(service, str):
            operation = service.rsplit(".", 1)[-1].replace("_", " ")
            labels = ", ".join(_entity_label(item, index) for item in target_ids)
            action_details.append(
                f"{operation} für {labels}" if labels else operation
            )
        elif "delay" in action:
            action_details.append(f"wartet {action['delay']}")
        else:
            action_details.append("führt eine nicht näher beschreibbare Aktion aus")

    ready = (
        False if not automation.enabled or False in condition_results
        else None if None in condition_results
        else True
    )
    return AutomationSimulation(ready, tuple(condition_details), tuple(action_details))


def render_automation_simulation(
    automation: AutomationSummary,
    entities: list[EntitySnapshot],
) -> str:
    """Render a transparent German dry-run with an explicit trigger caveat."""
    result = simulate_automation(automation, entities)
    readiness = (
        "Die Automation wäre nach den aktuell lesbaren Bedingungen bereit."
        if result.ready is True
        else "Die Automation würde unter den aktuellen Bedingungen nicht laufen."
        if result.ready is False
        else "Nicht alle Bedingungen lassen sich aus dem aktuellen Zustand sicher bewerten."
    )
    conditions = (
        " Bedingungen: " + "; ".join(result.condition_details) + "."
        if result.condition_details else " Es gibt keine Bedingungen."
    )
    actions = (
        " Vorgesehene Aktionen: " + "; ".join(result.action_details) + "."
        if result.action_details else " Es sind keine Aktionen hinterlegt."
    )
    return (
        readiness + conditions + actions
        + " Dies ist nur eine Simulation; ereignisbasierte Auslöser werden nicht ausgelöst."
    )
