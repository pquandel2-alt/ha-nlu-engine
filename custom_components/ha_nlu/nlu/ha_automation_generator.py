"""HA Automation Generator (HomeIntent V5 Teil 7/10, V5.25): the pure
translator from an already-``validate_automation()``-clean ``AutomationModel``
into a Home Assistant-native automation config dict - the exact shape
Home Assistant's own ``config/automation`` HTTP view
(``EditAutomationConfigView._write_value``, upstream ``homeassistant/
components/config/automation.py``) writes into ``automations.yaml``: modern
plural schema keys (``triggers``/``conditions``/``actions``, ``trigger:``/
``condition:``/``action:`` renamed from the legacy ``platform:``/``service:``
inside each item - confirmed against the real upstream source, not guessed
from memory, since getting this wrong risks producing YAML Home Assistant's
own config loader rejects or silently misinterprets).

Pure translation only, no live HA/hassil imports (same ``nlu/`` boundary
``automation_validator.py`` already keeps) - the only "live" piece is
resolving an already-parsed ``TriggerTarget``'s domain/device_class/area
back into concrete ``entity_id``s against the fresh entity list the caller
passes in (``nlu/constraint_resolver.py``'s ``resolve_candidates``, Regel 6 -
the exact same resolution ``automation_action_parser.py``'s own
``_candidates_for_target`` already performs; duplicated here in miniature
rather than imported, since that parser lives outside ``nlu/`` - same
cross-boundary duplication precedent ``automation_model.py``'s/
``action_model.py``'s ``_render_target`` already sets).

Regel 4 ("niemals raten") applied one layer deeper than anywhere else in this
codebase: a handful of ``TriggerType``/``ConditionType``/``ActionType``
values have no faithful, non-invented Home Assistant native-schema
translation given what this project's semantic model actually captures -
``TriggerType.DEVICE``/``ConditionType.DEVICE`` (HA's ``device`` trigger/
condition platforms require an integration-specific ``domain``/``subtype``
this project's ``DeviceSnapshot`` never records), a bare ``TriggerType.WEEKDAY``
(Home Assistant has no standalone "this weekday" trigger platform - only
``condition: time``'s ``weekday`` field, which is why ``ConditionType.WEEKDAY``
*is* translated below), ``ConditionType.DATE`` (no native month/day condition
platform - would require synthesizing a Jinja2 ``template`` condition, a new
and risky translation subsystem this wave does not add), and
``ActionType.WAIT`` (HA's ``wait_template``/``wait_for_trigger`` actions take
a Jinja2 template or a trigger definition, not this project's structured
``ConditionNode`` - the same "would require a template synthesizer" gap).
Each returns a specific ``GenerationError`` member instead of a best-effort
guess - the caller (the not-yet-written Executor/``conversation.py`` wiring)
speaks this back to the user and persists nothing, exactly the same
"refuse, never silently do something wrong" contract
``AutomationValidationError`` already established one stage earlier.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from ..entities import EntitySnapshot
from .action_model import ActionGroup, ActionModel, ActionType, ExecutionMode
from .automation_model import AutomationModel, NumericComparator, SunEvent, TriggerModel, TriggerTarget, TriggerType
from .condition_model import ConditionModel, ConditionNode, ConditionType, LogicalOperator, TimeComparator
from .constraint_resolver import Constraints, resolve_candidates
from .semantic_state import SemanticState


class GenerationError(Enum):
    """Mirrors ``AutomationValidationError``'s "refuse, don't guess" shape,
    one translation stage later (semantic model -> HA-native schema, not
    spoken sentence -> semantic model)."""

    ENTITY_NOT_FOUND = auto()  # target re-resolved against the live entity list yields zero matches
    UNSUPPORTED_STATE = auto()  # a SemanticState this domain/device_class combination cannot express
    UNSUPPORTED_TRIGGER_TYPE = auto()  # DEVICE, bare WEEKDAY - see module docstring
    UNSUPPORTED_CONDITION_TYPE = auto()  # DEVICE, DATE - see module docstring
    UNSUPPORTED_ACTION_TYPE = auto()  # WAIT - see module docstring


@dataclass(frozen=True)
class GenerationResult:
    """``config`` is the full Home Assistant automation dict (minus ``id`` -
    assigning that is the Executor's job, mirroring the real
    ``EditAutomationConfigView`` where the id is decided by the config-view
    caller, not ``_write_value`` itself) when ``error`` is ``None``; ``None``
    otherwise. Same "exactly one of the two is set" contract
    ``AutomationMatchResult``'s ``validation_error`` already follows."""

    config: dict[str, Any] | None
    error: GenerationError | None


