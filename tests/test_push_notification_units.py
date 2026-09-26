"""Unit tests for the 7.1.2 notification building blocks."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

from homeassistant.core import HomeAssistant  # noqa: E402

from _notify_sink import NotifySink  # noqa: E402
from homeintent.agent_delivery import AgentDelivery, NotificationDeliveryStatus  # noqa: E402
from homeintent.entities import EntitySnapshot  # noqa: E402
from homeintent.nlu.action_model import (  # noqa: E402
    ActionModel,
    ActionType,
    NotificationRecipient,
    NotificationRecipientKind,
)
from homeintent.nlu.automation_model import AutomationModel, TriggerModel, TriggerTarget, TriggerType  # noqa: E402
from homeintent.nlu.ha_automation_generator import GenerationError, generate_ha_automation_config  # noqa: E402
from homeintent.nlu.semantic_state import SemanticState  # noqa: E402
from homeintent.notification_language import (  # noqa: E402
    describe_state_event,
    message_from_dass_content,
    parse_notification_clause,
)
from homeintent.notification_request import (  # noqa: E402
    NotificationRequest,
    NotificationStage,
    async_deliver_notification_request,
)
from homeintent.notification_target import (  # noqa: E402
    NotificationResolutionStatus,
    NotificationTargetResolver,
    configured_push_targets,
    push_channel_enabled,
)
from homeintent.user_context import NotificationTarget, NotificationTargetKind  # noqa: E402

PHONE = "notify.mobile_app_phone"
WINDOWS = [
    EntitySnapshot("binary_sensor.wz_links", "Wohnzimmer Fenster links", "binary_sensor", "off",
                   area_id="wohnzimmer", area_name="Wohnzimmer", device_class="window"),
    EntitySnapshot("binary_sensor.wz_rechts", "Wohnzimmer Fenster rechts", "binary_sensor", "off",
                   area_id="wohnzimmer", area_name="Wohnzimmer", device_class="window"),
    EntitySnapshot("binary_sensor.kuechenfenster", "Küchenfenster", "binary_sensor", "off",
                   area_id="kueche", area_name="Küche", device_class="window"),
]


# --- delivery primitive -----------------------------------------------------------


def test_entity_push_uses_only_fields_send_message_accepts():
    hass = HomeAssistant()
    sink = NotifySink.install(hass, (PHONE,))
    result = asyncio.run(AgentDelivery(hass).async_send_notification(
        (NotificationTarget(PHONE, NotificationTargetKind.ENTITY),), title="T", message="M"
    ))
    assert result.status is NotificationDeliveryStatus.DELIVERED
    assert sink.notify_calls == [("send_message", {"entity_id": [PHONE], "title": "T", "message": "M"})]


def test_bound_legacy_service_uses_its_own_service():
    hass = HomeAssistant()
    sink = NotifySink.install(hass, legacy_services=("mobile_app_phone",))
    result = asyncio.run(AgentDelivery(hass).async_send_notification(
        (NotificationTarget(PHONE, NotificationTargetKind.SERVICE),), title="T", message="M"
    ))
    assert result.delivered
    assert sink.notify_calls == [("mobile_app_phone", {"title": "T", "message": "M"})]


def test_missing_entity_is_unavailable_and_not_called():
    hass = HomeAssistant()
    sink = NotifySink.install(hass, ())
    result = asyncio.run(AgentDelivery(hass).async_send_notification(
        (NotificationTarget(PHONE, NotificationTargetKind.ENTITY),), title="T", message="M"
    ))
    assert result.status is NotificationDeliveryStatus.UNAVAILABLE
    assert sink.notify_calls == []


def test_no_target_is_never_a_broadcast():
    hass = HomeAssistant()
    sink = NotifySink.install(hass, (PHONE,))
    result = asyncio.run(AgentDelivery(hass).async_send_notification((), title="T", message="M"))
    assert result.status is NotificationDeliveryStatus.FAILED
    assert sink.notify_calls == [] and sink.other_calls == []


def test_request_outcome_is_a_privacy_safe_diagnostic():
    hass = HomeAssistant()
    NotifySink.install(hass, (PHONE,))
    outcome = asyncio.run(async_deliver_notification_request(
        NotificationRequest.test_push(),
        resolver=NotificationTargetResolver(user_contexts=None, configured_targets=(PHONE,)),
        delivery=AgentDelivery(hass),
        user_id="u1",
    ))
    assert outcome.stage is NotificationStage.DELIVERED
    assert outcome.diagnostic() == {
        "stage": "delivered", "push_channel_enabled": True, "target_resolved": True,
        "resolution": "resolved", "target_available": True, "service_accepted": True,
        "reason": "accepted",
    }
    assert PHONE not in str(outcome.diagnostic())


# --- resolver helpers ---------------------------------------------------------------


def test_configured_targets_are_exact_notify_ids_only():
    assert configured_push_targets({"agent_notify_targets": [PHONE, "light.x", PHONE, 3]}) == (PHONE,)
    assert push_channel_enabled({}) is True
    assert push_channel_enabled({"agent_delivery_channels": ["tts"]}) is False


def test_explicit_target_is_not_a_semantic_resolution():
    resolver = NotificationTargetResolver(user_contexts=None, configured_targets=(PHONE,))
    resolution = resolver.resolve(NotificationRecipientKind.EXPLICIT_TARGET, "u1")
    assert resolution.status is NotificationResolutionStatus.UNSUPPORTED


# --- generator ---------------------------------------------------------------------------


def _push_model(recipient: NotificationRecipient) -> AutomationModel:
    return AutomationModel(
        triggers=(TriggerModel(type=TriggerType.STATE, target=TriggerTarget(
            domain="binary_sensor", device_class="window", area_id="wohnzimmer"),
            state=SemanticState.OPEN),),
        actions=(ActionModel(type=ActionType.NOTIFY, message="Hallo", recipient=recipient),),
        source_text="x",
    )


def test_unmaterialized_current_user_is_refused_not_persistent():
    result = generate_ha_automation_config(
        _push_model(NotificationRecipient(NotificationRecipientKind.CURRENT_USER)), WINDOWS,
        automation_id="a1",
    )
    assert result.error is GenerationError.NOTIFY_RECIPIENT_UNRESOLVED


def test_materialized_target_that_disappeared_is_refused():
    recipient = NotificationRecipient(NotificationRecipientKind.CURRENT_USER, entity_ids=(PHONE,))
    result = generate_ha_automation_config(_push_model(recipient), WINDOWS, automation_id="a1")
    assert result.error is GenerationError.ENTITY_NOT_FOUND


def test_legacy_service_binding_generates_its_service():
    recipient = NotificationRecipient(NotificationRecipientKind.CURRENT_USER, service_ids=(PHONE,))
    result = generate_ha_automation_config(_push_model(recipient), WINDOWS, automation_id="a1")
    assert result.config["actions"] == [
        {"action": PHONE, "data": {"message": "Hallo", "title": "HomeIntent"}}
    ]


# --- language realization ---------------------------------------------------------------


@pytest.mark.parametrize(("content", "message"), (
    ("im Wohnzimmer ein Fenster offen ist", "Im Wohnzimmer ist ein Fenster offen."),
    ("das Fenster offen ist", "Das Fenster ist offen."),
    ("der Akku leer ist", "Der Akku ist leer."),
    ("in der Küche das Licht an ist", "In der Küche ist das Licht an."),
    ("ich den Backofen prüfen soll", "Erinnerung: den Backofen prüfen."),
    ("es regnet", "Es regnet."),
))
def test_dass_complement_becomes_a_main_clause(content, message):
    assert message_from_dass_content(content) == message


def test_state_event_descriptions():
    area = TriggerModel(type=TriggerType.STATE, target=TriggerTarget(
        domain="binary_sensor", device_class="window", area_id="wohnzimmer"), state=SemanticState.OPEN)
    single = TriggerModel(type=TriggerType.STATE, target=TriggerTarget(
        domain="binary_sensor", device_class="window", area_id="kueche"), state=SemanticState.CLOSED)
    anywhere = TriggerModel(type=TriggerType.STATE, target=TriggerTarget(
        domain="binary_sensor", device_class="window"), state=SemanticState.OPEN)
    assert describe_state_event(area, WINDOWS).sentence == "Im Wohnzimmer wurde ein Fenster geöffnet."
    assert describe_state_event(single, WINDOWS).sentence == "Das Küchenfenster wurde geschlossen."
    assert describe_state_event(anywhere, WINDOWS).subordinate == "ein Fenster geöffnet wird"


@pytest.mark.parametrize("text", (
    "Sag mir, ob das Fenster offen ist.",
    "Sag mir, dass das Fenster offen ist.",
    "Schick ihm eine Nachricht",
    "Sende dir eine Testnachricht",
    "Schick mir das Protokoll",
    "",
))
def test_structurally_not_a_notification(text):
    assert parse_notification_clause(text) is None
