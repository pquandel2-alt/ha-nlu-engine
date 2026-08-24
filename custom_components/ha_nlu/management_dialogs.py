"""Conversation orchestration for calendar and automation-edit dialogs."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import conversation
from homeassistant.helpers import intent

from .automation_action_edit import select_candidate_reply
from .automation_executor import AutomationExecutor
from .calendar_management import (
    CalendarManagementKind,
    CalendarManagementRequest,
    flatten_calendar_response,
    render_calendar_events,
)
from .calendar_runtime import (
    async_delete_calendar_event,
    async_get_mutable_calendar_events,
    async_reschedule_calendar_event,
)
from .entities import EntitySnapshot, normalize_for_compare
from .nlu.automation_confirmation import ConfirmationReply, classify_confirmation_reply
from .nlu.context import (
    ConversationContext,
    PendingAutomationActionEdit,
    PendingCalendarMutation,
)
from .nlu.ha_automation_generator import generate_ha_action_configs
from .nlu.response_generator import _automation_label

_LOGGER = logging.getLogger(__name__)


def store_automation_action_edit(
    agent: Any, conversation_id: str, pending: PendingAutomationActionEdit
) -> None:
    agent._context_store.set(
        conversation_id,
        ConversationContext(
            last_command=None,
            last_entities=(),
            last_area=None,
            pending_clarification=None,
            pending_automation_action_edit=pending,
        ),
    )


async def async_handle_automation_action_edit_turn(
    agent: Any,
    user_input: conversation.ConversationInput,
    response: intent.IntentResponse,
    pending: PendingAutomationActionEdit,
    entities: list[EntitySnapshot],
) -> conversation.ConversationResult:
    """Resolve automation, replacement action and final consent in stages."""
    reply = classify_confirmation_reply(user_input.text)
    if pending.rendered_actions:
        if reply is ConfirmationReply.NO:
            agent._context_store.clear(user_input.conversation_id)
            response.async_set_speech("Abgebrochen. Die Automation wurde nicht verändert.")
        elif reply is not ConfirmationReply.YES:
            response.async_set_speech("Bitte antworte mit Ja oder Nein.")
        else:
            assert pending.automation is not None and pending.action_text is not None
            if agent._automation_executor is None:
                agent._automation_executor = AutomationExecutor(agent.hass)
            try:
                await agent._automation_executor.async_replace_automation_actions(
                    pending.automation.automation_id,
                    list(pending.rendered_actions),
                    (
                        (pending.automation.source_text or pending.automation.alias)
                        + " | Neue Aktion: "
                        + pending.action_text
                    ),
                )
            except Exception as err:  # noqa: BLE001
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    f"Fehler beim Ändern der Automation: {err}",
                )
            else:
                response.async_set_speech(
                    "Die Aktion wurde geändert. Auslöser und Bedingungen blieben unverändert."
                )
            agent._context_store.clear(user_input.conversation_id)
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    automation = pending.automation
    if automation is None:
        automation = select_candidate_reply(user_input.text, pending.candidates)
        if automation is None:
            response.async_set_speech(
                "Das ist nicht eindeutig. Bitte nenne genau eine dieser Automationen: "
                + ", ".join(_automation_label(item) for item in pending.candidates)
                + "."
            )
        else:
            store_automation_action_edit(
                agent,
                user_input.conversation_id,
                PendingAutomationActionEdit(
                    candidates=pending.candidates, automation=automation
                ),
            )
            response.async_set_speech(
                "Was soll stattdessen passieren? Auslöser und Bedingungen bleiben unverändert."
            )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    actions = agent._engine.parse_automation_actions(
        user_input.text, entities, agent._world_model
    )
    if not actions:
        response.async_set_speech(
            "Die neue Aktion habe ich nicht eindeutig verstanden. Bitte nenne eine vollständige Geräteaktion."
        )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )
    rendered, error = generate_ha_action_configs(actions, entities)
    if error is not None or rendered is None:
        response.async_set_speech("Diese Aktion kann ich nicht sicher in Home Assistant abbilden.")
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )
    store_automation_action_edit(
        agent,
        user_input.conversation_id,
        PendingAutomationActionEdit(
            candidates=pending.candidates,
            automation=automation,
            rendered_actions=tuple(rendered),
            action_text=user_input.text,
        ),
    )
    response.async_set_speech(
        f"Soll ich bei „{_automation_label(automation)}“ nur die Aktion durch "
        f"„{user_input.text.strip()}“ ersetzen?"
    )
    return conversation.ConversationResult(
        response=response, conversation_id=user_input.conversation_id
    )


async def async_handle_calendar_management(
    agent: Any,
    user_input: conversation.ConversationInput,
    response: intent.IntentResponse,
    request: CalendarManagementRequest,
    calendars: tuple[EntitySnapshot, ...],
) -> conversation.ConversationResult:
    """Read events or prepare one capability-checked calendar mutation."""
    if not request.calendar_entity_ids:
        response.async_set_speech("Ich finde keinen für HomeIntent freigegebenen Kalender.")
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    if request.kind in {CalendarManagementKind.LIST, CalendarManagementKind.FIND}:
        try:
            result = await agent.hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "start_date_time": request.start.isoformat(),
                    "end_date_time": request.end.isoformat(),
                },
                target={"entity_id": list(request.calendar_entity_ids)},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Calendar event query failed: %s", err)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                f"Fehler beim Lesen des Kalenders: {err}",
            )
        else:
            response.async_set_speech(
                render_calendar_events(
                    flatten_calendar_response(result, request.title_filter), request
                )
            )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    required = (
        "DELETE_EVENT" if request.kind is CalendarManagementKind.DELETE else "UPDATE_EVENT"
    )
    capable_ids = tuple(
        calendar.entity_id
        for calendar in calendars
        if calendar.entity_id in request.calendar_entity_ids
        and required in calendar.capabilities
    )
    if not capable_ids:
        operation = "Löschen" if required == "DELETE_EVENT" else "Verschieben"
        response.async_set_speech(
            f"Der ausgewählte Kalender unterstützt das {operation} von Terminen über Home Assistant nicht."
        )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )
    if request.kind is CalendarManagementKind.RESCHEDULE and request.new_start_time is None:
        response.async_set_speech("Auf welche Uhrzeit soll ich den Termin verschieben?")
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    try:
        events = await async_get_mutable_calendar_events(
            agent.hass, capable_ids, request.start, request.end
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Calendar event lookup for mutation failed: %s", err)
        response.async_set_error(
            intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
            f"Fehler beim Lesen des Kalenders: {err}",
        )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )
    if request.title_filter:
        wanted = normalize_for_compare(request.title_filter)
        events = tuple(
            event for event in events if wanted in normalize_for_compare(event.summary)
        )
    events = tuple(event for event in events if event.uid is not None)
    if not events:
        response.async_set_speech("Ich finde keinen eindeutig änderbaren passenden Termin.")
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )
    if len(events) > 1:
        names = "; ".join(f"„{event.summary}“ ({event.start})" for event in events[:5])
        response.async_set_speech(
            f"Mehrere Termine passen: {names}. Bitte nenne Titel und Zeitpunkt genauer."
        )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    event = events[0]
    agent._context_store.set(
        user_input.conversation_id,
        ConversationContext(
            last_command=None,
            last_entities=(),
            last_area=None,
            pending_clarification=None,
            pending_calendar_mutation=PendingCalendarMutation(
                kind=request.kind,
                event=event,
                new_start_time=request.new_start_time,
            ),
        ),
    )
    if request.kind is CalendarManagementKind.DELETE:
        preview = f"Soll ich den Termin „{event.summary}“ wirklich löschen?"
    else:
        assert request.new_start_time is not None
        preview = (
            f"Soll ich den Termin „{event.summary}“ auf "
            f"{request.new_start_time.strftime('%H:%M')} Uhr verschieben?"
        )
    response.async_set_speech(preview)
    return conversation.ConversationResult(
        response=response, conversation_id=user_input.conversation_id
    )


async def async_handle_calendar_mutation_confirmation(
    agent: Any,
    user_input: conversation.ConversationInput,
    response: intent.IntentResponse,
    pending: PendingCalendarMutation,
) -> conversation.ConversationResult:
    reply = classify_confirmation_reply(user_input.text)
    if reply is ConfirmationReply.NO:
        agent._context_store.clear(user_input.conversation_id)
        response.async_set_speech("Abgebrochen. Der Termin wurde nicht verändert.")
    elif reply is not ConfirmationReply.YES:
        response.async_set_speech("Bitte antworte mit Ja oder Nein.")
    else:
        agent._context_store.clear(user_input.conversation_id)
        try:
            if pending.kind is CalendarManagementKind.DELETE:
                await async_delete_calendar_event(agent.hass, pending.event)
                response.async_set_speech("Der Termin wurde gelöscht.")
            else:
                assert pending.new_start_time is not None
                await async_reschedule_calendar_event(
                    agent.hass, pending.event, pending.new_start_time
                )
                response.async_set_speech("Der Termin wurde verschoben.")
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Calendar mutation failed: %s", err)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                f"Fehler beim Ändern des Termins: {err}",
            )
    return conversation.ConversationResult(
        response=response, conversation_id=user_input.conversation_id
    )