# Reverse of ``semantic_state.py``'s ``derive_semantic_state()`` (that
# module's own tables are private/module-local, and this is the only other
# place in the codebase needing the inverse direction - small, stable,
# duplicated rather than imported, same precedent
# ``automation_model.py``'s/``action_model.py``'s ``_render_target`` already
# sets for cross-``nlu/``-module duplication).
_BINARY_SENSOR_OPEN_CLOSE_DEVICE_CLASSES = frozenset({"window", "door", "opening", "garage_door"})
_ON_OFF_DOMAINS = frozenset({"light", "switch", "fan"})


def _raw_state_for_semantic(domain: str | None, device_class: str | None, state: SemanticState) -> str | None:
    if domain == "cover":
        return {SemanticState.OPEN: "open", SemanticState.CLOSED: "closed"}.get(state)
    if domain == "binary_sensor":
        if device_class in _BINARY_SENSOR_OPEN_CLOSE_DEVICE_CLASSES:
            return {SemanticState.OPEN: "on", SemanticState.CLOSED: "off"}.get(state)
        return {SemanticState.ON: "on", SemanticState.OFF: "off"}.get(state)
    if domain in _ON_OFF_DOMAINS:
        return {SemanticState.ON: "on", SemanticState.OFF: "off"}.get(state)
    return None


def _entity_id_field(entities: list[EntitySnapshot]) -> str | list[str]:
    """A bare string for a single entity, a list for multiple - mirrors
    ``service_call.py``'s own ``_entity_id_field`` exactly (same
    cross-boundary duplication reasoning as the module docstring)."""
    ids = [e.entity_id for e in entities]
    return ids[0] if len(ids) == 1 else ids


def _resolve_target_entities(target: TriggerTarget, entities: list[EntitySnapshot]) -> list[EntitySnapshot]:
    """Mirrors ``automation_action_parser.py``'s own ``_candidates_for_target``
    (Regel 6 in spirit - same resolution logic, duplicated in miniature
    because that parser lives outside ``nlu/`` and this module must stay
    inside it, same boundary every other ``nlu/`` module already respects)."""
    if target.entity_id is not None:
        return [e for e in entities if e.entity_id == target.entity_id]
    candidates = resolve_candidates(
        entities,
        Constraints(
            domain=target.domain,
            device_class=target.device_class,
            area_id=target.area_id,
            floor_id=target.floor_id,
        ),
    )
    if target.exclude_entity_ids:
        candidates = [e for e in candidates if e.entity_id not in target.exclude_entity_ids]
    return candidates


def _format_offset(minutes: int) -> str:
    """Minutes (already signed - negative = before, positive = after, see
    ``TriggerModel.offset_minutes``' own comment) as the "±HH:MM:SS" string
    Home Assistant's ``cv.time_period``-based offset fields accept."""
    sign = "-" if minutes < 0 else ""
    total_seconds = abs(minutes) * 60
    hours, remainder = divmod(total_seconds, 3600)
    mins, secs = divmod(remainder, 60)
    return f"{sign}{hours:02d}:{mins:02d}:{secs:02d}"


def _generate_trigger(trigger: TriggerModel, entities: list[EntitySnapshot]) -> tuple[dict[str, Any] | None, GenerationError | None]:
    def identified(config: dict[str, Any]) -> dict[str, Any]:
        if trigger.trigger_id is not None:
            config["id"] = trigger.trigger_id
        return config

    if trigger.type is TriggerType.STATE:
        assert trigger.target is not None and trigger.state is not None
        candidates = _resolve_target_entities(trigger.target, entities)
        if not candidates:
            return None, GenerationError.ENTITY_NOT_FOUND
        domain = trigger.target.domain or candidates[0].domain
        device_class = trigger.target.device_class or candidates[0].device_class
        to_raw = _raw_state_for_semantic(domain, device_class, trigger.state)
        if to_raw is None:
            return None, GenerationError.UNSUPPORTED_STATE
        return identified({"trigger": "state", "entity_id": _entity_id_field(candidates), "to": to_raw}), None

    if trigger.type is TriggerType.NUMERIC_STATE:
        assert trigger.target is not None and trigger.comparator is not None and trigger.threshold is not None
        candidates = _resolve_target_entities(trigger.target, entities)
        if not candidates:
            return None, GenerationError.ENTITY_NOT_FOUND
        key = "above" if trigger.comparator is NumericComparator.ABOVE else "below"
        return identified({"trigger": "numeric_state", "entity_id": _entity_id_field(candidates), key: trigger.threshold}), None

    if trigger.type is TriggerType.PRESENCE:
        assert trigger.target is not None and trigger.target.entity_id is not None
        # Direction-neutral (fires on any state change of the person entity)
        # - mirrors ``automation_preview.py``'s own PRESENCE rendering
        # decision: the upstream parser never records arrival vs. departure,
        # so this is the only truthful translation (see that module's
        # docstring for the full reasoning).
        return identified({"trigger": "state", "entity_id": trigger.target.entity_id}), None

    if trigger.type is TriggerType.SUN:
        assert trigger.sun_event is not None
        event = "sunrise" if trigger.sun_event is SunEvent.SUNRISE else "sunset"
        config: dict[str, Any] = {"trigger": "sun", "event": event}
        if trigger.offset_minutes is not None:
            config["offset"] = _format_offset(trigger.offset_minutes)
        return identified(config), None

    if trigger.type is TriggerType.TIME:
        assert trigger.time_hour is not None
        minute = trigger.time_minute or 0
        second = trigger.time_second or 0
        return identified({"trigger": "time", "at": f"{trigger.time_hour:02d}:{minute:02d}:{second:02d}"}), None

    if trigger.type is TriggerType.CALENDAR:
        assert trigger.calendar_entity_id is not None and trigger.calendar_event is not None
        if not any(
            entity.entity_id == trigger.calendar_entity_id and entity.domain == "calendar"
            for entity in entities
        ):
            return None, GenerationError.ENTITY_NOT_FOUND
        config = {
            "trigger": "calendar",
            "entity_id": trigger.calendar_entity_id,
            "event": trigger.calendar_event,
        }
        if trigger.offset_minutes is not None:
            config["offset"] = _format_offset(trigger.offset_minutes)
        return identified(config), None

    if trigger.type is TriggerType.RELATIVE_TIME:
        # Preview-only. conversation.py must anchor the offset to the
        # confirmation time before generation.
        return None, GenerationError.UNSUPPORTED_TRIGGER_TYPE

    # TriggerType.DEVICE / TriggerType.WEEKDAY - see module docstring.
    return None, GenerationError.UNSUPPORTED_TRIGGER_TYPE


def _generate_condition_leaf(condition: ConditionModel, entities: list[EntitySnapshot]) -> tuple[dict[str, Any] | None, GenerationError | None]:
    if condition.type is ConditionType.STATE:
        assert condition.target is not None and condition.state is not None
        candidates = _resolve_target_entities(condition.target, entities)
        if not candidates:
            return None, GenerationError.ENTITY_NOT_FOUND
        domain = condition.target.domain or candidates[0].domain
        device_class = condition.target.device_class or candidates[0].device_class
        raw_state = _raw_state_for_semantic(domain, device_class, condition.state)
        if raw_state is None:
            return None, GenerationError.UNSUPPORTED_STATE
        return {"condition": "state", "entity_id": _entity_id_field(candidates), "state": raw_state}, None

    if condition.type is ConditionType.NUMERIC:
        assert condition.target is not None and condition.comparator is not None and condition.threshold is not None
        candidates = _resolve_target_entities(condition.target, entities)
        if not candidates:
            return None, GenerationError.ENTITY_NOT_FOUND
        key = "above" if condition.comparator is NumericComparator.ABOVE else "below"
        return {"condition": "numeric_state", "entity_id": _entity_id_field(candidates), key: condition.threshold}, None

    if condition.type is ConditionType.TIME:
        assert condition.time_hour is not None and condition.time_comparator is not None
        minute = condition.time_minute or 0
        key = "before" if condition.time_comparator is TimeComparator.BEFORE else "after"
        return {"condition": "time", key: f"{condition.time_hour:02d}:{minute:02d}:00"}, None

    if condition.type is ConditionType.WEEKDAY:
        assert condition.weekdays
        # HA's ``time`` condition platform natively supports a bare
        # ``weekday`` filter with no before/after bound - unlike
        # ``TriggerType.WEEKDAY`` (no such standalone trigger platform
        # exists, see module docstring), this one has a faithful, direct
        # translation.
        return {"condition": "time", "weekday": list(condition.weekdays)}, None

    if condition.type is ConditionType.SUN:
        assert condition.sun_event is not None and condition.sun_comparator is not None
        event = "sunrise" if condition.sun_event is SunEvent.SUNRISE else "sunset"
        key = "before" if condition.sun_comparator is TimeComparator.BEFORE else "after"
        config: dict[str, Any] = {"condition": "sun", key: event}
        if condition.offset_minutes is not None:
            config[f"{key}_offset"] = _format_offset(condition.offset_minutes)
        return config, None

    if condition.type is ConditionType.PRESENCE:
        assert condition.raw_state is not None
        if condition.target is None:
            # Whole-house "[irgend]jemand ist zuhause" leaf (see
            # ``automation_condition_parser.py``'s ``_parse_presence_condition``
            # docstring - the NOT-wrapper caller negates this into "niemand
            # zuhause") - OR across every known person entity, since HA's
            # own multi-entity ``state`` condition uses AND semantics, the
            # opposite of what "jemand" (someone, i.e. at least one) means.
            person_entities = resolve_candidates(entities, Constraints(domain="person"))
            if not person_entities:
                return None, GenerationError.ENTITY_NOT_FOUND
            return {
                "condition": "or",
                "conditions": [
                    {"condition": "state", "entity_id": e.entity_id, "state": condition.raw_state} for e in person_entities
                ],
            }, None
        candidates = _resolve_target_entities(condition.target, entities)
        if not candidates:
            return None, GenerationError.ENTITY_NOT_FOUND
        return {"condition": "state", "entity_id": _entity_id_field(candidates), "state": condition.raw_state}, None

    if condition.type is ConditionType.ENTITY:
        assert condition.target is not None and condition.raw_state is not None
        candidates = _resolve_target_entities(condition.target, entities)
        if not candidates:
            return None, GenerationError.ENTITY_NOT_FOUND
        return {"condition": "state", "entity_id": _entity_id_field(candidates), "state": condition.raw_state}, None

    if condition.type is ConditionType.CALENDAR_EVENT:
        assert condition.raw_state is not None
        needle = json.dumps(condition.raw_state.casefold(), ensure_ascii=False)
        return {
            "condition": "template",
            "value_template": (
                "{{ " + needle
                + " in (trigger.calendar_event.summary | default('', true) | lower) }}"
            ),
        }, None

    # ConditionType.DEVICE / ConditionType.DATE - see module docstring.
    return None, GenerationError.UNSUPPORTED_CONDITION_TYPE


def _generate_condition_node(node: ConditionNode, entities: list[EntitySnapshot]) -> tuple[dict[str, Any] | None, GenerationError | None]:
    if node.operator is None:
        assert node.condition is not None
        return _generate_condition_leaf(node.condition, entities)

    translated: list[dict[str, Any]] = []
    for child in node.children:
        child_config, error = _generate_condition_node(child, entities)
        if error is not None:
            return None, error
        assert child_config is not None
        translated.append(child_config)

    if node.operator is LogicalOperator.AND:
        return {"condition": "and", "conditions": translated}, None
    if node.operator is LogicalOperator.OR:
        return {"condition": "or", "conditions": translated}, None
    return {"condition": "not", "conditions": translated}, None  # LogicalOperator.NOT


