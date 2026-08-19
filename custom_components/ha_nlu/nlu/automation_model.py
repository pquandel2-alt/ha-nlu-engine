"""Automation Semantic Model (HomeIntent V5 plan, Teil 1/10 + Teil 2/10,
V5.1-V5.3): ``AutomationModel`` is the semantic representation of a spoken
automation request ("Wenn das Küchenfenster geöffnet wird, ...") - it *is*
the AST itself (no separate AST class, mirrors ``nlu/query_command.py``'s
``QueryCommand`` being both the resolved command and the type the executor
consumes).

Kept free of Home Assistant/hassil imports, same boundary as
``nlu/frame.py``/``nlu/query_command.py`` - only ``automation_trigger_parser.py``
(top-level, hassil-aware) constructs these types from spoken text.

V5 Wave 1 scope: only ``triggers`` is ever populated. ``conditions``/
``actions`` exist as empty ``tuple()`` fields now so later Condition-/
Action-Engine waves (V5 Teil 3-4/10) can extend ``AutomationModel`` without
breaking this shape - not used, not guessed, just reserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from .semantic_state import SemanticState

if TYPE_CHECKING:
    # V5 Wave 2 (V5.4-V5.6): condition_model.py imports TriggerTarget/
    # NumericComparator/SunEvent from *this* module, so a real (non-
    # TYPE_CHECKING) import here would cycle. `from __future__ import
    # annotations` above means this annotation is never evaluated at
    # runtime, so the cycle only exists for type checkers, not at import
    # time.
    from .condition_model import ConditionNode

    # V5 Wave 3 (V5.7-V5.12): action_model.py imports TriggerTarget from
    # *this* module (and ConditionNode from condition_model.py, for WAIT) -
    # same TYPE_CHECKING-only cycle-avoidance as ConditionNode above.
    from .action_model import ActionGroup, ActionModel


class TriggerType(Enum):
    """The 7 trigger types HomeIntent V5 Teil 2/10 (V5.3) names.

    ``STATE`` vs. ``NUMERIC_STATE`` deliberately mirrors Home Assistant's own
    split between its ``state`` and ``numeric_state`` trigger platforms
    (equality/transition vs. threshold comparison) rather than merging them -
    the later HA generator (V5.25, a separate future wave) needs exactly
    this distinction to emit the right trigger platform.
    """

    STATE = auto()
    NUMERIC_STATE = auto()
    DEVICE = auto()
    PRESENCE = auto()
    SUN = auto()
    TIME = auto()
    WEEKDAY = auto()


class NumericComparator(Enum):
    """"above"/"below" - Home Assistant's own ``numeric_state`` trigger
    vocabulary (``above``/``below`` keys), not reinvented here."""

    ABOVE = auto()
    BELOW = auto()


class SunEvent(Enum):
    SUNRISE = auto()
    SUNSET = auto()


@dataclass(frozen=True)
class TriggerTarget:
    """What a trigger watches, before any entity is necessarily resolved.

    Mirrors ``nlu/query_command.py``'s ``QueryTarget`` domain/device_class/
    area/entity_id split on purpose: "ein Fenster im Wohnzimmer" stays
    representable as domain+device_class+area alone - ``entity_id`` is only
    set when the spoken sentence named one specific entity unambiguously.
    Binding to a concrete entity earlier than the sentence itself warrants
    would make the model less reusable for later waves (Reasoning/
    Validation still need to pick *which* entity at runtime, not this
    parse-time model).
    """

    domain: str | None = None
    device_class: str | None = None
    area_id: str | None = None
    entity_id: str | None = None
    # V5 Wave 4 (V5.17, "Natural Language Quantifiers in Automations") -
    # reuses parsers.py's QuantifierParser vocabulary/values verbatim
    # (Regel 6): "all"/"both"/"count" (same 3 kinds, same "beide"==exactly-2/
    # "die drei X"==exactly-3 validation rules), populated only by
    # automation_action_parser.py's quantified TURN_ON/TURN_OFF sentences -
    # every other target (triggers, conditions, single-entity actions) keeps
    # these at their default and is completely unaffected.
    quantifier: str | None = None
    quantifier_count: int | None = None  # only set when quantifier == "count"
    exclude_entity_ids: tuple[str, ...] = ()  # entities named via "... außer [dem|der|den] {name}"


@dataclass(frozen=True)
class TriggerModel:
    """One trigger, discriminated by ``type`` rather than 7 subclasses - a
    single dataclass with typed-but-optional fields is easier to inspect,
    compare in tests, and eventually serialize for the future HA generator
    (V5.25) than a class hierarchy would be. Only the fields relevant to
    ``type`` are ever populated; the rest stay at their ``None``/``()``
    default.
    """

    type: TriggerType
    target: TriggerTarget | None = None  # STATE / NUMERIC_STATE / PRESENCE / DEVICE
    state: SemanticState | None = None  # STATE - reuses the existing enum, no new state vocabulary
    comparator: NumericComparator | None = None  # NUMERIC_STATE
    threshold: float | None = None  # NUMERIC_STATE
    device_id: str | None = None  # DEVICE
    device_trigger_type: str | None = None  # DEVICE
    zone_id: str | None = None  # PRESENCE
    sun_event: SunEvent | None = None  # SUN
    offset_minutes: int | None = None  # SUN
    time_hour: int | None = None  # TIME
    time_minute: int | None = None  # TIME
    weekdays: tuple[str, ...] = ()  # WEEKDAY - HA weekday abbreviations, e.g. ("sat", "sun")
    # V5 Wave 4 (V5.14, "Relative Time" - "10 Minuten nachdem ich nach Hause
    # komme") - only ever set on an event-based trigger type (STATE/
    # NUMERIC_STATE/PRESENCE/DEVICE, see automation_trigger_parser.py's
    # _parse_delay_trigger); TIME/SUN/WEEKDAY triggers never carry a delay -
    # they already express an absolute/recurring point in time, "X Minuten
    # nachdem es 20 Uhr ist" is not a sentence any of the 7 trigger grammars
    # accept.
    delay_seconds: int | None = None


@dataclass(frozen=True)
class AutomationModel:
    """The semantic model/AST for one automation request. ``conditions``
    is populated from V5 Wave 2 onward (``ConditionNode`` trees, see
    ``condition_model.py``); ``actions`` is populated from V5 Wave 3 onward
    (``ActionModel``/``ActionGroup``, see ``action_model.py``) - a flat,
    top-level-SEQUENTIAL tuple whose elements may themselves be a nested
    ``ActionGroup`` for an explicit parallel branch (V5.9). No redundant
    top-level ``ActionGroup(mode=SEQUENTIAL)`` wrapper - HA's own action
    lists are sequential by default, so that's this tuple's default shape
    too, same as it always was before this wave.
    """

    triggers: tuple[TriggerModel, ...] = ()
    conditions: tuple["ConditionNode", ...] = ()
    actions: tuple["ActionModel | ActionGroup", ...] = ()
    source_text: str = ""


def _render_target(target: TriggerTarget) -> str:
    parts = [
        f"{field}={value}"
        for field, value in (
            ("domain", target.domain),
            ("device_class", target.device_class),
            ("area_id", target.area_id),
            ("entity_id", target.entity_id),
            ("quantifier", target.quantifier),
            ("quantifier_count", target.quantifier_count),
        )
        if value is not None
    ]
    if target.exclude_entity_ids:
        parts.append(f"exclude_entity_ids={','.join(target.exclude_entity_ids)}")
    return "{" + ", ".join(parts) + "}"


def _render_trigger(trigger: TriggerModel) -> str:
    parts = []
    if trigger.target is not None:
        parts.append(f"target={_render_target(trigger.target)}")
    if trigger.state is not None:
        parts.append(f"state={trigger.state.name}")
    if trigger.comparator is not None:
        parts.append(f"comparator={trigger.comparator.name}")
    if trigger.threshold is not None:
        parts.append(f"threshold={trigger.threshold}")
    if trigger.device_id is not None:
        parts.append(f"device_id={trigger.device_id}")
    if trigger.device_trigger_type is not None:
        parts.append(f"device_trigger_type={trigger.device_trigger_type}")
    if trigger.zone_id is not None:
        parts.append(f"zone_id={trigger.zone_id}")
    if trigger.sun_event is not None:
        parts.append(f"sun_event={trigger.sun_event.name}")
    if trigger.offset_minutes is not None:
        parts.append(f"offset_minutes={trigger.offset_minutes}")
    if trigger.time_hour is not None:
        parts.append(f"time={trigger.time_hour:02d}:{(trigger.time_minute or 0):02d}")
    if trigger.weekdays:
        parts.append(f"weekdays={','.join(trigger.weekdays)}")
    if trigger.delay_seconds is not None:
        parts.append(f"delay_seconds={trigger.delay_seconds}")
    return f"{trigger.type.name}(" + ", ".join(parts) + ")"


def render_automation_tree(model: AutomationModel) -> str:
    """Plain-text debug tree, not a spoken preview (V5.23's Dry-Run text is
    a later, separate wave with its own German wording) - only for logs/
    tests/manual inspection."""
    lines = [f"AutomationModel(source_text={model.source_text!r})"]
    if not model.triggers:
        lines.append("  triggers: (none)")
    else:
        lines.append(f"  triggers ({len(model.triggers)}):")
        for trigger in model.triggers:
            lines.append(f"    - {_render_trigger(trigger)}")
    if not model.conditions:
        lines.append("  conditions: 0")
    else:
        # Function-local import (V5 Wave 2): avoids a module-level import
        # cycle back to condition_model.py, which itself imports
        # TriggerTarget/NumericComparator/SunEvent from this module.
        from .condition_model import render_condition_tree

        lines.append(f"  conditions ({len(model.conditions)}):")
        for condition in model.conditions:
            for line in render_condition_tree(condition, indent=2).splitlines():
                lines.append(line)
    if not model.actions:
        lines.append("  actions: (none)")
    else:
        # Function-local import (V5 Wave 3): avoids a module-level import
        # cycle back to action_model.py, which itself imports TriggerTarget
        # from this module - same reasoning as render_condition_tree above.
        from .action_model import render_action_step

        lines.append(f"  actions ({len(model.actions)}):")
        for action in model.actions:
            for line in render_action_step(action, indent=2).splitlines():
                lines.append(line)
    return "\n".join(lines)
