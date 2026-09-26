"""Compositional notification actions for action-first and action-trailing automations.

Recognizes natural German phrasings for notifications:
  - "benachrichtige Philipp, wenn ..."
  - "sende Philipp eine Nachricht, wenn ..."
  - "schicke eine Push-Nachricht an Philipp, wenn ..."
  - "informiere Philipp, wenn ..."
"""

from __future__ import annotations

import re

from .nlu.action_model import (
    ActionModel,
    ActionType,
    NotificationRecipient,
    NotificationRecipientKind,
)
from .entities import EntitySnapshot, normalize_for_compare
from .nlu.automation_model import TriggerModel, TriggerTarget
from .notification_language import (
    NotificationClause,
    parse_notification_clause,
    trigger_message,
)


class NotificationSemantics:
    """Catalog of notification-related vocabulary and patterns."""

    # Action verb stems that start a notification (action-first).
    # Regex patterns for flexibility in conjugation.
    ACTION_VERB_STEMS = [
        r"benachrichti(?:ge|gen|ger)",
        r"informier(?:e|en|er)",
        r"send(?:e|en|er)",
        r"schick(?:e|en|er)",
        r"sag(?:e|en|er)",
        r"gib(?:t)?|geben|geber",
    ]

    # Notification message synonyms (any order, case-insensitive)
    NOTIFICATION_KEYWORDS = {
        "nachricht", "meldung", "benachrichtigung", "notification",
        "push", "benachrichti", "message", "mitteilung",
    }

    @staticmethod
    def is_notification_pattern(text: str) -> bool:
        """Check if text contains notification-related vocabulary."""
        text_lower = text.lower()
        return any(kw in text_lower for kw in NotificationSemantics.NOTIFICATION_KEYWORDS)


# Message-noun synonyms shared by every pattern below, so each variant
# ("Push-Nachricht", "Push Nachricht", "Benachrichtigung", "Nachricht",
# "Meldung", "Mitteilung") only needs to be listed once.
_MESSAGE_NOUN = (
    r"(?:push[\s-]nachricht|benachrichtigung|nachricht|meldung|mitteilung)"
)

# Recipient-first, infinitive-verb forms: "mich benachrichtigen",
# "Philipp benachrichtigen lassen", optionally wrapped in a modal question
# ("Kannst du ... ?"). This is the original, narrower notification pattern -
# kept alongside the newer imperative/trailing forms below so existing
# recipient-first phrasings keep matching.
_RECIPIENT_FIRST_NOTIFY_RE = re.compile(
    r"^(?:(?:kannst|koenntest|wuerdest)\s+du\s+|bitte\s+)?"
    r"(?P<recipient>mich|mir|uns|[a-zäöüß][a-z0-9äöüß_-]*)\s+"
    r"(?:benachrichtigen|informieren)(?:\s+lassen)?[?.!]*$",
    re.IGNORECASE,
)

# Patterns for action-first forms: verb + recipient (+ optional message type)
# E.g. "benachrichtige Philipp", "informiere mich", "schicke Philipp eine Nachricht"
_ACTION_FIRST_NOTIFY_RE = re.compile(
    r"^(?:(?:kannst|koenntest|wuerdest)\s+du\s+|bitte\s+)?"
    r"(?P<verb>" + "|".join(NotificationSemantics.ACTION_VERB_STEMS) + r")\s+"
    r"(?P<recipient>mich|mir|uns|[a-zäöüß][a-z0-9äöüß_-]*)"
    r"(?:\s+(?:eine\s+)?" + _MESSAGE_NOUN + r")?"
    r"[?.!]*$",
    re.IGNORECASE,
)

# Patterns for action-trailing forms: message type + "an" + recipient, with
# the action verb either leading ("schicke eine Push-Nachricht an Philipp"),
# trailing ("eine Push-Nachricht an Philipp schickt"), or omitted entirely
# ("eine Push-Nachricht an Philipp").
_ACTION_TRAILING_NOTIFY_RE = re.compile(
    r"^(?:(?P<lead_verb>" + "|".join(NotificationSemantics.ACTION_VERB_STEMS) + r")\s+)?"
    r"(?:eine\s+)?" + _MESSAGE_NOUN + r"\s+"
    r"(?:an\s+den|an\s+die|an\s+dem|an|dem|der)\s+"
    r"(?P<recipient>mich|mir|uns|[a-zäöüß][a-z0-9äöüß_-]*)"
    r"(?:\s+(?:schick\w*|send\w*|geb\w*|sag\w*))?"
    r"[?.!]*$",
    re.IGNORECASE,
)