def _generate_action_leaf(action: ActionModel, entities: list[EntitySnapshot]) -> tuple[dict[str, Any] | None, GenerationError | None]:
    if action.type is ActionType.DELAY:
        assert action.delay_seconds is not None
        return {"delay": {"seconds": action.delay_seconds}}, None

    if action.type is ActionType.NOTIFY:
        assert action.message is not None
        # No fixed notify target exists in this project's model (no
        # notify-service/entity vocabulary anywhere upstream) - Home
        # Assistant's always-available, no-configuration-required
        # ``persistent_notification.create`` is the only notify mechanism
        # that needs no invented target (Regel 4).
        return {"action": "persistent_notification.create", "data": {"message": action.message}}, None

    if action.type is ActionType.WAIT:
        assert action.wait_condition is not None
        template, error = _condition_template(action.wait_condition, entities)
        if error is not None:
            return None, (
                GenerationError.UNSUPPORTED_ACTION_TYPE
                if error is GenerationError.UNSUPPORTED_CONDITION_TYPE
                else error
            )
        assert template is not None
        config: dict[str, Any] = {
            "wait_template": "{{ " + template + " }}",
            "continue_on_timeout": False,
        }
        if action.timeout_seconds is not None:
            config["timeout"] = {"seconds": action.timeout_seconds}
        return config, None

    if action.type is ActionType.CHOOSE:
        assert action.if_condition is not None
        condition, error = _generate_condition_node(action.if_condition, entities)
        if error is not None:
            return None, error
        then_steps, error = generate_ha_action_configs(action.then_steps, entities)
        if error is not None:
            return None, error
        else_steps, error = generate_ha_action_configs(action.else_steps, entities)
        if error is not None:
            return None, error
        config = {"if": [condition], "then": then_steps}
        if else_steps:
            config["else"] = else_steps
        return config, None

    assert action.target is not None
    candidates = _resolve_target_entities(action.target, entities)
    if not candidates:
        return None, GenerationError.ENTITY_NOT_FOUND
    domain = action.target.domain or candidates[0].domain

    if action.type is ActionType.TURN_ON:
        service = "cover.open_cover" if domain == "cover" else "homeassistant.turn_on"
        return {"action": service, "target": {"entity_id": _entity_id_field(candidates)}}, None
    if action.type is ActionType.TURN_OFF:
        service = "cover.close_cover" if domain == "cover" else "homeassistant.turn_off"
        return {"action": service, "target": {"entity_id": _entity_id_field(candidates)}}, None
    if action.type is ActionType.SET_BRIGHTNESS:
        assert action.value is not None
        return {
            "action": "light.turn_on",
            "target": {"entity_id": _entity_id_field(candidates)},
            "data": {"brightness_pct": action.value},
        }, None
    if action.type is ActionType.SET_COLOR:
        assert action.color_name is not None
        return {
            "action": "light.turn_on",
            "target": {"entity_id": _entity_id_field(candidates)},
            "data": {"color_name": action.color_name},
        }, None
    if action.type is ActionType.SET_COLOR_TEMPERATURE:
        assert action.color_temp_kelvin is not None
        return {
            "action": "light.turn_on",
            "target": {"entity_id": _entity_id_field(candidates)},
            "data": {"kelvin": action.color_temp_kelvin},
        }, None
    if action.type is ActionType.SET_POSITION:
        assert action.value is not None
        return {
            "action": "cover.set_cover_position",
            "target": {"entity_id": _entity_id_field(candidates)},
            "data": {"position": action.value},
        }, None
    if action.type is ActionType.SET_TEMPERATURE:
        assert action.value is not None
        return {
            "action": "climate.set_temperature",
            "target": {"entity_id": _entity_id_field(candidates)},
            "data": {"temperature": action.value},
        }, None
    assert action.type is ActionType.SET_FAN_SPEED and action.value is not None
    return {
        "action": "fan.turn_on",
        "target": {"entity_id": _entity_id_field(candidates)},
        "data": {"percentage": action.value},
    }, None


