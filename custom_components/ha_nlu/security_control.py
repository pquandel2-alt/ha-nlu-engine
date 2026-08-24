"""Safety-gated alarm controls using Home Assistant's native services."""

from __future__ import annotations

import re

from .device_control import DeviceControlResult
from .entities import EntitySnapshot, normalize_for_compare
from .service_call import ServiceCallPlan


def _alarm_target(text: str, entities: list[EntitySnapshot]) -> EntitySnapshot | None:
    alarms = [entity for entity in entities if entity.domain == "alarm_control_panel"]
    if len(alarms) == 1:
        return alarms[0]
    value = normalize_for_compare(text)
    selected = [
        entity for entity in alarms
        if any(
            normalize_for_compare(name) in value
            for name in (entity.friendly_name, *entity.aliases)
            if normalize_for_compare(name)
        )
    ]
    return selected[0] if len(selected) == 1 else None


def match_alarm_control(
    text: str, entities: list[EntitySnapshot], *, allow_disarm: bool
) -> DeviceControlResult | None:
    value = normalize_for_compare(text)
    if not re.search(r"\b(?:alarm|alarmanlage|sicherung|scharf|unscharf)\b", value):
        return None
    entity = _alarm_target(text, entities)
    if entity is None:
        return DeviceControlResult(None, "Welche Alarmanlage meinst du?")

    options = [
        (r"\b(?:unscharf|deaktivier|entschaerf|ausschalt)\w*\b", "alarm_disarm", "unscharf geschaltet"),
        (r"\b(?:nachtmodus|nachts?)\b", "alarm_arm_night", "für die Nacht scharf geschaltet"),
        (r"\b(?:abwesend|ausser haus|away)\b", "alarm_arm_away", "für Abwesenheit scharf geschaltet"),
        (r"\b(?:urlaub|ferien)\b", "alarm_arm_vacation", "für Urlaub scharf geschaltet"),
        (r"\b(?:zuhause|anwesend|home)\b", "alarm_arm_home", "für Anwesenheit scharf geschaltet"),
        (r"\b(?:ausloes|auslös|trigger)\w*\b", "alarm_trigger", "ausgelöst"),
    ]
    selected = [(service, speech) for pattern, service, speech in options if re.search(pattern, value)]
    if not selected and re.search(r"\b(?:scharf|aktivier|einschalt)\w*\b", value):
        selected = [("alarm_arm_away", "für Abwesenheit scharf geschaltet")]
    if len(selected) != 1:
        return None
    service, speech = selected[0]
    if service in {"alarm_disarm", "alarm_trigger"} and not allow_disarm:
        return DeviceControlResult(
            None,
            "Diese sicherheitskritische Alarmfunktion ist nur für Administratoren erlaubt.",
        )
    plan = ServiceCallPlan("alarm_control_panel", service, entity.entity_id, {})
    return DeviceControlResult(
        plan, f"{entity.friendly_name} {speech}.",
        requires_confirmation=True, entity=entity,
    )


async def user_is_admin(hass, user_input) -> bool:
    """Resolve HA's authenticated conversation user; absence grants no elevation."""
    context = getattr(user_input, "context", None)
    user_id = getattr(context, "user_id", None)
    if not user_id:
        # Voice pipelines and older test stubs may have no user context. Arm
        # operations remain available; disarm/trigger stay protected.
        return False
    auth = getattr(hass, "auth", None)
    getter = getattr(auth, "async_get_user", None)
    if getter is None:
        return False
    user = await getter(user_id)
    return bool(user and getattr(user, "is_admin", False))


async def user_display_name(hass, user_input) -> str | None:
    context = getattr(user_input, "context", None)
    user_id = getattr(context, "user_id", None)
    auth = getattr(hass, "auth", None)
    getter = getattr(auth, "async_get_user", None)
    if not user_id or getter is None:
        return None
    user = await getter(user_id)
    name = getattr(user, "name", None) if user else None
    return str(name).strip() if name else None
