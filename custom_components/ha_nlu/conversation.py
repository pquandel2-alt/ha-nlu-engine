"""Conversation platform for the ha_nlu integration.

A deterministic, LLM-free Assist conversation agent: hassil matches the
sentence structure, ``entities.resolve_entity`` resolves the name, and a
match either executes exactly one Home Assistant service call or - on any
kind of mismatch (no template match, ambiguous/unknown name, wrong domain) -
returns a fixed "not understood" response. No fallback, no scoring; see the
project plan ("predictability over coverage") for why.

Deliberately does not use ``chat_log``/``homeassistant.helpers.llm`` at all -
there is no model round-trip here, so the response is built directly as an
``intent.IntentResponse``, the same way HA core's own built-in (hassil-based)
default conversation agent does it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Literal

from homeassistant.components import conversation
from homeassistant.components.conversation import ConversationEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, intent
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .automation_executor import AutomationExecutor
from .automation_action_edit import (
    homeintent_candidates,
    is_action_edit_request,
)
from .automation_management import (
    AutomationManagementKind,
    format_scheduled_time,
    parse_automation_management,
    select_automation_management,
)
from .calendar_event import (
    CalendarEventDraft,
    build_calendar_event_service_call,
    calendar_event_question,
    render_calendar_event_preview,
    start_calendar_event_draft,
    update_calendar_event_draft,
    writable_calendars,
)
from .calendar_management import parse_calendar_management
from .const import DOMAIN, NOT_UNDERSTOOD_TEXT
from .device_control import DeviceControlResult, match_device_control, match_device_control_followup
from .engine import (
    AutomationDraftMatchResult,
    AutomationDeletionMatchResult,
    AutomationMatchResult,
    AutomationToggleMatchResult,
    CommandPlan,
    NluEngine,
    _AUTOMATION_DELETE_RE,
    _AUTOMATION_DISABLE_RE,
    _AUTOMATION_ENABLE_RE,
    _AUTOMATION_QUERY_RE,
)
from .entities import EntitySnapshot
from .hass_entities import build_device_snapshots, build_entity_snapshots
from .management_dialogs import (
    async_handle_automation_action_edit_turn,
    async_handle_calendar_management,
    async_handle_calendar_mutation_confirmation,
    store_automation_action_edit,
)
from .nlu.automation_confirmation import ConfirmationReply, classify_confirmation_reply
from .nlu.automation_model import resolve_pending_schedule
from .nlu.automation_preview import render_automation_preview
from .nlu.context import (
    ConversationContext,
    ConversationContextStore,
    PendingAutomationConfirmation,
    PendingAutomationDeletion,
    PendingAutomationDraft,
    PendingAutomationActionEdit,
    PendingCalendarEvent,
    PendingServiceConfirmation,
)
from .nlu.dialog_focus import DialogFocus, derive_dialog_focus
from .nlu.ha_automation_generator import GenerationError, generate_ha_automation_config
from .nlu.response_generator import _automation_label
from .service_call import QUERY_INTENTS
from .semantic_dialog import continue_semantic_dialog, start_semantic_dialog
from .world_model import WorldModel, build_world_model as assemble_world_model

_LOGGER = logging.getLogger(__name__)

# Single source of truth for "which intents are queries" (V4.2) - read state
# and speak, never call a service - so Assist shows them as a QUERY_ANSWER
# rather than the default ACTION_DONE.
QUERY_INTENT_NAMES = frozenset(QUERY_INTENTS)

# V5 Teil 7/10 (V5.23/V5.26) - the confirmation dialog's own fixed spoken
# replies, same "small closed vocabulary" precedent NOT_UNDERSTOOD_TEXT
# already sets in const.py.
AUTOMATION_CREATED_TEXT = "Automation wurde erstellt."
AUTOMATION_CANCELLED_TEXT = "Abgebrochen. Die Automation wurde nicht erstellt."
AUTOMATION_CONFIRMATION_UNCLEAR_TEXT = (
    "Das habe ich nicht verstanden. Soll die Automation erstellt werden? "
    "Bitte antworte mit Ja oder Nein."
)

# V5 Teil 8/10 (V5.28, "Automation Deletion") - same "small closed
# vocabulary" precedent as the creation texts above, mirrored one-to-one for
# the deletion confirmation dialog.
AUTOMATION_DELETED_TEXT = "Automation wurde gelöscht."
AUTOMATION_DELETION_CANCELLED_TEXT = "Abgebrochen. Die Automation wurde nicht gelöscht."
AUTOMATION_DELETION_CONFIRMATION_UNCLEAR_TEXT = (
    "Das habe ich nicht verstanden. Soll die Automation gelöscht werden? "
    "Bitte antworte mit Ja oder Nein."
)

# HomeIntent V5 Teil 8/10 (Wave 11, "Automation Disable/Enable") - no
# confirmation-round-trip vocabulary here (see ``AutomationToggleMatchResult``'s
# own docstring for why): a single-match toggle executes immediately, so
# only an error text is needed here, mirroring the ordinary command path's
# own ``FAILED_TO_HANDLE`` wording.

# One spoken sentence per GenerationError member (nlu/ha_automation_generator.py) -
# every one of these is a "niemals raten" refusal Regel 4 already established
# one stage earlier (automation_validator.py); a validate_automation()-clean
# model can still hit one of these at confirmation time (e.g. the target
# entity disappeared between preview and "ja", or the model uses a
# TriggerType/ConditionType/ActionType the validator itself never rejects
# but the HA-native schema has no faithful translation for - see that
# module's own docstring for the full "why" per member).
_GENERATION_ERROR_SPOKEN_DE = {
    GenerationError.ENTITY_NOT_FOUND: (
        "Das passende Gerät wurde nicht mehr gefunden. Die Automation wurde nicht erstellt."
    ),
    GenerationError.UNSUPPORTED_STATE: (
        "Dieser Zustand lässt sich für dieses Gerät nicht in eine Automation übersetzen. "
        "Die Automation wurde nicht erstellt."
    ),
    GenerationError.UNSUPPORTED_TRIGGER_TYPE: (
        "Dieser Auslöser wird von Home Assistant nicht unterstützt. Die Automation wurde nicht erstellt."
    ),
    GenerationError.UNSUPPORTED_CONDITION_TYPE: (
        "Diese Bedingung wird von Home Assistant nicht unterstützt. Die Automation wurde nicht erstellt."
    ),
    GenerationError.UNSUPPORTED_ACTION_TYPE: (
        "Diese Aktion wird von Home Assistant nicht unterstützt. Die Automation wurde nicht erstellt."
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the conversation entity for this config entry."""
    async_add_entities([NluConversationEntity(config_entry)])