def _condition_template(
    node: ConditionNode, entities: list[EntitySnapshot]
) -> tuple[str | None, GenerationError | None]:
    """Compile a bounded condition tree into a deterministic wait template."""
    if node.operator is not None:
        parts: list[str] = []
        for child in node.children:
            value, error = _condition_template(child, entities)
            if error is not None:
                return None, error
            assert value is not None
            parts.append(f"({value})")
        if node.operator is LogicalOperator.NOT:
            return f"not {parts[0]}", None
        joiner = " and " if node.operator is LogicalOperator.AND else " or "
        return joiner.join(parts), None

    assert node.condition is not None
    condition = node.condition
    if condition.type in {ConditionType.STATE, ConditionType.ENTITY, ConditionType.PRESENCE}:
        if condition.target is None:
            return None, GenerationError.UNSUPPORTED_CONDITION_TYPE
        candidates = _resolve_target_entities(condition.target, entities)
        if not candidates:
            return None, GenerationError.ENTITY_NOT_FOUND
        if condition.type is ConditionType.STATE:
            assert condition.state is not None
            raw = _raw_state_for_semantic(
                condition.target.domain or candidates[0].domain,
                condition.target.device_class or candidates[0].device_class,
                condition.state,
            )
        else:
            raw = condition.raw_state
        if raw is None:
            return None, GenerationError.UNSUPPORTED_STATE
        return " and ".join(
            f"is_state('{entity.entity_id}', '{raw}')" for entity in candidates
        ), None
    if condition.type is ConditionType.NUMERIC:
        assert condition.target is not None and condition.threshold is not None and condition.comparator is not None
        candidates = _resolve_target_entities(condition.target, entities)
        if not candidates:
            return None, GenerationError.ENTITY_NOT_FOUND
        operator = ">" if condition.comparator is NumericComparator.ABOVE else "<"
        return " and ".join(
            f"states('{entity.entity_id}') | float(0) {operator} {condition.threshold:g}"
            for entity in candidates
        ), None
    return None, GenerationError.UNSUPPORTED_CONDITION_TYPE


def _generate_action_step(
    step: "ActionModel | ActionGroup", entities: list[EntitySnapshot]
) -> tuple[dict[str, Any] | None, GenerationError | None]:
    if isinstance(step, ActionGroup):
        children: list[dict[str, Any]] = []
        for child in step.steps:
            child_config, error = _generate_action_step(child, entities)
            if error is not None:
                return None, error
            assert child_config is not None
            children.append(child_config)
        key = "parallel" if step.mode is ExecutionMode.PARALLEL else "sequence"
        return {key: children}, None
    return _generate_action_leaf(step, entities)


def generate_ha_action_configs(
    actions: tuple["ActionModel | ActionGroup", ...],
    entities: list[EntitySnapshot],
) -> tuple[list[dict[str, Any]] | None, GenerationError | None]:
    """Public action-only renderer used by safe automation action editing."""
    rendered: list[dict[str, Any]] = []
    for action in actions:
        config, error = _generate_action_step(action, entities)
        if error is not None:
            return None, error
        assert config is not None
        rendered.append(config)
    return rendered, None


def generate_ha_trigger_configs(
    triggers: tuple[TriggerModel, ...], entities: list[EntitySnapshot]
) -> tuple[list[dict[str, Any]] | None, GenerationError | None]:
    """Public trigger-only renderer used by safe automation editing."""
    rendered: list[dict[str, Any]] = []
    for trigger in triggers:
        config, error = _generate_trigger(trigger, entities)
        if error is not None:
            return None, error
        assert config is not None
        rendered.append(config)
    return rendered, None


def generate_ha_condition_configs(
    conditions: tuple[ConditionNode, ...], entities: list[EntitySnapshot]
) -> tuple[list[dict[str, Any]] | None, GenerationError | None]:
    """Public condition-only renderer used by safe automation editing."""
    rendered: list[dict[str, Any]] = []
    for condition in conditions:
        config, error = _generate_condition_node(condition, entities)
        if error is not None:
            return None, error
        assert config is not None
        rendered.append(config)
    return rendered, None