def resolve_notify_target(
    recipient_text: str,
    entities: list[EntitySnapshot] | tuple[EntitySnapshot, ...],
) -> TriggerTarget | None:
    """Resolve a named recipient to a notify.* entity.

    Returns None if:
      - recipient is "mich"/"mir"/"uns" (use default proactive agent channel)
      - no matching notify entity found
      - multiple matching notify entities found (ambiguous)
    """
    if recipient_text.casefold() in {"mich", "mir", "uns"}:
        return None

    recipient_key = normalize_for_compare(recipient_text)
    targets = [
        entity
        for entity in entities
        if entity.domain == "notify"
        and any(
            recipient_key in normalize_for_compare(name)
            for name in (entity.friendly_name, *entity.aliases)
        )
    ]

    if len(targets) == 1:
        return TriggerTarget(domain="notify", entity_id=targets[0].entity_id)

    return None


def is_notification_shaped(action_text: str) -> bool:
    """Check whether ``action_text`` matches one of the recipient-shaped
    notification patterns, independent of whether the recipient actually
    resolves.

    Used by callers to distinguish "this is a notification whose recipient
    is unknown/ambiguous" (a hard failure - never guess, never fall back
    to a different interpretation) from "this isn't a notification at all"
    (safe to fall back to the general action parser).
    """
    action_stripped = action_text.strip()
    return (
        parse_notification_clause(action_stripped) is not None
        or _RECIPIENT_FIRST_NOTIFY_RE.fullmatch(action_stripped) is not None
        or _ACTION_FIRST_NOTIFY_RE.fullmatch(action_stripped) is not None
        or _ACTION_TRAILING_NOTIFY_RE.fullmatch(action_stripped) is not None
    )


def notification_action_from_request(
    action_text: str,
    trigger_text: str,
    entities: list[EntitySnapshot] | tuple[EntitySnapshot, ...] = (),
    trigger: TriggerModel | None = None,
) -> ActionModel | None:
    """Build a recipient-shaped notification whose message describes its trigger.

    Supports action-first forms ("benachrichtige Philipp, wenn..."),
    modal forms ("kannst du mich benachrichtigen, sobald ...") and
    action-trailing forms ("...eine Push-Nachricht an Philipp schickt").

    The recipient is typed (``NotificationRecipient``): "mich"/"mir" is the
    authenticated current user and "uns" the confirmed household - both are
    materialized into exact notify targets before persistence, never left
    as a targetless (persistent) notification.  A named addressee is
    resolved only if exactly one matching notify.* entity exists; otherwise
    ``None`` so the caller refuses instead of silently falling back.

    A clause that dictates its own message ("... dass ...") is not
    recipient-shaped; ``notification_action_from_clause()`` owns it.
    """
    clause = parse_notification_clause(action_text)
    if clause is not None:
        if clause.message is not None or clause.reminder:
            return None
        return notification_action_from_clause(action_text, trigger_text, entities, trigger)

    action_stripped = action_text.strip()
    match = _RECIPIENT_FIRST_NOTIFY_RE.fullmatch(action_stripped)
    if match is None:
        match = _ACTION_FIRST_NOTIFY_RE.fullmatch(action_stripped)
    if match is None:
        match = _ACTION_TRAILING_NOTIFY_RE.fullmatch(action_stripped)
    if match is None:
        return None
    recipient = match.group("recipient")
    lowered = recipient.casefold()
    kind = (
        NotificationRecipientKind.CURRENT_USER if lowered in {"mich", "mir"}
        else NotificationRecipientKind.HOUSEHOLD if lowered == "uns"
        else NotificationRecipientKind.EXPLICIT_TARGET
    )
    return notification_action(
        NotificationClause(kind, recipient if kind is NotificationRecipientKind.EXPLICIT_TARGET else None),
        trigger_message(trigger, trigger_text, entities),
        entities,
    )


def notification_action_from_clause(
    action_text: str,
    trigger_text: str,
    entities: list[EntitySnapshot] | tuple[EntitySnapshot, ...] = (),
    trigger: TriggerModel | None = None,
) -> ActionModel | None:
    """Any notification clause, including a dictated message.

    An explicit message always wins over the trigger-derived description.
    """
    clause = parse_notification_clause(action_text)
    if clause is None:
        return None
    message = clause.message or trigger_message(trigger, trigger_text, entities)
    return notification_action(clause, message, entities)


def notification_action(
    clause: NotificationClause,
    message: str,
    entities: list[EntitySnapshot] | tuple[EntitySnapshot, ...] = (),
) -> ActionModel | None:
    """Typed NOTIFY action for one clause; ``None`` for an unresolved name."""
    if clause.recipient_kind is NotificationRecipientKind.EXPLICIT_TARGET:
        target = resolve_notify_target(clause.recipient_name or "", entities)
        if target is None or target.entity_id is None:
            # No or several matching notify entities - never guess.
            return None
        label = next(
            (item.friendly_name for item in entities if item.entity_id == target.entity_id),
            "",
        )
        return ActionModel(
            type=ActionType.NOTIFY,
            target=target,
            message=message,
            recipient=NotificationRecipient(
                NotificationRecipientKind.EXPLICIT_TARGET,
                entity_ids=(target.entity_id,),
                label=label,
            ),
        )
    return ActionModel(
        type=ActionType.NOTIFY,
        message=message,
        recipient=NotificationRecipient(clause.recipient_kind),
    )