class NluConversationEntity(
    conversation.ConversationEntity, conversation.AbstractConversationAgent
):
    """Deterministic, rule-based Assist conversation agent (German, v1)."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supports_streaming = False
    _attr_supported_features = ConversationEntityFeature.CONTROL

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="ha-nlu-engine (local, deterministic)",
            model="hassil v1",
            entry_type=dr.DeviceEntryType.SERVICE,
        )
        self._engine = NluEngine()
        self._context_store = ConversationContextStore()
        # Rebuilt every turn in _async_handle_message() (World Model Wave,
        # 2026-08-14); None only until the first turn.
        self._world_model: WorldModel | None = None
        # Lazily constructed on first use in _async_handle_message() (V5.26)
        # rather than here: self.hass isn't set yet at __init__ time (HA's
        # entity platform assigns it before async_added_to_hass() runs, not
        # before __init__()). Built once and kept for this entity's whole
        # lifetime, not per-turn - its asyncio.Lock() must persist across
        # turns to actually guard automations.yaml's read-modify-write cycle
        # against two concurrent confirmations (see AutomationExecutor's own
        # docstring).
        self._automation_executor: AutomationExecutor | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        conversation.async_set_agent(self.hass, self.entry, self)

    async def async_will_remove_from_hass(self) -> None:
        conversation.async_unset_agent(self.hass, self.entry)
        await super().async_will_remove_from_hass()

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        # v1 intent YAMLs are German-only (see intents/de/).
        return ["de"]

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Match the utterance and either act on it or say "not understood".

        A pending clarification (v2 plan Phase 25) for this
        ``conversation_id`` takes priority over a fresh match: the reply is
        resolved against the pending candidates instead of parsed as a new
        sentence (see ``NluEngine.resolve_clarification()``'s docstring for
        why - a reply like "Das im Wohnzimmer" isn't itself a full command).

        Otherwise, an elliptical follow-up without its own target ("Etwas
        heller.", v2 plan Phase 26), a pronoun/relative reference ("Mach es
        aus.", "Die Rollläden dort runter.", v2 plan Phase 27), or a
        cross-sentence query follow-up ("Und in der Küche?", HomeIntent
        plan V4.9) is tried against the stored context before a fresh
        ``match()`` - see ``NluEngine.match_followup()``/
        ``match_reference()``/``match_query_followup()``'s docstrings for
        their scope decisions.
        """
        response = intent.IntentResponse(language=user_input.language)

        # entities stays the exact list every match()/match_followup()/etc.
        # call below already took before the World Model Wave - devices are
        # fetched and bundled alongside it (World Model Wave, 2026-08-14) so
        # a real WorldModel is now built every live turn, not just in tests.
        # Threaded into match() below (WorldModelQuery wave) so query parsers
        # can resolve device-/area-level data - see docs/architecture-v6.md 6d.
        entities = build_entity_snapshots(self.hass, self.entry)
        devices = build_device_snapshots(self.hass, self.entry)
        self._world_model = assemble_world_model(entities, devices)
        pending = self._context_store.get(user_input.conversation_id)

        all_calendars = tuple(entity for entity in entities if entity.domain == "calendar")
        calendars = writable_calendars(entities)
        if pending is not None and pending.pending_calendar_event is not None:
            return await self._async_handle_calendar_event_turn(
                user_input, response, pending.pending_calendar_event, calendars
            )

        if pending is not None and pending.pending_calendar_mutation is not None:
            return await async_handle_calendar_mutation_confirmation(
                self, user_input, response, pending.pending_calendar_mutation
            )

        if pending is not None and pending.pending_automation_confirmation is not None:
            revised = self._engine.revise_pending_automation(
                user_input.text,
                pending.pending_automation_confirmation.model,
                entities,
                self._world_model,
            )
            if revised is not None and revised.validation_error is None:
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None,
                        last_entities=(),
                        last_area=None,
                        pending_clarification=None,
                        pending_automation_confirmation=PendingAutomationConfirmation(
                            model=revised.model
                        ),
                    ),
                )
                response.async_set_speech(render_automation_preview(revised.model, entities))
                return conversation.ConversationResult(
                    response=response, conversation_id=user_input.conversation_id
                )
            return await self._async_handle_automation_confirmation_reply(
                user_input, response, pending.pending_automation_confirmation, entities
            )

        if pending is not None and pending.pending_automation_action_edit is not None:
            return await async_handle_automation_action_edit_turn(
                self,
                user_input,
                response,
                pending.pending_automation_action_edit,
                entities,
            )

        if pending is not None and pending.pending_automation_deletion is not None:
            return await self._async_handle_automation_deletion_confirmation_reply(
                user_input, response, pending.pending_automation_deletion
            )

        if pending is not None and pending.pending_service_confirmation is not None:
            return await self._async_handle_service_confirmation_reply(
                user_input, response, pending.pending_service_confirmation
            )

        if pending is not None and pending.pending_semantic_command is not None:
            dialog = continue_semantic_dialog(
                user_input.text, pending.pending_semantic_command
            )
            if dialog.result is not None:
                self._context_store.clear(user_input.conversation_id)
                return await self._async_handle_device_control_result(
                    user_input, response, dialog.result
                )
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=None,
                    last_entities=(),
                    last_area=None,
                    pending_clarification=None,
                    pending_semantic_command=dialog.pending,
                ),
            )
            response.async_set_speech(dialog.question)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if pending is not None and pending.pending_automation_draft is not None:
            draft = pending.pending_automation_draft
            completed = self._engine.complete_automation_draft(
                user_input.text,
                draft.trigger,
                draft.source_text,
                entities,
                self._world_model,
                pending,
            )
            if completed is None:
                response.async_set_speech(
                    "Was soll dann passieren? Bitte nenne eine vollständige Aktion."
                )
            elif completed.validation_error is not None:
                self._context_store.clear(user_input.conversation_id)
                response.async_set_speech(completed.response_text)
            else:
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None,
                        last_entities=(),
                        last_area=None,
                        pending_clarification=None,
                        pending_automation_confirmation=PendingAutomationConfirmation(
                            model=completed.model
                        ),
                    ),
                )
                response.async_set_speech(render_automation_preview(completed.model, entities))
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        calendar_management = parse_calendar_management(
            user_input.text, all_calendars, dt_util.now()
        )
        if calendar_management is not None:
            return await async_handle_calendar_management(
                self, user_input, response, calendar_management, all_calendars
            )

        calendar_draft = start_calendar_event_draft(
            user_input.text, calendars, dt_util.now()
        )
        if calendar_draft is not None:
            if not calendars:
                self._context_store.clear(user_input.conversation_id)
                response.async_set_speech(
                    "Ich finde keinen für HomeIntent freigegebenen, beschreibbaren Kalender."
                )
                return conversation.ConversationResult(
                    response=response, conversation_id=user_input.conversation_id
                )
            question = calendar_event_question(calendar_draft, calendars)
            awaiting_confirmation = question is None
            self._store_calendar_event(
                user_input.conversation_id, calendar_draft, awaiting_confirmation
            )
            response.async_set_speech(
                render_calendar_event_preview(calendar_draft, calendars)
                if awaiting_confirmation
                else question
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if is_action_edit_request(user_input.text):
            if self._automation_executor is None:
                self._automation_executor = AutomationExecutor(self.hass)
            automations = await self._automation_executor.async_list_automations()
            candidates = homeintent_candidates(automations, user_input.text)
            if not candidates:
                response.async_set_speech("Ich finde keine änderbare HomeIntent-Automation.")
            elif len(candidates) > 1:
                store_automation_action_edit(
                    self,
                    user_input.conversation_id,
                    PendingAutomationActionEdit(candidates=candidates),
                )
                response.async_set_speech(
                    "Welche Automation meinst du? "
                    + ", ".join(_automation_label(item) for item in candidates)
                    + "."
                )
            else:
                store_automation_action_edit(
                    self,
                    user_input.conversation_id,
                    PendingAutomationActionEdit(
                        candidates=candidates, automation=candidates[0]
                    ),
                )
                response.async_set_speech(
                    "Was soll stattdessen passieren? Auslöser und Bedingungen bleiben unverändert."
                )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        management_request = parse_automation_management(user_input.text)
        if management_request is not None:
            return await self._async_handle_automation_management(
                user_input, response, management_request, entities
            )

        device_control = match_device_control(user_input.text, entities)
        if device_control is None:
            device_control = match_device_control_followup(user_input.text, pending)
        if device_control is not None:
            return await self._async_handle_device_control_result(
                user_input, response, device_control
            )

        if pending is not None and pending.pending_clarification is not None:
            # A complete new command supersedes an open clarification.  Try
            # the ordinary grammar first so e.g. "Fahre alle Rollläden im
            # Esszimmer hoch" cannot be mistaken for the short answer to
            # "Welche Rollläden meinst du?".  Elliptical answers such as
            # "die linke" do not match a complete command and therefore
            # continue through the established clarification resolver.
            result = self._engine.match(
                user_input.text, entities, self._world_model
            )
            if result is None:
                result = self._engine.resolve_clarification(
                    user_input.text, pending.pending_clarification, entities
                )
                self._context_store.clear(user_input.conversation_id)
        else:
            result = self._engine.match_correction_followup(
                user_input.text, entities, pending
            )
            if result is None:
                result = self._engine.match_followup(user_input.text, pending)
            if result is None:
                result = self._engine.match_contextual_property_followup(
                    user_input.text, entities, pending
                )
            if result is None:
                result = self._engine.match_reference(user_input.text, entities, pending)
            if result is None:
                result = self._engine.match_query_followup(
                    user_input.text, entities, pending, self._world_model
                )
            if result is None:
                result = self._engine.match_command_followup(user_input.text, entities, pending)
            if result is None and _AUTOMATION_DELETE_RE.search(user_input.text):
                # V5.28 "Automation Deletion": checked before the query gate
                # below - "Lösche die Automation für X" also contains the
                # word "Automation" and would otherwise trigger an
                # unnecessary second automations.yaml read via the query
                # gate first (that grammar just wouldn't match it). Same
                # lazily-constructed, entity-lifetime executor instance the
                # query/creation paths already use.
                if self._automation_executor is None:
                    self._automation_executor = AutomationExecutor(self.hass)
                automations = await self._automation_executor.async_list_automations()
                result = self._engine.match_automation_delete(user_input.text, entities, automations)
            if result is None and _AUTOMATION_DISABLE_RE.search(user_input.text):
                # Wave 11 "Automation Disable/Enable": same "checked before
                # the query gate" reasoning as the delete gate above -
                # "Deaktiviere die Automation für X" also contains the word
                # "Automation".
                if self._automation_executor is None:
                    self._automation_executor = AutomationExecutor(self.hass)
                automations = await self._automation_executor.async_list_automations()
                result = self._engine.match_automation_disable(user_input.text, entities, automations)
            if result is None and _AUTOMATION_ENABLE_RE.search(user_input.text):
                if self._automation_executor is None:
                    self._automation_executor = AutomationExecutor(self.hass)
                automations = await self._automation_executor.async_list_automations()
                result = self._engine.match_automation_enable(user_input.text, entities, automations)
            if result is None and _AUTOMATION_QUERY_RE.search(user_input.text):
                # V5.29 "Automation Query": the same cheap pre-check
                # ``match_automation_query()`` itself re-checks is applied
                # here first too, since it is what decides whether the real,
                # blocking ``automations.yaml``/metadata-sidecar read below
                # happens at all - an ordinary command/query turn must never
                # pay that I/O cost. ``self._automation_executor`` is the
                # same lazily-constructed, entity-lifetime instance
                # ``_async_handle_automation_confirmation_reply`` already
                # uses for automation creation (see below) - one executor,
                # one lock, shared across both read and write paths.
                if self._automation_executor is None:
                    self._automation_executor = AutomationExecutor(self.hass)
                automations = await self._automation_executor.async_list_automations()
                result = self._engine.match_automation_query(
                    user_input.text, entities, pending, automations
                )
            if result is None:
                result = self._engine.match_automation(
                    user_input.text, entities, self._world_model, pending
                )
            if result is None:
                result = self._engine.match_calendar_time_automation(
                    user_input.text, entities, self._world_model, pending
                )
            if result is None:
                result = self._engine.match_automation_draft_start(
                    user_input.text, entities, self._world_model, pending
                )
            if result is None:
                # Wave 13 ("Relative-Zeit-Automationen") - a single-clause
                # command with a relative-time offset ("Fahre in 5 Minuten
                # ..."), tried after the two-clause match_automation() (which
                # can never split this comma-less sentence, see
                # relative_time_command.yaml's own comment) and before the
                # plain match() fallback (which would otherwise route it to
                # TemporalParser, which only parses-and-discards the "in N
                # Minuten" phrase and executes immediately - the original bug
                # this wave fixes). ``dt_util.now()`` (local time, not UTC)
                # is fetched here - the only layer allowed to import
                # homeassistant.util.dt - and passed into the engine so it
                # stays Home-Assistant-import-free.
                result = self._engine.match_relative_time_automation(
                    user_input.text, entities, self._world_model, pending
                )
            if result is None:
                result = self._engine.match(user_input.text, entities, self._world_model)

        if result is None:
            dialog = start_semantic_dialog(user_input.text, entities)
            if dialog is not None and dialog.result is not None:
                return await self._async_handle_device_control_result(
                    user_input, response, dialog.result
                )
            if dialog is not None and dialog.pending is not None:
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None,
                        last_entities=(),
                        last_area=None,
                        pending_clarification=None,
                        pending_semantic_command=dialog.pending,
                    ),
                )
                response.async_set_speech(dialog.question)
                return conversation.ConversationResult(
                    response=response, conversation_id=user_input.conversation_id
                )
            response.async_set_error(
                intent.IntentResponseErrorCode.NO_INTENT_MATCH,
                self._engine.failure_feedback(user_input.text, entities) or NOT_UNDERSTOOD_TEXT,
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if isinstance(result, CommandPlan):
            # V4.8 Multi-Step Commands: every sub-command already validated
            # together before we got here (see CommandPlan's docstring) -
            # only a runtime HA-side failure can still interrupt this, in
            # which case we stop at the first failing sub-command rather
            # than attempt a rollback of already-executed ones (same
            # fail-fast-on-error handling as the single-command path below,
            # just without retroactive undo - HA service calls aren't
            # transactional). Context isn't carried over for a multi-step
            # turn: "last entities" would be ambiguous across several
            # unrelated sub-commands, so follow-ups just start fresh.
            self._context_store.clear(user_input.conversation_id)
            response_parts: list[str] = []
            for sub_result in result.commands:
                if sub_result.plan is None:
                    response_parts.append(sub_result.response_text)
                    continue
                try:
                    await self.hass.services.async_call(
                        sub_result.plan.domain,
                        sub_result.plan.service,
                        {"entity_id": sub_result.plan.entity_id, **sub_result.plan.data},
                        blocking=True,
                    )
                except Exception as err:  # noqa: BLE001 - HA 2025.x service calls can raise beyond HomeAssistantError (vol.Invalid, TimeoutError, ...); must not propagate as "Unexpected error during intent recognition"
                    _LOGGER.error(
                        "Service call %s.%s on %s failed: %s",
                        sub_result.plan.domain,
                        sub_result.plan.service,
                        sub_result.plan.entity_id,
                        err,
                    )
                    response.async_set_error(
                        intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                        f"Fehler beim Ausführen: {err}",
                    )
                    return conversation.ConversationResult(
                        response=response, conversation_id=user_input.conversation_id
                    )
                response_parts.append(sub_result.response_text)
            response.async_set_speech(" ".join(response_parts))
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if isinstance(result, AutomationMatchResult):
            # V5 Teil 7/10 (V5.23, "Dry Run"): a structurally- and
            # semantically-valid AutomationModel is never persisted on this
            # turn - it's spoken back as a preview and held as a
            # PendingAutomationConfirmation awaiting the user's "ja"/"nein"
            # (handled at the top of this method, same priority
            # pending_clarification already has - see PendingAutomationConfirmation's
            # own docstring). Still never a HA service call/write on *this*
            # turn - that only happens once the confirmation reply resolves
            # to YES.
            #
            # A validation_error result can never be confirmed (Integration
            # Wave Migration Step 4's original scope boundary still applies
            # to this branch unchanged): spoken back as the same debug tree
            # + error name as before, no context stored, no follow-up
            # possible - "niemals raten" extends to not offering to persist
            # something already known to be invalid.
            if result.validation_error is None:
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None,
                        last_entities=(),
                        last_area=None,
                        pending_clarification=None,
                        pending_automation_confirmation=PendingAutomationConfirmation(model=result.model),
                    ),
                )
                response.async_set_speech(render_automation_preview(result.model, entities))
            else:
                self._context_store.clear(user_input.conversation_id)
                response.async_set_speech(result.response_text)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if isinstance(result, AutomationDraftMatchResult):
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=None,
                    last_entities=(),
                    last_area=None,
                    pending_clarification=None,
                    pending_automation_draft=PendingAutomationDraft(
                        trigger=result.trigger,
                        source_text=result.source_text,
                    ),
                ),
            )
            response.async_set_speech(result.response_text)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if isinstance(result, AutomationDeletionMatchResult):
            # V5 Teil 8/10 (V5.28, "Automation Deletion"): mirrors the
            # AutomationMatchResult branch above - nothing is ever deleted
            # on this turn. A resolved single match is spoken back as a
            # "ja"/"nein" question and held as a PendingAutomationDeletion
            # (handled at the top of this method); a refusal (no match, or
            # 2+ matches) just speaks result.response_text and stores
            # nothing, same "niemals raten" stance the query path already
            # takes for ambiguous automation names.
            if result.automation is not None:
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None,
                        last_entities=(),
                        last_area=None,
                        pending_clarification=None,
                        pending_automation_deletion=PendingAutomationDeletion(automation=result.automation),
                    ),
                )
            else:
                self._context_store.clear(user_input.conversation_id)
            response.async_set_speech(result.response_text)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if isinstance(result, AutomationToggleMatchResult):
            # Wave 11 "Automation Disable/Enable": unlike the deletion
            # branch above, a resolved single match is acted on immediately
            # on this same turn - no pending state is ever stored (see
            # ``AutomationToggleMatchResult``'s own docstring for why this
            # action needs no ja/nein gate). A refusal (no match, or 2+
            # matches) just speaks ``result.response_text`` with no action,
            # same "niemals raten" stance the delete/query paths already
            # take for ambiguous automation names.
            self._context_store.clear(user_input.conversation_id)
            if result.automation is not None:
                if self._automation_executor is None:
                    self._automation_executor = AutomationExecutor(self.hass)
                try:
                    if result.enable:
                        await self._automation_executor.async_enable_automation(
                            result.automation.automation_id
                        )
                    else:
                        await self._automation_executor.async_disable_automation(
                            result.automation.automation_id
                        )
                except Exception as err:  # noqa: BLE001 - a YAML write + service call can fail in ways beyond HomeAssistantError; must not propagate as "Unexpected error during intent recognition"
                    verb = "Aktivieren" if result.enable else "Deaktivieren"
                    _LOGGER.error("Automation %s failed: %s", verb.lower(), err)
                    response.async_set_error(
                        intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                        f"Fehler beim {verb} der Automation: {err}",
                    )
                    return conversation.ConversationResult(
                        response=response, conversation_id=user_input.conversation_id
                    )
            response.async_set_speech(result.response_text)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if result.clarification is not None:
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=None,
                    last_entities=(),
                    last_area=None,
                    pending_clarification=result.clarification,
                ),
            )
            response.async_set_speech(result.response_text)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if result.command is not None:
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=result.command,
                    last_entities=tuple(result.command.entities),
                    last_area=result.command.area,
                    pending_clarification=None,
                    focus=derive_dialog_focus(result.command),
                ),
            )
        else:
            self._context_store.clear(user_input.conversation_id)

        if result.plan is not None:
            try:
                await self.hass.services.async_call(
                    result.plan.domain,
                    result.plan.service,
                    {"entity_id": result.plan.entity_id, **result.plan.data},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001 - HA 2025.x service calls can raise beyond HomeAssistantError (vol.Invalid, TimeoutError, ...); must not propagate as "Unexpected error during intent recognition"
                _LOGGER.error(
                    "Service call %s.%s on %s failed: %s",
                    result.plan.domain,
                    result.plan.service,
                    result.plan.entity_id,
                    err,
                )
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    f"Fehler beim Ausführen: {err}",
                )
                return conversation.ConversationResult(
                    response=response, conversation_id=user_input.conversation_id
                )

        if result.command is not None and result.command.intent in QUERY_INTENT_NAMES:
            response.response_type = intent.IntentResponseType.QUERY_ANSWER
        response.async_set_speech(result.response_text)
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_handle_automation_confirmation_reply(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        confirmation: PendingAutomationConfirmation,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        """V5 Teil 7/10 (V5.23/V5.25/V5.26): resolves this turn's text
        against the closed yes/no vocabulary (see
        ``nlu/automation_confirmation.py``) instead of parsing it as a fresh
        sentence - a reply like "Ja" isn't itself a command.

        ``UNCLEAR`` keeps the same pending confirmation in place (re-asks,
        never guesses) rather than clearing it - same "caller decides how to
        re-ask" split ``resolve_clarification()``'s own ``None`` case
        already uses. ``NO`` and any generation/persistence failure both
        clear the pending state and persist nothing; only a clean ``YES`` ->
        ``generate_ha_automation_config()`` -> ``AutomationExecutor`` path
        ever reaches Home Assistant.
        """
        reply = classify_confirmation_reply(user_input.text)

        if reply is ConfirmationReply.UNCLEAR:
            response.async_set_speech(AUTOMATION_CONFIRMATION_UNCLEAR_TEXT)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        self._context_store.clear(user_input.conversation_id)

        if reply is ConfirmationReply.NO:
            response.async_set_speech(AUTOMATION_CANCELLED_TEXT)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        try:
            model = resolve_pending_schedule(confirmation.model, dt_util.now())
        except ValueError as err:
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                f"Der Zeitpunkt kann nicht geplant werden: {err}",
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        # Wave 12 ("Einmalige Automation"): a self-deleting automation's own
        # action list needs to reference its own future id (see
        # ha_automation_generator.py's generate_ha_automation_config()
        # docstring for why) - pre-generated here, before persistence, and
        # threaded into both the generator and the executor so they agree.
        # None/unused for every ordinary (non-once) automation.
        once_automation_id = (
            uuid.uuid4().hex if model.once or model.max_runs is not None else None
        )

        generation_result = generate_ha_automation_config(
            model, entities, automation_id=once_automation_id
        )
        if generation_result.error is not None:
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                _GENERATION_ERROR_SPOKEN_DE[generation_result.error],
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        assert generation_result.config is not None

        if self._automation_executor is None:
            self._automation_executor = AutomationExecutor(self.hass)
        try:
            await self._automation_executor.async_create_automation(
                generation_result.config,
                automation_id=once_automation_id,
                scheduled_for=model.scheduled_for,
                once=model.once,
                max_runs=model.max_runs,
            )
        except Exception as err:  # noqa: BLE001 - a YAML write + service call can fail in ways beyond HomeAssistantError; must not propagate as "Unexpected error during intent recognition"
            _LOGGER.error("Automation creation failed: %s", err)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                f"Fehler beim Erstellen der Automation: {err}",
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        response.async_set_speech(AUTOMATION_CREATED_TEXT)
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_handle_device_control_result(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        device_control: DeviceControlResult,
    ) -> conversation.ConversationResult:
        """Apply the common safety, execution and context policy once."""
        if device_control.plan is None:
            self._context_store.clear(user_input.conversation_id)
            response.async_set_speech(device_control.response_text)
        elif device_control.requires_confirmation:
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=None,
                    last_entities=(),
                    last_area=None,
                    pending_clarification=None,
                    pending_service_confirmation=PendingServiceConfirmation(
                        device_control.plan, device_control.response_text
                    ),
                ),
            )
            response.async_set_speech(
                f"Soll ich wirklich {device_control.response_text.rstrip('.')}?"
            )
        else:
            try:
                await self.hass.services.async_call(
                    device_control.plan.domain,
                    device_control.plan.service,
                    {
                        "entity_id": device_control.plan.entity_id,
                        **device_control.plan.data,
                    },
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001 - HA services raise heterogeneous errors
                self._context_store.clear(user_input.conversation_id)
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    f"Fehler beim Ausführen: {err}",
                )
            else:
                response.async_set_speech(device_control.response_text)
                if device_control.entity is not None:
                    controlled = device_control.entity
                    self._context_store.set(
                        user_input.conversation_id,
                        ConversationContext(
                            last_command=None,
                            last_entities=(controlled,),
                            last_area=None,
                            pending_clarification=None,
                            focus=DialogFocus(
                                property=None,
                                scope_kind="entity",
                                scope_id=controlled.entity_id,
                                candidate_entity_ids=(controlled.entity_id,),
                                source_intent="DeviceControl:" + device_control.plan.service,
                            ),
                        ),
                    )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    def _store_calendar_event(
        self,
        conversation_id: str,
        draft: CalendarEventDraft,
        awaiting_confirmation: bool,
    ) -> None:
        self._context_store.set(
            conversation_id,
            ConversationContext(
                last_command=None,
                last_entities=(),
                last_area=None,
                pending_clarification=None,
                pending_calendar_event=PendingCalendarEvent(
                    draft=draft, awaiting_confirmation=awaiting_confirmation
                ),
            ),
        )

    async def _async_handle_calendar_event_turn(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        pending: PendingCalendarEvent,
        calendars: tuple[EntitySnapshot, ...],
    ) -> conversation.ConversationResult:
        """Complete, revise, confirm, and finally create one calendar event."""
        reply = classify_confirmation_reply(user_input.text)
        if reply is ConfirmationReply.NO:
            self._context_store.clear(user_input.conversation_id)
            response.async_set_speech("Abgebrochen. Der Termin wurde nicht eingetragen.")
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if not pending.awaiting_confirmation and reply is ConfirmationReply.YES:
            response.async_set_speech(
                calendar_event_question(pending.draft, calendars)
                or "Bitte ergänze die noch fehlende Terminangabe."
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if pending.awaiting_confirmation and reply is ConfirmationReply.YES:
            try:
                call = build_calendar_event_service_call(
                    pending.draft, calendars, dt_util.now()
                )
            except ValueError as err:
                response.async_set_speech(
                    f"Der Termin kann so nicht eingetragen werden: {err}. Bitte korrigiere die Angabe."
                )
                return conversation.ConversationResult(
                    response=response, conversation_id=user_input.conversation_id
                )

            self._context_store.clear(user_input.conversation_id)
            try:
                await self.hass.services.async_call(
                    "calendar",
                    "create_event",
                    call.data,
                    target={"entity_id": call.entity_id},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001 - HA calendar integrations raise heterogeneous errors
                _LOGGER.error("Calendar event creation failed: %s", err)
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    f"Fehler beim Eintragen des Termins: {err}",
                )
            else:
                response.async_set_speech("Der Termin wurde eingetragen.")
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        update = update_calendar_event_draft(
            user_input.text, pending.draft, calendars, dt_util.now()
        )
        if update.error_text is not None:
            response.async_set_speech(update.error_text)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        if pending.awaiting_confirmation and not update.changed:
            response.async_set_speech(
                "Bitte antworte mit Ja oder Nein. Du kannst Datum, Uhrzeit, Dauer, Titel oder Kalender auch noch korrigieren."
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        question = calendar_event_question(update.draft, calendars)
        awaiting_confirmation = question is None
        self._store_calendar_event(
            user_input.conversation_id, update.draft, awaiting_confirmation
        )
        response.async_set_speech(
            render_calendar_event_preview(update.draft, calendars)
            if awaiting_confirmation
            else question
        )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_handle_automation_management(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        request,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        """Execute the bounded query/reschedule/cleanup management language."""
        self._context_store.clear(user_input.conversation_id)
        if self._automation_executor is None:
            self._automation_executor = AutomationExecutor(self.hass)
        now = dt_util.now()
        if request.kind is AutomationManagementKind.CLEAN_EXPIRED:
            try:
                removed = await self._automation_executor.async_cleanup_expired_scheduled_automations(
                    now
                )
            except Exception as err:  # noqa: BLE001 - persistence failures are heterogeneous
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    f"Fehler beim Bereinigen der Aufträge: {err}",
                )
            else:
                response.async_set_speech(
                    "Es waren keine abgelaufenen HomeIntent-Aufträge vorhanden."
                    if not removed
                    else f"{len(removed)} abgelaufene HomeIntent-Aufträge wurden gelöscht."
                )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        automations = await self._automation_executor.async_list_automations()
        selection = select_automation_management(request, entities, automations, now)
        if selection.error_text is not None:
            response.async_set_speech(selection.error_text)
        elif request.kind is AutomationManagementKind.LIST_HOMEINTENT:
            labels = [_automation_label(item) for item in selection.automations]
            response.async_set_speech(
                "Es sind keine HomeIntent-Automationen vorhanden."
                if not labels
                else "HomeIntent-Automationen: " + ", ".join(labels) + "."
            )
        elif request.kind in {
            AutomationManagementKind.COUNT_ACTIVE,
            AutomationManagementKind.COUNT_DISABLED,
        }:
            state = (
                "aktiv"
                if request.kind is AutomationManagementKind.COUNT_ACTIVE
                else "deaktiviert"
            )
            response.async_set_speech(
                f"{len(selection.automations)} HomeIntent-Automationen sind {state}."
            )
        elif request.kind in {
            AutomationManagementKind.EXPLAIN_TRIGGER,
            AutomationManagementKind.CONTROLS_ENTITY,
        }:
            if not selection.automations:
                response.async_set_speech("Ich finde keine passende HomeIntent-Automation.")
            else:
                details = [
                    item.source_text or item.alias for item in selection.automations
                ]
                prefix = (
                    "Auf diesen Auslöser reagieren: "
                    if request.kind is AutomationManagementKind.EXPLAIN_TRIGGER
                    else "Dieses Gerät wird gesteuert durch: "
                )
                response.async_set_speech(prefix + "; ".join(details) + ".")
        elif request.kind in (
            AutomationManagementKind.LIST_SCHEDULED,
            AutomationManagementKind.WHEN,
        ):
            if not selection.automations:
                response.async_set_speech("Es sind keine passenden einmaligen Aufträge geplant.")
            else:
                details = [
                    f"{_automation_label(item)} – {format_scheduled_time(item.scheduled_for)}"
                    for item in selection.automations
                    if item.scheduled_for is not None
                ]
                response.async_set_speech("Geplant sind: " + "; ".join(details) + ".")
        elif request.kind is AutomationManagementKind.RESCHEDULE:
            if not selection.automations:
                response.async_set_speech("Ich habe keinen passenden geplanten Auftrag gefunden.")
            elif len(selection.automations) > 1:
                labels = ", ".join(_automation_label(item) for item in selection.automations)
                response.async_set_speech(
                    "Mehrere Aufträge passen. Bitte nenne das Gerät im Verschiebebefehl: "
                    + labels
                    + "."
                )
            else:
                automation = selection.automations[0]
                target = datetime.fromisoformat(automation.scheduled_for)
                target = target.replace(hour=request.hour, minute=request.minute, second=0)
                comparable_now = now
                if target.tzinfo is None and now.tzinfo is not None:
                    comparable_now = now.replace(tzinfo=None)
                elif target.tzinfo is not None and now.tzinfo is None:
                    comparable_now = now.replace(tzinfo=target.tzinfo)
                if target <= comparable_now:
                    response.async_set_speech(
                        "Die neue Uhrzeit liegt am geplanten Tag bereits in der Vergangenheit."
                    )
                else:
                    try:
                        await self._automation_executor.async_reschedule_automation(
                            automation.automation_id, target
                        )
                    except Exception as err:  # noqa: BLE001 - persistence failures are heterogeneous
                        response.async_set_error(
                            intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                            f"Fehler beim Verschieben des Auftrags: {err}",
                        )
                    else:
                        response.async_set_speech(
                            "Der Auftrag wurde auf "
                            + format_scheduled_time(target.isoformat())
                            + " verschoben."
                        )
        elif request.kind is AutomationManagementKind.SET_MAX_RUNS:
            if not selection.automations:
                response.async_set_speech(
                    "Ich habe keine passende dauerhafte HomeIntent-Automation gefunden."
                )
            elif len(selection.automations) > 1:
                labels = ", ".join(
                    _automation_label(item) for item in selection.automations
                )
                response.async_set_speech(
                    "Mehrere Automationen passen. Bitte nenne das Gerät: "
                    + labels
                    + "."
                )
            else:
                automation = selection.automations[0]
                try:
                    await self._automation_executor.async_set_max_runs(
                        automation.automation_id, request.max_runs
                    )
                except Exception as err:  # noqa: BLE001 - persistence failures are heterogeneous
                    response.async_set_error(
                        intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                        f"Fehler beim Begrenzen der Automation: {err}",
                    )
                else:
                    response.async_set_speech(
                        f"{_automation_label(automation)} wird nur noch "
                        f"{request.max_runs} Mal ausgeführt."
                    )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_handle_service_confirmation_reply(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        confirmation: PendingServiceConfirmation,
    ) -> conversation.ConversationResult:
        """Confirm a high-risk lock or garage movement before execution."""
        reply = classify_confirmation_reply(user_input.text)
        if reply is ConfirmationReply.UNCLEAR:
            response.async_set_speech("Bitte antworte mit Ja oder Nein.")
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        self._context_store.clear(user_input.conversation_id)
        if reply is ConfirmationReply.NO:
            response.async_set_speech("Abgebrochen. Es wurde nichts ausgeführt.")
        else:
            try:
                await self.hass.services.async_call(
                    confirmation.plan.domain,
                    confirmation.plan.service,
                    {
                        "entity_id": confirmation.plan.entity_id,
                        **confirmation.plan.data,
                    },
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001 - HA service failures are heterogeneous
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    f"Fehler beim Ausführen: {err}",
                )
            else:
                response.async_set_speech(confirmation.success_text)
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_handle_automation_deletion_confirmation_reply(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        deletion: PendingAutomationDeletion,
    ) -> conversation.ConversationResult:
        """V5 Teil 8/10 (V5.28, "Automation Deletion"): the deletion
        counterpart to ``_async_handle_automation_confirmation_reply()``
        above - same closed yes/no vocabulary, same ``UNCLEAR``-keeps-
        pending/``NO``-and-failure-clear-and-persist-nothing shape. No
        ``entities`` parameter is needed here (unlike the creation reply):
        deletion doesn't regenerate anything against live HA state, it just
        removes the already-resolved ``deletion.automation`` by id.
        """
        reply = classify_confirmation_reply(user_input.text)

        if reply is ConfirmationReply.UNCLEAR:
            response.async_set_speech(AUTOMATION_DELETION_CONFIRMATION_UNCLEAR_TEXT)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        self._context_store.clear(user_input.conversation_id)

        if reply is ConfirmationReply.NO:
            response.async_set_speech(AUTOMATION_DELETION_CANCELLED_TEXT)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if self._automation_executor is None:
            self._automation_executor = AutomationExecutor(self.hass)
        try:
            await self._automation_executor.async_delete_automation(
                deletion.automation.automation_id
            )
        except Exception as err:  # noqa: BLE001 - a YAML write + service call can fail in ways beyond HomeAssistantError; must not propagate as "Unexpected error during intent recognition"
            _LOGGER.error("Automation deletion failed: %s", err)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                f"Fehler beim Löschen der Automation: {err}",
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        response.async_set_speech(AUTOMATION_DELETED_TEXT)
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )
