"""Compositional notification actions for action-first automations."""

from __future__ import annotations

import re

from .nlu.action_model import ActionModel, ActionType
from .entities import EntitySnapshot, normalize_for_compare
from .nlu.automation_model import TriggerTarget

_NOTIFY_ONLY_RE = re.compile(
    r"^(?:(?:kannst|koenntest|wuerdest)\s+du\s+|bitte\s+)?"
    r"(?P<recipient>mich|mir|uns|[a-zäöüß][a-z0-9äöüß_-]*)\s+"
    r"(?:benachrichtigen|informieren)(?:\s+lassen)?[?.!]*$",
    re.IGNORECASE,
)


def notification_action_from_request(
    action_text: str,
    trigger_text: str,
    entities: list[EntitySnapshot] | tuple[EntitySnapshot, ...] = (),
) -> ActionModel | None:
    """Build a notification whose message describes its parsed trigger.

    A named addressee is accepted as natural phrasing, but is not silently
    mapped to a device. The generator therefore uses Home Assistant's local
    persistent notification mechanism, exactly like existing untargeted
    notification actions.
    """
    match = _NOTIFY_ONLY_RE.fullmatch(action_text.strip())
    if match is None:
        return None
    message = re.sub(
        r"^(?:wenn|sobald|falls)\s+", "", trigger_text.strip(), flags=re.IGNORECASE
    ).strip(" ,.!?")
    message = message[:1].upper() + message[1:] if message else "Auslöser eingetreten"
    recipient = match.group("recipient")
    target = None
    if recipient.casefold() not in {"mich", "mir", "uns"}:
        recipient_key = normalize_for_compare(recipient)
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
            target = TriggerTarget(
                domain="notify", entity_id=targets[0].entity_id
            )
    return ActionModel(
        type=ActionType.NOTIFY, target=target, message=f"{message}."
    )