def generate_ha_automation_config(
    model: AutomationModel, entities: list[EntitySnapshot], automation_id: str | None = None
) -> GenerationResult:
    """Translates an already-validated ``AutomationModel`` into a Home
    Assistant-native automation config dict (no ``id`` - the Executor's job,
    see ``GenerationResult``'s own docstring). Re-resolves every target
    against ``entities`` (the confirming turn's fresh entity list, per
    ``PendingAutomationConfirmation``'s own docstring) rather than trusting
    anything cached from parse time - the exact "future HA-generator wave"
    deferral ``automation_action_parser.py``'s ``_build_quantified_target``
    already names.

    Exactly one ``TriggerModel`` is ever present today (``match_automation()``
    never builds more than one) - iterated as a list regardless, so this
    function keeps working unchanged if that ever stops being true.

    ``automation_id`` (new feature, Wave 12 "Einmalige Automation"): when
    ``model.once`` is set, the generated config's own actions end with a
    call to the custom ``ha_nlu.delete_automation`` service, reusing the
    already-existing ``AutomationExecutor.async_delete_automation()`` (Wave
    10) rather than a parallel deletion mechanism (Regel 6). That service
    call needs to know the automation's own future ``automation_id`` - a
    chicken-and-egg problem, since ``AutomationExecutor.async_create_automation()``
    normally only generates that id at persist time, *after* this config
    already exists. The caller (``conversation.py``) resolves this by
    pre-generating the id and passing it in here *and* into
    ``async_create_automation()`` for the same automation, so both sides
    agree. ``automation_id`` is ``None``/ignored for every other (non-once)
    automation - fully backward compatible with every existing caller.
    """
    triggers: list[dict[str, Any]] = []
    triggers_delay_action: dict[str, Any] | None = None
    for trigger in model.triggers:
        trigger_config, error = _generate_trigger(trigger, entities)
        if error is not None:
            return GenerationResult(config=None, error=error)
        assert trigger_config is not None
        triggers.append(trigger_config)
        # A trigger's own post-fire delay (V5.14, "10 Minuten nachdem...")
        # has no Home Assistant trigger-level field - it becomes the first
        # action, run before anything the automation was actually asked to
        # do (see TriggerModel.delay_seconds' own comment: "the delay
        # pushes the actual automation start later").
        if trigger.delay_seconds is not None:
            triggers_delay_action = {"delay": {"seconds": trigger.delay_seconds}}

    conditions: list[dict[str, Any]] = []
    for condition_node in model.conditions:
        condition_config, error = _generate_condition_node(condition_node, entities)
        if error is not None:
            return GenerationResult(config=None, error=error)
        assert condition_config is not None
        conditions.append(condition_config)

    if model.scheduled_for is not None:
        scheduled_date = model.scheduled_for.date().isoformat()
        conditions.append(
            {
                "condition": "template",
                "value_template": (
                    "{{ now().date().isoformat() == '" + scheduled_date + "' }}"
                ),
            }
        )

    actions: list[dict[str, Any]] = []
    if triggers_delay_action is not None:
        actions.append(triggers_delay_action)
    for step in model.actions:
        step_config, error = _generate_action_step(step, entities)
        if error is not None:
            return GenerationResult(config=None, error=error)
        assert step_config is not None
        actions.append(step_config)

    if model.once:
        assert automation_id is not None
        actions.append({"action": "ha_nlu.delete_automation", "data": {"automation_id": automation_id}})
    elif model.max_runs is not None:
        assert automation_id is not None
        actions.append(
            {
                "action": "ha_nlu.record_automation_run",
                "data": {
                    "automation_id": automation_id,
                    "max_runs": model.max_runs,
                },
            }
        )

    config: dict[str, Any] = {"alias": model.source_text, "triggers": triggers, "actions": actions}
    if any(trigger.type is TriggerType.CALENDAR for trigger in model.triggers):
        # Calendar events can overlap; queued prevents a second event from
        # being discarded while the first action sequence is still active.
        config["mode"] = "queued"
    if conditions:
        config["conditions"] = conditions
    return GenerationResult(config=config, error=None)
