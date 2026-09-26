"""Event clause + notification clause -> one canonical automation (7.2.0).

This is the projection step of the compositional automation reader::

    utterance
      -> prepare_automation_text()          (repairs, STT rejoins, normalize)
      -> segment_notification_automation()  (EVENT clause + NOTIFICATION clause)
      -> read_event_roles() / ground_event() (typed roles -> TriggerModel)
      -> notification_action()              (existing notification authority)
      -> AutomationModel                    (existing validator / preview / writer)

The *canonical meaning* (:class:`CanonicalEventNotification`) is what every
paraphrase of one request must share; paraphrase tests compare it
directly.  Nothing here synthesizes German text for another parser: the
established trigger and condition parsers only ever receive unchanged
source spans (a connector plus its clause) for the event kinds this module
does not type itself - time, sun, presence, weekday.

Home-Assistant-free and strictly typed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Sequence

from .automation_grounding import (
    GroundedEvent,
    GroundingStatus,
    choose_candidate,
    ground_event,
    restrict_to,
)
from .automation_language import (
    ConditionSpan,
    EventRoles,
    NotificationAutomationFrame,
    TemporalEvent,
    condition_split_candidates,
    prepare_automation_text,
    read_event_roles,
    segment_notification_automation,
)
from .automation_notification import notification_action
from .entities import EntitySnapshot
from .nlu.action_model import ActionModel, NotificationRecipientKind
from .nlu.automation_model import AutomationModel, NumericComparator, TriggerModel, TriggerType
from .nlu.automation_validator import AutomationValidationError, validate_automation
from .nlu.condition_model import ConditionModel, ConditionNode, ConditionType, LogicalOperator
from .nlu.measurement import MeasurementProperty, TravelDirection
from .nlu.semantic_state import SemanticState
from .notification_language import NotificationClause, trigger_message

_LOGGER = logging.getLogger(__name__)

TriggerReader = Callable[[str], "TriggerModel | None"]
ConditionReader = Callable[[str], "ConditionNode | None"]


class OutcomeKind(Enum):
    AUTOMATION = auto()
    CLARIFY = auto()
    UNSUPPORTED = auto()


@dataclass(frozen=True)
class CanonicalEvent:
    """Word-order independent meaning of the event."""

    trigger_type: TriggerType
    entity_ids: tuple[str, ...]
    measurement: MeasurementProperty | None = None
    comparator: NumericComparator | None = None
    value: float | None = None
    state: SemanticState | None = None
    direction: TravelDirection | None = None
    for_seconds: int | None = None


@dataclass(frozen=True)
class CanonicalEventNotification:
    """EVENT_NOTIFICATION: who is told what, when."""

    recipient: NotificationRecipientKind
    recipient_name: str | None
    event: CanonicalEvent
    condition_count: int
    explicit_message: str | None


@dataclass(frozen=True)
class EventClarification:
    """Enough state to finish the same draft after "Die linke."."""

    grounded: GroundedEvent
    clause: NotificationClause
    conditions: tuple[ConditionNode, ...]
    source_text: str


@dataclass(frozen=True)
class CompositionTrace:
    """Privacy-safe diagnostics: structure, never the utterance itself."""

    route: str
    order: str | None = None
    connector: str | None = None
    grounding: str | None = None
    reason: str | None = None
    repaired: bool = False
    event_words: int = 0


@dataclass(frozen=True)
class CompositionOutcome:
    kind: OutcomeKind
    model: AutomationModel | None = None
    validation_error: AutomationValidationError | None = None
    speech: str | None = None
    clarification: EventClarification | None = None
    canonical: CanonicalEventNotification | None = None
    trace: CompositionTrace = field(default_factory=lambda: CompositionTrace("none"))


@dataclass(frozen=True)
class EventInterpretation:
    """One event clause read into a trigger plus embedded conditions."""

    trigger: TriggerModel | None
    conditions: tuple[ConditionNode, ...] = ()
    grounded: GroundedEvent | None = None
    typed: bool = False


_UNSUPPORTED_TEXT = {
    "relative_change": (
        "Ich habe verstanden, dass du bei einer relativen Änderung benachrichtigt werden "
        "möchtest (zum Beispiel „um 2 Grad“). Solche Änderungs-Auslöser kann ich noch nicht "
        "sicher erstellen; nenne mir bitte einen festen Wert."
    ),
    "aggregate": (
        "„Alle …“ beschreibt einen Gesamtzustand und kein einzelnes Ereignis. Diesen Auslöser "
        "kann ich noch nicht sicher erstellen."
    ),
    "no_numeric_property": (
        "Für dieses Gerät kenne ich keinen sicheren Prozent- oder Messwert, auf den ich "
        "reagieren könnte."
    ),
    "unit_mismatch": "Die genannte Einheit passt nicht zu diesem Sensor.",
    "half_without_cover": "„Halb“ kann ich nur für Rollläden als Position verstehen.",
    "bare_number": "Bitte nenne die Einheit, zum Beispiel „50 Prozent“.",
    "out_of_range": "Dieser Wert liegt außerhalb des möglichen Bereichs von 0 bis 100 Prozent.",
    "direction_without_position": (
        "Eine Fahrtrichtung kann ich nur zusammen mit einer Rollladenposition auswerten."
    ),
    "mixed_domains": "Die genannten Geräte haben keinen gemeinsamen Messwert.",
}
_GENERIC_UNSUPPORTED = (
    "Ich habe verstanden, dass du bei einem Ereignis benachrichtigt werden möchtest, "
    "konnte das Ereignis aber keinem Gerät oder Zeitpunkt sicher zuordnen."
)


def log_composition_trace(trace: CompositionTrace) -> None:
    """Developer diagnostics (spec §62): structure only, never the utterance.

    Enabled with ``logger: logs: custom_components.homeintent.automation_composition: debug``.
    """
    if _LOGGER.isEnabledFor(logging.DEBUG):
        _LOGGER.debug(
            "automation composition route=%s order=%s connector=%s grounding=%s "
            "reason=%s repaired=%s event_words=%d",
            trace.route, trace.order, trace.connector, trace.grounding,
            trace.reason, trace.repaired, trace.event_words,
        )


def unsupported_text(reason: str | None) -> str:
    return _UNSUPPORTED_TEXT.get(reason or "", _GENERIC_UNSUPPORTED)


def _conditions_for(
    spans: Sequence[ConditionSpan], parse_condition: ConditionReader
) -> tuple[ConditionNode, ...] | None:
    nodes: list[ConditionNode] = []
    for span in spans:
        node = parse_condition(span.text)
        if node is None:
            return None
        nodes.append(ConditionNode(operator=LogicalOperator.NOT, children=(node,)) if span.negated else node)
    return tuple(nodes)


def interpret_event_clause(
    event_text: str,
    connector: str,
    entities: Sequence[EntitySnapshot],
    parse_trigger: TriggerReader,
    parse_condition: ConditionReader,
) -> EventInterpretation:
    """Typed reading first; established parsers only for untyped event kinds."""
    roles = read_event_roles(event_text)
    embedded = _conditions_for(roles.conditions, parse_condition)
    if embedded is None:
        return EventInterpretation(None)
    grounded = ground_event(roles, entities)
    if grounded.status is GroundingStatus.RESOLVED:
        return EventInterpretation(grounded.trigger, embedded, grounded, typed=True)
    # "X und niemand zuhause ist" / "X, aber nur wenn Y": the event plus a
    # condition the established condition parser has to accept verbatim.
    for left, span in condition_split_candidates(roles.source):
        condition = _conditions_for((span,), parse_condition)
        if condition is None:
            continue
        left_roles = read_event_roles(left)
        left_conditions = _conditions_for(left_roles.conditions, parse_condition)
        if left_conditions is None:
            continue
        left_grounded = ground_event(left_roles, entities)
        if left_grounded.status is GroundingStatus.RESOLVED:
            return EventInterpretation(
                left_grounded.trigger, (*embedded, *left_conditions, *condition), left_grounded, typed=True
            )
        if left_grounded.status is GroundingStatus.NOT_APPLICABLE:
            legacy = parse_trigger(f"{connector} {left}")
            if legacy is not None:
                return EventInterpretation(legacy, (*embedded, *left_conditions, *condition))
        elif left_grounded.status is not GroundingStatus.NOT_FOUND:
            return EventInterpretation(
                None, (*embedded, *left_conditions, *condition), left_grounded
            )
    if grounded.status is GroundingStatus.NOT_APPLICABLE:
        legacy = parse_trigger(f"{connector} {roles.source}")
        if legacy is not None:
            return EventInterpretation(legacy, embedded)
        if roles.conditions:
            # The prepositional condition may belong to the untyped trigger.
            legacy = parse_trigger(f"{connector} {event_text.strip(' ,.!?')}")
            if legacy is not None:
                return EventInterpretation(legacy, ())
    return EventInterpretation(None, embedded, grounded)


def temporal_interpretation(temporal: TemporalEvent) -> EventInterpretation:
    """Project a sun/clock phrase straight into the existing trigger model."""
    if temporal.sun_event is not None:
        trigger = TriggerModel(
            type=TriggerType.SUN, sun_event=temporal.sun_event, offset_minutes=temporal.offset_minutes
        )
    else:
        trigger = TriggerModel(
            type=TriggerType.TIME, time_hour=temporal.hour, time_minute=temporal.minute or 0
        )
    conditions: tuple[ConditionNode, ...] = ()
    if temporal.weekdays:
        conditions = (ConditionNode(condition=ConditionModel(
            type=ConditionType.WEEKDAY, weekdays=temporal.weekdays
        )),)
    return EventInterpretation(trigger, conditions, typed=True)


def _canonical(
    trigger: TriggerModel,
    clause: NotificationClause,
    conditions: tuple[ConditionNode, ...],
    grounded: GroundedEvent | None,
) -> CanonicalEventNotification:
    entity_ids = tuple(sorted(entity.entity_id for entity in grounded.candidates)) if grounded else ()
    return CanonicalEventNotification(
        recipient=clause.recipient_kind,
        recipient_name=(clause.recipient_name or "").casefold() or None,
        event=CanonicalEvent(
            trigger_type=trigger.type,
            entity_ids=entity_ids,
            measurement=trigger.measurement,
            comparator=trigger.comparator,
            value=trigger.threshold,
            state=trigger.state,
            direction=trigger.direction,
            for_seconds=trigger.for_seconds,
        ),
        condition_count=len(conditions),
        explicit_message=clause.message,
    )


def build_notification_automation(
    trigger: TriggerModel,
    conditions: tuple[ConditionNode, ...],
    clause: NotificationClause,
    entities: Sequence[EntitySnapshot],
    source_text: str,
    grounded: GroundedEvent | None,
    trace: CompositionTrace,
) -> CompositionOutcome:
    message = clause.message or trigger_message(trigger, "", entities)
    action: ActionModel | None = notification_action(clause, message, entities)
    if action is None:
        name = clause.recipient_name or "diese Person"
        return CompositionOutcome(
            OutcomeKind.CLARIFY,
            speech=(
                f"Ich finde kein eindeutiges Benachrichtigungsziel für {name}. "
                "Wen soll ich benachrichtigen?"
            ),
            trace=CompositionTrace(trace.route, trace.order, trace.connector, "recipient", "recipient_unresolved",
                                   trace.repaired, trace.event_words),
        )
    model = AutomationModel(
        triggers=(trigger,), conditions=conditions, actions=(action,), source_text=source_text
    )
    return CompositionOutcome(
        OutcomeKind.AUTOMATION,
        model=model,
        validation_error=validate_automation(model),
        canonical=_canonical(trigger, clause, conditions, grounded),
        trace=trace,
    )


def compose_event_notification(
    raw_text: str,
    entities: Sequence[EntitySnapshot],
    parse_trigger: TriggerReader,
    parse_condition: ConditionReader,
) -> CompositionOutcome | None:
    """``None`` unless the utterance is an event + notification request."""
    prepared = prepare_automation_text(raw_text)
    frame: NotificationAutomationFrame | None = segment_notification_automation(prepared.text)
    if frame is None:
        return None
    trace = CompositionTrace(
        route="event_notification",
        order=frame.order.name,
        connector=frame.connector,
        repaired=prepared.repaired,
        event_words=len(frame.event_text.split()),
    )
    if frame.notification.reminder or frame.notification.test:
        # "Erinnere mich, wenn ..." and test pushes keep their own routes.
        return None
    if frame.temporal is not None:
        interpreted = temporal_interpretation(frame.temporal)
    else:
        interpreted = interpret_event_clause(
            frame.event_text, frame.connector, entities, parse_trigger, parse_condition
        )
    if interpreted.trigger is not None:
        return build_notification_automation(
            interpreted.trigger, interpreted.conditions, frame.notification, entities,
            raw_text, interpreted.grounded,
            CompositionTrace(trace.route, trace.order, trace.connector,
                             "typed" if interpreted.typed else "established_parser",
                             None, trace.repaired, trace.event_words),
        )
    return failure_outcome(
        interpreted.grounded, frame.notification, raw_text, trace, interpreted.conditions
    )


def failure_outcome(
    grounded: GroundedEvent | None,
    clause: NotificationClause,
    source_text: str,
    trace: CompositionTrace,
    conditions: tuple[ConditionNode, ...] = (),
) -> CompositionOutcome:
    status = grounded.status if grounded is not None else GroundingStatus.NOT_APPLICABLE
    reason = grounded.reason if grounded is not None else None
    failed = CompositionTrace(trace.route, trace.order, trace.connector, status.name, reason,
                              trace.repaired, trace.event_words)
    if grounded is not None and status is GroundingStatus.AMBIGUOUS:
        return CompositionOutcome(
            OutcomeKind.CLARIFY,
            speech=grounded.question,
            clarification=EventClarification(grounded, clause, conditions, source_text),
            trace=failed,
        )
    if grounded is not None and status in {GroundingStatus.MISSING_SUBJECT, GroundingStatus.NOT_FOUND}:
        return CompositionOutcome(OutcomeKind.CLARIFY, speech=grounded.question, trace=failed)
    return CompositionOutcome(OutcomeKind.UNSUPPORTED, speech=unsupported_text(reason), trace=failed)


def resolve_event_clarification(
    reply: str,
    pending: EventClarification,
    entities: Sequence[EntitySnapshot],
) -> CompositionOutcome | None:
    """Finish the same draft with the chosen candidate; ``None`` if the reply
    does not pick exactly one of them (then it is not an answer)."""
    chosen = choose_candidate(reply, pending.grounded.candidates)
    if chosen is None:
        return None
    grounded = restrict_to(pending.grounded, chosen, entities)
    if grounded.trigger is None:
        return None
    return build_notification_automation(
        grounded.trigger, pending.conditions, pending.clause, entities,
        pending.source_text, grounded, CompositionTrace("event_notification_followup", grounding="typed"),
    )


__all__ = (
    "CanonicalEvent",
    "CanonicalEventNotification",
    "CompositionOutcome",
    "CompositionTrace",
    "EventClarification",
    "EventInterpretation",
    "EventRoles",
    "OutcomeKind",
    "compose_event_notification",
    "failure_outcome",
    "interpret_event_clause",
    "log_composition_trace",
    "resolve_event_clarification",
    "unsupported_text",
)
