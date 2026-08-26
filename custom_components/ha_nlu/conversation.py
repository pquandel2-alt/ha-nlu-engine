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
import re
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
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
    action_edit_operation,
    homeintent_candidates,
    is_action_edit_request,
    reordered_actions,
    select_candidate_reply,
)
from .automation_management import (
    AutomationManagementKind,
    format_scheduled_time,
    parse_automation_management,
    select_automation_management,
)
from .automation_structure_edit import (
    AutomationEditOperation,
    AutomationStructureEditRequest,
    parse_automation_structure_edit,
)
from .automation_wizard import (
    AutomationWizardStage,
    AutomationWizardState,
    parse_lifetime,
    starts_automation_wizard,
)
from .advanced_queries import match_advanced_query
from .audit_log import render_today
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
from .capability_audit import match_capability_audit_query
from .conversation_location import (
    materialize_local_reference,
    resolve_conversation_area,
)
from .const import (
    CONF_ALLOW_NON_ADMIN_AUTOMATIONS,
    DOMAIN,
    NOT_UNDERSTOOD_TEXT,
)
from .device_control import DeviceControlResult, match_device_control, match_device_control_followup
from .engine import (
    AutomationDraftMatchResult,
    AutomationDeletionMatchResult,
    AutomationMatchResult,
    AutomationToggleMatchResult,
    CommandPlan,
    MatchResult,
    _AUTOMATION_DELETE_RE,
    _AUTOMATION_DISABLE_RE,
    _AUTOMATION_ENABLE_RE,
    _AUTOMATION_QUERY_RE,
)
from .entities import EntitySnapshot, normalize_for_compare
from .hass_entities import build_device_snapshots, build_entity_snapshots
from .history_query import (
    ComparativeHistoryQuery,
    HistoryQuery,
    StateHistoryQuery,
    async_execute_history_query,
    parse_history_query,
)
from .household_query import match_household_query
from .management_dialogs import (
    async_handle_automation_action_edit_turn,
    async_handle_automation_structure_edit_turn,
    async_prepare_automation_structure_edit,
    async_handle_calendar_management,
    async_handle_calendar_mutation_confirmation,
    store_automation_action_edit,
    store_automation_structure_edit,
)
from .nlu.automation_confirmation import ConfirmationReply, classify_confirmation_reply
from .nlu.automation_model import AutomationModel, TriggerTarget, resolve_pending_schedule
from .nlu.automation_validator import validate_automation
from .nlu.automation_preview import render_automation_preview
from .nlu.context import (
    ConversationContext,
    DialogTurnMemory,
    PendingAutomationConfirmation,
    PendingAutomationDeletion,
    PendingAutomationDraft,
    PendingAutomationActionEdit,
    PendingAutomationManagement,
    PendingAutomationStructureEdit,
    PendingAutomationWizard,
    PendingCalendarEvent,
    PendingServiceConfirmation,
    PendingSemanticCommand,
    PendingProductivityCommand,
)
from .nlu.dialog_focus import DialogFocus, derive_dialog_focus
from .nlu.explanation import explain_command, is_explanation_request
from .nlu.ha_automation_generator import (
    GenerationError,
    generate_ha_automation_config,
    resolve_automation_action_entity_ids,
)
from .nlu.response_generator import _automation_label
from .nlu.semantic_utterance import SpeechAct, analyse_utterance
from .service_call import QUERY_INTENTS, ServiceCallPlan
from .semantic_dialog import continue_semantic_dialog, start_semantic_dialog
from .reminder import (
    reminder_automation_text,
    reminder_quiet_hours,
    reminder_recipient,
)
from .security_control import (
    conversation_user_id,
    match_alarm_control,
    user_display_name,
    user_is_admin,
)
from .extended_device_query import match_extended_device_query
from .execution_policy import (
    PolicyOutcome,
    evaluate_service_plan,
    validate_automation_action_targets,
)
from .world_model import WorldModel, build_world_model as assemble_world_model
from .undo import UndoPlan, build_undo_plan, is_undo_request
from .runtime_data import HaNluRuntimeData
from .productivity import (
    ProductivityRequest,
    TimerOperation,
    TimerRequest,
    TodoOperation,
    TodoRequest,
    format_duration,
    parse_productivity_request,
    select_productivity_candidate,
)
from .phonetic_correction import phonetic_suggestions

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
        runtime = getattr(entry, "runtime_data", None)
        if not isinstance(runtime, HaNluRuntimeData):
            # Direct unit construction and upgrades from an older entry do
            # not necessarily pass through integration setup first.
            runtime = HaNluRuntimeData()
            try:
                entry.runtime_data = runtime
            except AttributeError:
                pass
        self._engine = runtime.engine
        self._context_store = runtime.context_store
        self._audit_trail = runtime.audit_trail
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
        conversation_area = resolve_conversation_area(self.hass, user_input)
        localized_text = materialize_local_reference(
            user_input.text, conversation_area
        )
        if localized_text != user_input.text:
            user_input = replace(user_input, text=localized_text)
        if conversation_area is not None and (
            pending is None or pending.last_area is None
        ):
            pending = (
                replace(pending, last_area=conversation_area)
                if pending is not None
                else ConversationContext(
                    last_command=None,
                    last_entities=(),
                    last_area=conversation_area,
                    pending_clarification=None,
                )
            )

        if is_undo_request(user_input.text):
            return await self._async_handle_undo_request(
                user_input, response, pending, entities
            )

        if is_explanation_request(user_input.text):
            return self._handle_explanation_request(
                user_input, response, pending, entities
            )

        all_calendars = tuple(entity for entity in entities if entity.domain == "calendar")
        calendars = writable_calendars(entities)
        if pending is not None and pending.pending_automation_wizard is not None:
            return await self._async_handle_automation_wizard(
                user_input,
                response,
                pending.pending_automation_wizard.state,
                entities,
            )
        if pending is not None and pending.pending_productivity_command is not None:
            return await self._async_handle_pending_productivity(
                user_input,
                response,
                pending.pending_productivity_command,
                entities,
            )
        if pending is not None and pending.pending_calendar_event is not None:
            return await self._async_handle_calendar_event_turn(
                user_input, response, pending.pending_calendar_event, calendars
            )

        if pending is not None and pending.pending_calendar_mutation is not None:
            return await async_handle_calendar_mutation_confirmation(
                self, user_input, response, pending.pending_calendar_mutation
            )

        if pending is not None and pending.pending_automation_confirmation is not None:
            return await self._async_handle_pending_automation_confirmation_turn(
                user_input,
                response,
                pending.pending_automation_confirmation,
                entities,
            )

        if pending is not None and pending.pending_automation_action_edit is not None:
            return await async_handle_automation_action_edit_turn(
                self,
                user_input,
                response,
                pending.pending_automation_action_edit,
                entities,
            )

        if pending is not None and pending.pending_automation_structure_edit is not None:
            return await async_handle_automation_structure_edit_turn(
                self,
                user_input,
                response,
                pending.pending_automation_structure_edit,
                entities,
            )

        if pending is not None and pending.pending_automation_management is not None:
            return await self._async_handle_automation_management_confirmation(
                user_input, response, pending.pending_automation_management
            )

        if pending is not None and pending.pending_automation_deletion is not None:
            return await self._async_handle_automation_deletion_confirmation_reply(
                user_input, response, pending.pending_automation_deletion
            )

        if pending is not None and pending.pending_service_confirmation is not None:
            return await self._async_handle_service_confirmation_reply(
                user_input,
                response,
                pending.pending_service_confirmation,
                entities,
            )

        if pending is not None and pending.pending_semantic_command is not None:
            return await self._async_handle_pending_semantic_command(
                user_input, response, pending.pending_semantic_command
            )

        if pending is not None and pending.pending_automation_draft is not None:
            return await self._async_handle_pending_automation_draft(
                user_input, response, pending, entities
            )

        if starts_automation_wizard(user_input.text):
            return self._start_automation_wizard(user_input, response)

        if re.search(
            r"\bwas\s+wurde\s+heute\s+(?:durch|von)\s+homeintent\s+ausgefuehrt\b",
            normalize_for_compare(user_input.text),
        ):
            return self._handle_audit_query(user_input, response)

        history_query = parse_history_query(user_input.text, entities, dt_util.now())
        if history_query is not None:
            return await self._async_handle_history_query_result(
                user_input, response, history_query
            )

        advanced_answer = match_advanced_query(user_input.text, entities, dt_util.now())
        if advanced_answer is not None:
            return self._handle_advanced_answer(user_input, response, advanced_answer)

        if re.search(
            r"\b(?:alarm|alarmanlage|sicherung|scharf|unscharf)\b",
            user_input.text, re.IGNORECASE,
        ):
            alarm = match_alarm_control(
                user_input.text, entities,
                allow_disarm=await user_is_admin(self.hass, user_input),
            )
            if alarm is not None:
                return await self._async_handle_device_control_result(
                    user_input, response, alarm
                )

        productivity_entities = entities
        if re.search(r"\bmein(?:e|er|en|em)?\b", user_input.text, re.IGNORECASE):
            owner = await user_display_name(self.hass, user_input)
            if owner:
                owner_key = normalize_for_compare(owner)
                personal_todos = {
                    entity.entity_id for entity in entities
                    if entity.domain == "todo" and owner_key in normalize_for_compare(entity.friendly_name)
                }
                if personal_todos:
                    productivity_entities = [
                        entity for entity in entities
                        if entity.domain != "todo" or entity.entity_id in personal_todos
                    ]
        productivity = parse_productivity_request(
            user_input.text, productivity_entities, dt_util.now()
        )
        if productivity is not None:
            return await self._async_handle_productivity_request(
                user_input, response, productivity, entities
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
            return self._handle_calendar_draft(
                user_input, response, calendar_draft, calendars
            )

        structure_edit = (
            None
            if is_action_edit_request(user_input.text)
            else parse_automation_structure_edit(user_input.text)
        )
        if structure_edit is not None:
            return await self._async_handle_structure_edit_request(
                user_input, response, structure_edit, entities
            )

        if is_action_edit_request(user_input.text):
            return await self._async_handle_action_edit_request(
                user_input, response
            )

        management_request = parse_automation_management(user_input.text)
        if management_request is not None:
            return await self._async_handle_automation_management(
                user_input, response, management_request, entities
            )

        device_control = match_capability_audit_query(user_input.text, entities)
        if device_control is None:
            device_control = match_household_query(
                user_input.text, entities, dt_util.now()
            )
        if device_control is None:
            device_control = match_extended_device_query(user_input.text, entities)
        if device_control is None:
            device_control = match_device_control(user_input.text, entities)
        if device_control is None:
            device_control = match_device_control_followup(
                user_input.text, pending, entities
            )
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
                result = self._engine.match_repeated_event_automation(
                    user_input.text, entities, self._world_model, pending
                )
            if result is None:
                result = self._engine.match_persistent_state_automation(
                    user_input.text, entities, self._world_model, pending
                )
            if result is None:
                result = self._engine.match_recurring_time_automation(
                    user_input.text, entities, dt_util.now(), self._world_model, pending
                )
            if result is None:
                result = self._engine.match_automation(
                    user_input.text, entities, self._world_model, pending
                )
            if result is None:
                result = self._engine.match_calendar_event_automation(
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
                reminder_text = reminder_automation_text(user_input.text)
                if reminder_text is not None:
                    result = self._engine.match_calendar_time_automation(
                        reminder_text, entities, self._world_model, pending
                    )
                    if result is None:
                        result = self._engine.match_relative_time_automation(
                            reminder_text, entities, self._world_model, pending
                        )
                    if isinstance(result, AutomationMatchResult):
                        recipient = reminder_recipient(user_input.text)
                        quiet_hours = reminder_quiet_hours(user_input.text)
                        actions = result.model.actions
                        if recipient is not None:
                            recipient_key = normalize_for_compare(recipient)
                            targets = [
                                entity for entity in entities
                                if entity.domain == "notify" and any(
                                    recipient_key in normalize_for_compare(name)
                                    for name in (entity.friendly_name, *entity.aliases)
                                )
                            ]
                            if len(targets) != 1:
                                response.async_set_speech(
                                    f"Ich finde kein eindeutig ausgewähltes Benachrichtigungsziel für {recipient}."
                                )
                                return conversation.ConversationResult(
                                    response=response,
                                    conversation_id=user_input.conversation_id,
                                )
                            updated_actions = list(actions)
                            updated_actions[0] = replace(
                                updated_actions[0],
                                target=TriggerTarget(
                                    domain="notify", entity_id=targets[0].entity_id
                                ),
                            )
                            actions = tuple(updated_actions)
                        result = replace(
                            result,
                            model=replace(
                                result.model,
                                source_text=user_input.text,
                                actions=actions,
                                quiet_start_hour=(quiet_hours[0] if quiet_hours else None),
                                quiet_end_hour=(quiet_hours[1] if quiet_hours else None),
                            ),
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
            return await self._async_handle_no_match(user_input, response, entities)

        if isinstance(result, CommandPlan):
            return await self._async_handle_command_plan(
                user_input, response, result, entities
            )

        if isinstance(result, AutomationMatchResult):
            return self._handle_automation_match_result(
                user_input, response, result, entities
            )

        if isinstance(result, AutomationDraftMatchResult):
            return self._handle_automation_draft_match_result(
                user_input, response, result
            )

        if isinstance(result, AutomationDeletionMatchResult):
            return self._handle_automation_deletion_match_result(
                user_input, response, result
            )

        if isinstance(result, AutomationToggleMatchResult):
            return await self._async_handle_automation_toggle_result(
                user_input, response, result
            )

        if result.clarification is not None:
            return self._handle_clarification_result(user_input, response, result)

        return await self._async_handle_match_result(
            user_input, response, result, entities
        )

    async def _async_handle_undo_request(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        pending: ConversationContext | None,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        """Undo the most recent safely reversible action for this user."""
        undo = pending.pending_undo if pending is not None else None
        current_user_id = conversation_user_id(user_input)
        if undo is None:
            response.async_set_speech(
                "Es gibt keine kürzlich ausgeführte, sicher rückgängig machbare Aktion."
            )
        elif (
            undo.requested_by_user_id is not None
            and undo.requested_by_user_id != current_user_id
        ):
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                "Diese Rücknahme gehört zu einem anderen Benutzer.",
            )
        else:
            is_admin = await user_is_admin(self.hass, user_input)
            denial = next(
                (
                    decision.reason
                    for plan in undo.plans
                    if (
                        decision := evaluate_service_plan(
                            plan,
                            entities,
                            self.entry.options,
                            is_admin=is_admin,
                            user_id=current_user_id,
                        )
                    ).outcome
                    is PolicyOutcome.DENY
                ),
                None,
            )
            if denial is not None:
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    denial,
                )
                return conversation.ConversationResult(
                    response=response,
                    conversation_id=user_input.conversation_id,
                )
            self._context_store.clear(user_input.conversation_id)
            try:
                for plan in undo.plans:
                    await self.hass.services.async_call(
                        plan.domain,
                        plan.service,
                        {"entity_id": plan.entity_id, **plan.data},
                        blocking=True,
                    )
                    self._record_execution(user_input, plan)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Undo service call failed: %s", err, exc_info=True)
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    f"Fehler beim Rückgängigmachen: {err}",
                )
            else:
                response.async_set_speech("Die letzte Aktion wurde rückgängig gemacht.")
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    def _handle_explanation_request(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        pending: ConversationContext | None,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        """Explain the pending automation or the last understood command."""
        if pending is not None and pending.pending_automation_confirmation is not None:
            speech = (
                "Ich habe folgende Automation verstanden:\n"
                + render_automation_preview(
                    pending.pending_automation_confirmation.model, entities
                )
            )
        elif pending is not None and pending.last_command is not None:
            speech = explain_command(pending.last_command)
        elif pending is not None and (
            pending.memory is not None and pending.memory.explanation is not None
            or pending.last_explanation is not None
        ):
            speech = (
                pending.memory.explanation
                if pending.memory is not None and pending.memory.explanation is not None
                else pending.last_explanation
            )
        else:
            speech = "In diesem Gespräch gibt es noch keinen verstandenen Befehl."
        response.async_set_speech(speech)
        response.response_type = intent.IntentResponseType.QUERY_ANSWER
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    def _start_automation_wizard(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
    ) -> conversation.ConversationResult:
        """Start the bounded automation wizard."""
        state = AutomationWizardState()
        self._store_automation_wizard(user_input.conversation_id, state)
        response.async_set_speech(
            "Was soll die Automation auslösen? Bitte nenne einen vollständigen Auslöser."
        )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    def _handle_audit_query(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
    ) -> conversation.ConversationResult:
        """Render today's bounded HomeIntent execution audit."""
        response.async_set_speech(render_today(self._audit_trail.today(dt_util.now())))
        response.response_type = intent.IntentResponseType.QUERY_ANSWER
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_handle_history_query_result(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        history_query: HistoryQuery | StateHistoryQuery | ComparativeHistoryQuery,
    ) -> conversation.ConversationResult:
        """Execute a read-only recorder query and render its answer."""
        self._context_store.clear(user_input.conversation_id)
        response.async_set_speech(
            await async_execute_history_query(self.hass, history_query)
        )
        response.response_type = intent.IntentResponseType.QUERY_ANSWER
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    def _handle_advanced_answer(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        answer: str,
    ) -> conversation.ConversationResult:
        """Return an already composed advanced-query answer."""
        self._context_store.clear(user_input.conversation_id)
        response.async_set_speech(answer)
        response.response_type = intent.IntentResponseType.QUERY_ANSWER
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    def _handle_calendar_draft(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        draft: CalendarEventDraft,
        calendars: tuple[EntitySnapshot, ...],
    ) -> conversation.ConversationResult:
        """Store a calendar draft and ask for its next missing value."""
        if not calendars:
            self._context_store.clear(user_input.conversation_id)
            response.async_set_speech(
                "Ich finde keinen für HomeIntent freigegebenen, beschreibbaren Kalender."
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        question = calendar_event_question(draft, calendars)
        awaiting_confirmation = question is None
        self._store_calendar_event(
            user_input.conversation_id, draft, awaiting_confirmation
        )
        response.async_set_speech(
            render_calendar_event_preview(draft, calendars)
            if awaiting_confirmation
            else question
        )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_handle_structure_edit_request(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        request: AutomationStructureEditRequest,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        """Resolve and prepare a trigger or condition edit."""
        if self._automation_executor is None:
            self._automation_executor = AutomationExecutor(self.hass)
        automations = await self._automation_executor.async_list_automations()
        candidates = tuple(
            item
            for item in homeintent_candidates(automations, user_input.text)
            if not item.once
        )
        if not candidates:
            response.async_set_speech(
                "Ich finde keine passende dauerhafte HomeIntent-Automation. "
                "Einmalige Aufträge werden aus Sicherheitsgründen nicht strukturell geändert."
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        pending_edit = PendingAutomationStructureEdit(
            request=request,
            candidates=candidates,
            automation=candidates[0] if len(candidates) == 1 else None,
        )
        if len(candidates) > 1:
            store_automation_structure_edit(
                self, user_input.conversation_id, pending_edit
            )
            response.async_set_speech(
                "Welche Automation meinst du? "
                + ", ".join(_automation_label(item) for item in candidates)
                + "."
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        if request.payload or request.operation in {
            AutomationEditOperation.CLEAR,
            AutomationEditOperation.REMOVE,
        }:
            return await async_prepare_automation_structure_edit(
                self,
                user_input,
                response,
                pending_edit,
                entities,
                request.payload,
            )
        store_automation_structure_edit(self, user_input.conversation_id, pending_edit)
        response.async_set_speech(
            "Wie soll der neue Auslöser lauten?"
            if request.section.name == "TRIGGERS"
            else "Welche Bedingung soll gelten?"
        )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_handle_action_edit_request(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
    ) -> conversation.ConversationResult:
        """Resolve an automation and begin its action-only edit dialog."""
        if self._automation_executor is None:
            self._automation_executor = AutomationExecutor(self.hass)
        automations = await self._automation_executor.async_list_automations()
        candidates = homeintent_candidates(automations, user_input.text)
        operation = action_edit_operation(user_input.text)
        if not candidates:
            response.async_set_speech("Ich finde keine änderbare HomeIntent-Automation.")
        elif len(candidates) > 1:
            store_automation_action_edit(
                self,
                user_input.conversation_id,
                PendingAutomationActionEdit(
                    candidates=candidates, operation=operation
                ),
            )
            response.async_set_speech(
                "Welche Automation meinst du? "
                + ", ".join(_automation_label(item) for item in candidates)
                + "."
            )
        else:
            reordered = reordered_actions(candidates[0].actions, operation)
            if operation.startswith("reorder:") and reordered is None:
                response.async_set_speech(
                    "Diese Automation hat nicht genügend Aktionen für diese Reihenfolge."
                )
            else:
                store_automation_action_edit(
                    self,
                    user_input.conversation_id,
                    PendingAutomationActionEdit(
                        candidates=candidates,
                        automation=candidates[0],
                        rendered_actions=reordered or (),
                        action_text=user_input.text if reordered else None,
                        operation=operation,
                    ),
                )
                response.async_set_speech(
                    "Soll ich die Reihenfolge der Aktionen wie gewünscht ändern?"
                    if reordered
                    else "Welche Aktion soll zusätzlich danach ausgeführt werden?"
                    if operation == "add"
                    else "Was soll stattdessen passieren? Auslöser und Bedingungen bleiben unverändert."
                )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_handle_pending_automation_confirmation_turn(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        pending: PendingAutomationConfirmation,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        """Revise a pending automation or interpret its confirmation reply."""
        revised = self._engine.revise_pending_automation(
            user_input.text,
            pending.model,
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
                        model=revised.model,
                        requested_by_user_id=pending.requested_by_user_id,
                    ),
                ),
            )
            response.async_set_speech(render_automation_preview(revised.model, entities))
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        return await self._async_handle_automation_confirmation_reply(
            user_input, response, pending, entities
        )

    async def _async_handle_pending_semantic_command(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        pending: PendingSemanticCommand,
    ) -> conversation.ConversationResult:
        """Continue a deterministic slot-filling device dialog."""
        dialog = continue_semantic_dialog(user_input.text, pending)
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

    async def _async_handle_pending_automation_draft(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        pending: ConversationContext,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        """Complete the action missing from a pending automation draft."""
        draft = pending.pending_automation_draft
        assert draft is not None
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
                        model=completed.model,
                        requested_by_user_id=conversation_user_id(user_input),
                    ),
                ),
            )
            response.async_set_speech(render_automation_preview(completed.model, entities))
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_handle_match_result(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        result: MatchResult,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        """Authorize, execute and remember one regular engine match."""
        if (
            result.plan is not None
            and analyse_utterance(user_input.text).speech_act is SpeechAct.QUERY
        ):
            self._context_store.clear(user_input.conversation_id)
            response.async_set_error(
                intent.IntentResponseErrorCode.NO_INTENT_MATCH,
                "Ich habe eine Frage erkannt und führe deshalb keine Aktion aus.",
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        if result.plan is not None:
            policy = evaluate_service_plan(
                result.plan,
                entities,
                self.entry.options,
                is_admin=await user_is_admin(self.hass, user_input),
                user_id=conversation_user_id(user_input),
            )
            if policy.outcome is PolicyOutcome.DENY:
                self._context_store.clear(user_input.conversation_id)
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    policy.reason or "Diese Aktion ist nicht erlaubt.",
                )
                return conversation.ConversationResult(
                    response=response, conversation_id=user_input.conversation_id
                )
            if policy.outcome is PolicyOutcome.CONFIRM:
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None,
                        last_entities=(),
                        last_area=None,
                        pending_clarification=None,
                        pending_service_confirmation=PendingServiceConfirmation(
                            result.plan,
                            result.response_text,
                            conversation_user_id(user_input),
                            build_undo_plan(
                                result.plan,
                                entities,
                                requested_by_user_id=conversation_user_id(user_input),
                            ),
                        ),
                    ),
                )
                response.async_set_speech(
                    f"Soll ich wirklich {result.response_text.rstrip('.')}?"
                )
                return conversation.ConversationResult(
                    response=response, conversation_id=user_input.conversation_id
                )

        undo_plan = (
            build_undo_plan(
                result.plan,
                entities,
                requested_by_user_id=conversation_user_id(user_input),
            )
            if result.plan is not None
            else None
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
                    pending_undo=undo_plan,
                    last_explanation=result.explanation_text,
                    memory=DialogTurnMemory(
                        source_text=user_input.text,
                        entities=tuple(result.command.entities),
                        explanation=result.explanation_text,
                        command=result.command,
                    ),
                ),
            )
        elif result.context_entities:
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=None,
                    last_entities=result.context_entities,
                    last_area=None,
                    pending_clarification=None,
                    last_query_predicate=result.context_predicate,
                    last_explanation=result.explanation_text,
                    memory=DialogTurnMemory(
                        source_text=user_input.text,
                        entities=result.context_entities,
                        predicate=result.context_predicate,
                        explanation=result.explanation_text,
                    ),
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
                self._record_execution(user_input, result.plan)
            except Exception as err:  # noqa: BLE001 - HA 2025.x service calls can raise beyond HomeAssistantError (vol.Invalid, TimeoutError, ...); must not propagate as "Unexpected error during intent recognition"
                self._context_store.clear(user_input.conversation_id)
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

        if (
            result.command is not None and result.command.intent in QUERY_INTENT_NAMES
        ) or (
            analyse_utterance(user_input.text).speech_act is SpeechAct.QUERY
            or result.context_predicate is not None
        ):
            response.response_type = intent.IntentResponseType.QUERY_ANSWER
        response.async_set_speech(result.response_text)
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    def _handle_automation_match_result(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        result: AutomationMatchResult,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        """Store a valid automation preview, or report its validation error."""
        if result.validation_error is None:
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=None,
                    last_entities=(),
                    last_area=None,
                    pending_clarification=None,
                    pending_automation_confirmation=PendingAutomationConfirmation(
                        model=result.model,
                        requested_by_user_id=conversation_user_id(user_input),
                    ),
                ),
            )
            response.async_set_speech(render_automation_preview(result.model, entities))
        else:
            self._context_store.clear(user_input.conversation_id)
            response.async_set_speech(result.response_text)
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    def _handle_automation_draft_match_result(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        result: AutomationDraftMatchResult,
    ) -> conversation.ConversationResult:
        """Persist a partial automation until its action is supplied."""
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

    def _handle_automation_deletion_match_result(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        result: AutomationDeletionMatchResult,
    ) -> conversation.ConversationResult:
        """Store an unambiguous deletion candidate for confirmation."""
        if result.automation is not None:
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=None,
                    last_entities=(),
                    last_area=None,
                    pending_clarification=None,
                    pending_automation_deletion=PendingAutomationDeletion(
                        automation=result.automation
                    ),
                ),
            )
        else:
            self._context_store.clear(user_input.conversation_id)
        response.async_set_speech(result.response_text)
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_handle_automation_toggle_result(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        result: AutomationToggleMatchResult,
    ) -> conversation.ConversationResult:
        """Apply an unambiguous enable/disable result immediately."""
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
            except Exception as err:  # noqa: BLE001 - HA/YAML failures are heterogeneous
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

    def _handle_clarification_result(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        result: MatchResult,
    ) -> conversation.ConversationResult:
        """Store an ambiguous match until the user selects a candidate."""
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

    async def _async_handle_no_match(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        """Try bounded correction/dialog fallbacks for an unmatched turn."""
        is_query = analyse_utterance(user_input.text).speech_act is SpeechAct.QUERY
        corrected_plans: dict[tuple, tuple[object, str, EntitySnapshot]] = {}
        for suggestion in (
            () if is_query else phonetic_suggestions(user_input.text, entities)
        ):
            corrected = self._engine.match(
                suggestion.corrected_text, entities, self._world_model
            )
            plan = getattr(corrected, "plan", None)
            success = getattr(corrected, "response_text", None)
            if plan is None:
                device = match_device_control(suggestion.corrected_text, entities)
                plan = device.plan if device is not None else None
                success = device.response_text if device is not None else None
            if plan is None or not success:
                continue
            entity_ids = (
                tuple(plan.entity_id)
                if isinstance(plan.entity_id, list)
                else (plan.entity_id,)
            )
            key = (plan.domain, plan.service, entity_ids, repr(sorted(plan.data.items())))
            corrected_plans[key] = (plan, success, suggestion.entity)
        if len(corrected_plans) == 1:
            plan, success, corrected_entity = next(iter(corrected_plans.values()))
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=None,
                    last_entities=(),
                    last_area=None,
                    pending_clarification=None,
                    pending_service_confirmation=PendingServiceConfirmation(
                        plan,
                        success,
                        conversation_user_id(user_input),
                        build_undo_plan(
                            plan,
                            entities,
                            requested_by_user_id=conversation_user_id(user_input),
                        ),
                    ),
                ),
            )
            response.async_set_speech(
                f"Meintest du „{corrected_entity.friendly_name}“? "
                f"Soll ich {success.rstrip('.')}?"
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        dialog = None if is_query else start_semantic_dialog(user_input.text, entities)
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

    async def _async_handle_command_plan(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        result: CommandPlan,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        """Authorize and execute an already validated multi-command plan."""
        if (
            analyse_utterance(user_input.text).speech_act is SpeechAct.QUERY
            and any(command.plan is not None for command in result.commands)
        ):
            self._context_store.clear(user_input.conversation_id)
            response.async_set_error(
                intent.IntentResponseErrorCode.NO_INTENT_MATCH,
                "Ich habe eine Frage erkannt und führe deshalb keine Aktion aus.",
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        # Every sub-command was validated together before this point. A HA-side
        # runtime failure remains fail-fast because service calls are not
        # transactional and already executed calls cannot be rolled back safely.
        is_admin = await user_is_admin(self.hass, user_input)
        actor_id = conversation_user_id(user_input)
        for sub_result in result.commands:
            if sub_result.plan is None:
                continue
            policy = evaluate_service_plan(
                sub_result.plan,
                entities,
                self.entry.options,
                is_admin=is_admin,
                user_id=actor_id,
            )
            if policy.outcome is PolicyOutcome.DENY:
                self._context_store.clear(user_input.conversation_id)
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    policy.reason or "Mindestens eine Aktion ist nicht erlaubt.",
                )
                return conversation.ConversationResult(
                    response=response,
                    conversation_id=user_input.conversation_id,
                )
            if policy.outcome is PolicyOutcome.CONFIRM:
                self._context_store.clear(user_input.conversation_id)
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    "Sicherheitskritische Aktionen müssen einzeln bestätigt werden.",
                )
                return conversation.ConversationResult(
                    response=response,
                    conversation_id=user_input.conversation_id,
                )
        self._context_store.clear(user_input.conversation_id)
        response_parts: list[str] = []
        multi_undo_parts: list[UndoPlan] = []
        multi_undo_supported = True
        for sub_result in result.commands:
            if sub_result.plan is None:
                response_parts.append(sub_result.response_text)
                continue
            inverse = build_undo_plan(
                sub_result.plan,
                entities,
                requested_by_user_id=actor_id,
            )
            if inverse is None:
                multi_undo_supported = False
            else:
                multi_undo_parts.append(inverse)
            try:
                await self.hass.services.async_call(
                    sub_result.plan.domain,
                    sub_result.plan.service,
                    {"entity_id": sub_result.plan.entity_id, **sub_result.plan.data},
                    blocking=True,
                )
                self._record_execution(user_input, sub_result.plan)
            except Exception as err:  # noqa: BLE001 - HA service failures are heterogeneous
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
        if multi_undo_supported and multi_undo_parts:
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=None,
                    last_entities=(),
                    last_area=None,
                    pending_clarification=None,
                    pending_undo=UndoPlan(
                        tuple(
                            plan
                            for undo in reversed(multi_undo_parts)
                            for plan in undo.plans
                        ),
                        actor_id,
                    ),
                ),
            )
        response.async_set_speech(" ".join(response_parts))
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    def _store_automation_wizard(
        self, conversation_id: str, state: AutomationWizardState
    ) -> None:
        self._context_store.set(
            conversation_id,
            ConversationContext(
                last_command=None,
                last_entities=(),
                last_area=None,
                pending_clarification=None,
                pending_automation_wizard=PendingAutomationWizard(state),
            ),
        )

    async def _async_handle_automation_wizard(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        state: AutomationWizardState,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        text = user_input.text.strip()
        if re.search(r"\b(?:abbrechen|abbruch|stopp|stop|vergiss)\b", text, re.I):
            self._context_store.clear(user_input.conversation_id)
            response.async_set_speech("Abgebrochen. Der Automationsentwurf wurde verworfen.")
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if state.stage is AutomationWizardStage.TRIGGER:
            trigger = self._engine.parse_automation_trigger(
                text, entities, self._world_model
            )
            if trigger is None:
                response.async_set_speech(
                    "Den Auslöser habe ich nicht eindeutig verstanden. "
                    "Zum Beispiel: Wenn das Küchenfenster geöffnet wird."
                )
            else:
                state = replace(
                    state,
                    stage=AutomationWizardStage.CONDITION_DECISION,
                    trigger=trigger,
                    source_parts=(*state.source_parts, text),
                )
                self._store_automation_wizard(user_input.conversation_id, state)
                response.async_set_speech(
                    "Soll zusätzlich eine Bedingung gelten? Bitte antworte mit Ja oder Nein."
                )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if state.stage is AutomationWizardStage.CONDITION_DECISION:
            reply = classify_confirmation_reply(text)
            if reply is ConfirmationReply.UNCLEAR:
                response.async_set_speech("Bitte antworte mit Ja oder Nein.")
            else:
                next_stage = (
                    AutomationWizardStage.CONDITION
                    if reply is ConfirmationReply.YES
                    else AutomationWizardStage.ACTION
                )
                state = replace(state, stage=next_stage)
                self._store_automation_wizard(user_input.conversation_id, state)
                response.async_set_speech(
                    "Welche Bedingung soll gelten?"
                    if next_stage is AutomationWizardStage.CONDITION
                    else "Was soll dann passieren?"
                )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if state.stage is AutomationWizardStage.CONDITION:
            condition = self._engine.parse_automation_condition(
                text, entities, self._world_model
            )
            if condition is None:
                response.async_set_speech(
                    "Die Bedingung habe ich nicht eindeutig verstanden. "
                    "Zum Beispiel: Nur wenn jemand zuhause ist."
                )
            else:
                state = replace(
                    state,
                    stage=AutomationWizardStage.ACTION,
                    condition=condition,
                    source_parts=(*state.source_parts, text),
                )
                self._store_automation_wizard(user_input.conversation_id, state)
                response.async_set_speech("Was soll dann passieren?")
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if state.stage is AutomationWizardStage.ACTION:
            actions = self._engine.parse_automation_actions(
                text, entities, self._world_model
            )
            if not actions:
                response.async_set_speech(
                    "Die Aktion habe ich nicht eindeutig verstanden. "
                    "Bitte nenne eine vollständige Geräteaktion."
                )
            else:
                state = replace(
                    state,
                    stage=AutomationWizardStage.LIFETIME,
                    actions=actions,
                    source_parts=(*state.source_parts, text),
                )
                self._store_automation_wizard(user_input.conversation_id, state)
                response.async_set_speech(
                    "Soll die Automation dauerhaft, einmalig oder nur eine bestimmte Anzahl Mal gelten?"
                )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        lifetime = parse_lifetime(text)
        if lifetime is None:
            response.async_set_speech(
                "Bitte sage dauerhaft, einmalig oder zum Beispiel nur dreimal."
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        once, max_runs = lifetime
        assert state.trigger is not None and state.actions
        model = AutomationModel(
            triggers=(state.trigger,),
            conditions=(state.condition,) if state.condition is not None else (),
            actions=state.actions,
            source_text="; ".join((*state.source_parts, text)),
            once=once,
            max_runs=max_runs,
        )
        validation_error = validate_automation(model)
        if validation_error is not None:
            self._context_store.clear(user_input.conversation_id)
            response.async_set_speech(
                "Der vollständige Entwurf ist strukturell nicht sicher ausführbar: "
                + validation_error.name
            )
        else:
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=None,
                    last_entities=(),
                    last_area=None,
                    pending_clarification=None,
                    pending_automation_confirmation=PendingAutomationConfirmation(
                        model, conversation_user_id(user_input)
                    ),
                ),
            )
            response.async_set_speech(render_automation_preview(model, entities))
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    def _store_productivity(
        self,
        conversation_id: str,
        request: ProductivityRequest,
        *,
        awaiting_confirmation: bool = False,
    ) -> None:
        self._context_store.set(
            conversation_id,
            ConversationContext(
                last_command=None,
                last_entities=(),
                last_area=None,
                pending_clarification=None,
                pending_productivity_command=PendingProductivityCommand(
                    request=request,
                    awaiting_confirmation=awaiting_confirmation,
                ),
            ),
        )

    async def _async_handle_pending_productivity(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        pending: PendingProductivityCommand,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        if pending.awaiting_confirmation:
            reply = classify_confirmation_reply(user_input.text)
            if reply is ConfirmationReply.UNCLEAR:
                response.async_set_speech("Bitte antworte mit Ja oder Nein.")
                return conversation.ConversationResult(
                    response=response, conversation_id=user_input.conversation_id
                )
            self._context_store.clear(user_input.conversation_id)
            if reply is ConfirmationReply.NO:
                response.async_set_speech("Abgebrochen. Die Liste wurde nicht verändert.")
                return conversation.ConversationResult(
                    response=response, conversation_id=user_input.conversation_id
                )
            return await self._async_execute_productivity(
                user_input, response, pending.request, entities
            )

        selected = select_productivity_candidate(pending.request, user_input.text)
        if selected is None:
            labels = ", ".join(item.friendly_name for item in pending.request.candidates)
            question = "Welche Liste" if isinstance(pending.request, TodoRequest) else "Welchen Timer"
            response.async_set_speech(f"{question} meinst du? {labels}.")
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        return await self._async_handle_productivity_request(
            user_input, response, selected, entities
        )

    async def _async_handle_productivity_request(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        request: ProductivityRequest,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        if request.entity_id is None:
            if request.candidates:
                self._store_productivity(user_input.conversation_id, request)
                labels = ", ".join(item.friendly_name for item in request.candidates)
                question = "Welche Liste" if isinstance(request, TodoRequest) else "Welchen Timer"
                response.async_set_speech(f"{question} meinst du? {labels}.")
            else:
                noun = "keine für HomeIntent freigegebene Liste" if isinstance(request, TodoRequest) else "keinen für HomeIntent freigegebenen Timer"
                response.async_set_speech(f"Ich finde {noun}.")
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if (
            isinstance(request, TodoRequest)
            and request.operation is TodoOperation.CLEAR_COMPLETED
        ):
            self._store_productivity(
                user_input.conversation_id, request, awaiting_confirmation=True
            )
            response.async_set_speech(
                "Soll ich wirklich alle erledigten Einträge aus der Liste löschen?"
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        self._context_store.clear(user_input.conversation_id)
        return await self._async_execute_productivity(
            user_input, response, request, entities
        )

    async def _async_execute_productivity(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        request: ProductivityRequest,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        try:
            if isinstance(request, TodoRequest):
                speech = await self._async_execute_todo(request)
            else:
                speech = await self._async_execute_timer(request, entities)
        except Exception as err:  # noqa: BLE001 - HA service errors are heterogeneous
            _LOGGER.error("Productivity command failed: %s", err)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                f"Fehler beim Ausführen: {err}",
            )
        else:
            response.async_set_speech(speech)
            if isinstance(request, TodoRequest) and request.operation is not TodoOperation.LIST:
                todo_service = {
                    TodoOperation.ADD: "add_item",
                    TodoOperation.COMPLETE: "update_item",
                    TodoOperation.REMOVE: "remove_item",
                    TodoOperation.CLEAR_COMPLETED: "remove_completed_items",
                    TodoOperation.MOVE: "move_items",
                }[request.operation]
                self._record_execution(
                    user_input,
                    ServiceCallPlan("todo", todo_service, request.entity_id, {}),
                )
            elif isinstance(request, TimerRequest) and request.operation is not TimerOperation.STATUS:
                timer_service = {
                    TimerOperation.START: "start",
                    TimerOperation.CHANGE: "change",
                    TimerOperation.PAUSE: "pause",
                    TimerOperation.RESUME: "start",
                    TimerOperation.CANCEL: "cancel",
                    TimerOperation.FINISH: "finish",
                }[request.operation]
                self._record_execution(
                    user_input,
                    ServiceCallPlan("timer", timer_service, request.entity_id, {}),
                )
            if (
                isinstance(request, TimerRequest)
                and request.operation is TimerOperation.STATUS
            ) or (
                isinstance(request, TodoRequest)
                and request.operation is TodoOperation.LIST
            ):
                response.response_type = intent.IntentResponseType.QUERY_ANSWER
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_get_todo_items(self, entity_id: str) -> list[dict]:
        result = await self.hass.services.async_call(
            "todo",
            "get_items",
            {"status": ["needs_action", "completed"]},
            target={"entity_id": entity_id},
            blocking=True,
            return_response=True,
        )
        container = result.get(entity_id, result) if isinstance(result, dict) else {}
        items = container.get("items", []) if isinstance(container, dict) else []
        return [item for item in items if isinstance(item, dict)]

    async def _async_execute_todo(self, request: TodoRequest) -> str:
        assert request.entity_id is not None
        if request.operation is TodoOperation.LIST:
            items = await self._async_get_todo_items(request.entity_id)
            open_items = [
                str(item.get("summary") or item.get("item") or "").strip()
                for item in items
                if item.get("status", "needs_action") == "needs_action"
            ]
            open_items = [item for item in open_items if item]
            return (
                "Auf der Liste steht nichts Offenes."
                if not open_items
                else "Auf der Liste stehen: " + ", ".join(open_items) + "."
            )

        if request.operation is TodoOperation.CLEAR_COMPLETED:
            items = await self._async_get_todo_items(request.entity_id)
            completed = [
                item.get("uid") or item.get("summary") or item.get("item")
                for item in items
                if item.get("status") == "completed"
            ]
            completed = [item for item in completed if item]
            if completed:
                await self.hass.services.async_call(
                    "todo", "remove_completed_items", {},
                    target={"entity_id": request.entity_id}, blocking=True,
                )
            return (
                "Es gab keine erledigten Einträge."
                if not completed
                else f"{len(completed)} erledigte Einträge wurden gelöscht."
            )

        def matching_items(
            available: list[dict], requested: tuple[str, ...]
        ) -> list[dict]:
            """Resolve spoken summaries to stable todo UIDs without guessing."""
            selected: list[dict] = []
            for spoken in requested:
                key = normalize_for_compare(spoken)
                matches = []
                for candidate in available:
                    summary = str(
                        candidate.get("summary") or candidate.get("item") or ""
                    ).strip()
                    # Home Assistant has no portable priority field. HomeIntent
                    # stores it as a visible prefix, but users need not repeat it.
                    plain_summary = re.sub(
                        r"^\[(?:hoch|mittel|niedrig)\]\s*", "", summary,
                        flags=re.IGNORECASE,
                    )
                    if normalize_for_compare(plain_summary) == key:
                        matches.append(candidate)
                if not matches:
                    raise ValueError(f"Eintrag „{spoken}“ wurde nicht gefunden")
                if len(matches) > 1:
                    raise ValueError(
                        f"Eintrag „{spoken}“ ist mehrfach vorhanden. "
                        "Bitte mache ihn zuerst eindeutig"
                    )
                selected.append(matches[0])
            return selected

        if request.operation in {TodoOperation.COMPLETE, TodoOperation.REMOVE}:
            available = await self._async_get_todo_items(request.entity_id)
            selected = matching_items(available, request.items)
            service = (
                "update_item"
                if request.operation is TodoOperation.COMPLETE
                else "remove_item"
            )
            for item in selected:
                uid = item.get("uid")
                if not uid:
                    raise ValueError("Die Liste liefert keine stabile Eintrags-ID")
                data: dict[str, object] = {"item": uid}
                if request.operation is TodoOperation.COMPLETE:
                    data["status"] = "completed"
                await self.hass.services.async_call(
                    "todo", service, data,
                    target={"entity_id": request.entity_id}, blocking=True,
                )
            count = len(selected)
            if request.operation is TodoOperation.COMPLETE:
                return f"{count} Eintrag" + (" wurde" if count == 1 else "e wurden") + " als erledigt markiert."
            return f"{count} Eintrag" + (" wurde" if count == 1 else "e wurden") + " aus der Liste entfernt."

        if request.operation is TodoOperation.MOVE:
            if request.destination_entity_id is None:
                raise ValueError("Die Zielliste fehlt")
            available = await self._async_get_todo_items(request.entity_id)
            selected = matching_items(available, request.items)
            # Resolve every source item before the first write. A partial move
            # can therefore only result from an external HA service failure.
            added: list[dict] = []
            try:
                for item in selected:
                    summary = str(item.get("summary") or item.get("item") or "")
                    data: dict[str, object] = {"item": summary}
                    due = item.get("due") or item.get("due_date") or item.get("due_datetime")
                    if due:
                        data["due_datetime" if "T" in str(due) else "due_date"] = due
                    if item.get("description"):
                        data["description"] = item["description"]
                    await self.hass.services.async_call(
                        "todo", "add_item", data,
                        target={"entity_id": request.destination_entity_id}, blocking=True,
                    )
                    added.append(item)
                for item in selected:
                    uid = item.get("uid")
                    if not uid:
                        raise ValueError("Die Liste liefert keine stabile Eintrags-ID")
                    await self.hass.services.async_call(
                        "todo", "remove_item", {"item": uid},
                        target={"entity_id": request.entity_id}, blocking=True,
                    )
            except Exception:
                _LOGGER.warning(
                    "Todo move failed after %d destination writes; source items "
                    "were retained where possible", len(added)
                )
                raise
            count = len(selected)
            return f"{count} Eintrag" + (" wurde" if count == 1 else "e wurden") + " verschoben."

        assert request.operation is TodoOperation.ADD
        for item in request.items:
            stored_item = (
                f"[{request.priority.capitalize()}] {item}"
                if request.priority else item
            )
            data: dict[str, object] = {"item": stored_item}
            if request.due_date:
                data["due_date"] = request.due_date
            if request.description:
                data["description"] = request.description
            await self.hass.services.async_call(
                "todo", "add_item", data,
                target={"entity_id": request.entity_id}, blocking=True,
            )
        count = len(request.items)
        return (
            f"{request.items[0]} wurde zur Liste hinzugefügt."
            if count == 1
            else f"{count} Einträge wurden zur Liste hinzugefügt: "
            + ", ".join(request.items) + "."
        )

    async def _async_execute_timer(
        self, request: TimerRequest, entities: list[EntitySnapshot]
    ) -> str:
        assert request.entity_id is not None
        entity = next((item for item in entities if item.entity_id == request.entity_id), None)
        if request.operation is TimerOperation.STATUS:
            if entity is None:
                return "Der Timer ist nicht mehr verfügbar."
            if entity.state == "idle":
                return "Der Timer ist nicht aktiv."
            remaining = entity.attributes.get("remaining") or entity.attributes.get("duration")
            state = "pausiert" if entity.state == "paused" else "aktiv"
            return f"Der Timer ist {state}. Verbleibende Zeit: {remaining}."

        service = {
            TimerOperation.START: "start",
            TimerOperation.CHANGE: "change",
            TimerOperation.PAUSE: "pause",
            TimerOperation.RESUME: "start",
            TimerOperation.CANCEL: "cancel",
            TimerOperation.FINISH: "finish",
        }[request.operation]
        data: dict[str, str | int] = {}
        if request.operation is TimerOperation.START:
            assert request.duration_seconds is not None
            data["duration"] = self._timer_duration_value(request.duration_seconds)
        elif request.operation is TimerOperation.CHANGE:
            assert request.change_seconds is not None
            # timer.change explicitly accepts signed seconds; using the
            # integer form avoids ambiguity around a negative HH:MM string.
            data["duration"] = request.change_seconds
        await self.hass.services.async_call(
            "timer", service, data,
            target={"entity_id": request.entity_id}, blocking=True,
        )
        if request.operation is TimerOperation.START:
            return f"Timer für {format_duration(request.duration_seconds or 0)} gestartet."
        if request.operation is TimerOperation.CHANGE:
            verb = "verlängert" if (request.change_seconds or 0) > 0 else "verkürzt"
            return f"Timer um {format_duration(request.change_seconds or 0)} {verb}."
        return {
            TimerOperation.PAUSE: "Timer pausiert.",
            TimerOperation.RESUME: "Timer fortgesetzt.",
            TimerOperation.CANCEL: "Timer abgebrochen.",
            TimerOperation.FINISH: "Timer beendet.",
        }[request.operation]

    @staticmethod
    def _timer_duration_value(seconds: int) -> str:
        sign = "-" if seconds < 0 else ""
        hours, remainder = divmod(abs(seconds), 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{sign}{hours:02d}:{minutes:02d}:{secs:02d}"

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
        current_user_id = conversation_user_id(user_input)
        if (
            confirmation.requested_by_user_id is not None
            and confirmation.requested_by_user_id != current_user_id
        ):
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                "Diese Bestätigung gehört zu einem anderen Benutzer.",
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

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

        if (
            not bool(
                self.entry.options.get(CONF_ALLOW_NON_ADMIN_AUTOMATIONS, True)
            )
            and not await user_is_admin(self.hass, user_input)
        ):
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                "Das Erstellen von Automationen ist nur für Administratoren erlaubt.",
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        controlled_ids = resolve_automation_action_entity_ids(
            confirmation.model, entities
        )
        target_policy_error = validate_automation_action_targets(
            controlled_ids,
            self.entry.options,
            is_admin=await user_is_admin(self.hass, user_input),
            user_id=conversation_user_id(user_input),
        )
        if target_policy_error is not None:
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                target_policy_error,
            )
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
            created_id = await self._automation_executor.async_create_automation(
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

        self._record_execution(
            user_input,
            ServiceCallPlan("ha_nlu", "create_automation", created_id, {}),
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
        if (
            device_control.plan is not None
            and analyse_utterance(user_input.text).speech_act is SpeechAct.QUERY
        ):
            self._context_store.clear(user_input.conversation_id)
            response.async_set_error(
                intent.IntentResponseErrorCode.NO_INTENT_MATCH,
                "Ich habe eine Frage erkannt und führe deshalb keine Aktion aus.",
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        if device_control.plan is None:
            self._context_store.clear(user_input.conversation_id)
            if device_control.is_query:
                response.response_type = intent.IntentResponseType.QUERY_ANSWER
            response.async_set_speech(device_control.response_text)
        else:
            resolved_entities = list(device_control.resolved_entities)
            policy = evaluate_service_plan(
                device_control.plan,
                resolved_entities,
                self.entry.options,
                is_admin=await user_is_admin(self.hass, user_input),
                user_id=conversation_user_id(user_input),
            )
            if policy.outcome is PolicyOutcome.DENY:
                self._context_store.clear(user_input.conversation_id)
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    policy.reason or "Diese Aktion ist nicht erlaubt.",
                )
                return conversation.ConversationResult(
                    response=response, conversation_id=user_input.conversation_id
                )
            needs_confirmation = (
                device_control.requires_confirmation
                or policy.outcome is PolicyOutcome.CONFIRM
            )
            if needs_confirmation:
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None,
                        last_entities=(),
                        last_area=None,
                        pending_clarification=None,
                        pending_service_confirmation=PendingServiceConfirmation(
                            device_control.plan,
                            device_control.response_text,
                            conversation_user_id(user_input),
                            build_undo_plan(
                                device_control.plan,
                                resolved_entities,
                                requested_by_user_id=conversation_user_id(user_input),
                            ),
                        ),
                    ),
                )
                response.async_set_speech(
                    f"Soll ich wirklich {device_control.response_text.rstrip('.')}?"
                )
                return conversation.ConversationResult(
                    response=response, conversation_id=user_input.conversation_id
                )
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
                self._record_execution(user_input, device_control.plan)
            except Exception as err:  # noqa: BLE001 - HA services raise heterogeneous errors
                self._context_store.clear(user_input.conversation_id)
                _LOGGER.error(
                    "Device-control service call %s.%s on %s failed: %s",
                    device_control.plan.domain,
                    device_control.plan.service,
                    device_control.plan.entity_id,
                    err,
                    exc_info=True,
                )
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    f"Fehler beim Ausführen: {err}",
                )
            else:
                response.async_set_speech(device_control.response_text)
                if resolved_entities:
                    controlled = resolved_entities[0]
                    self._context_store.set(
                        user_input.conversation_id,
                        ConversationContext(
                            last_command=None,
                            last_entities=tuple(resolved_entities),
                            last_area=None,
                            pending_clarification=None,
                            focus=DialogFocus(
                                property=None,
                                scope_kind=("entity" if len(resolved_entities) == 1 else None),
                                scope_id=(controlled.entity_id if len(resolved_entities) == 1 else None),
                                candidate_entity_ids=tuple(
                                    entity.entity_id for entity in resolved_entities
                                ),
                                source_intent="DeviceControl:" + device_control.plan.service,
                            ),
                            pending_undo=build_undo_plan(
                                device_control.plan,
                                resolved_entities,
                                requested_by_user_id=conversation_user_id(user_input),
                            ),
                        ),
                    )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    def _record_execution(self, user_input, plan) -> None:
        context = getattr(user_input, "context", None)
        self._audit_trail.record(
            dt_util.now(), getattr(context, "user_id", None), plan
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
                self._record_execution(
                    user_input,
                    ServiceCallPlan("calendar", "create_event", call.entity_id, {}),
                )
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
        if request.kind in {
            AutomationManagementKind.CLEAN_EXPIRED,
            AutomationManagementKind.ROLLBACK,
        }:
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=None,
                    last_entities=(),
                    last_area=None,
                    pending_clarification=None,
                    pending_automation_management=PendingAutomationManagement(request),
                ),
            )
            response.async_set_speech(
                "Soll ich die letzte HomeIntent-Automationsänderung wirklich rückgängig machen?"
                if request.kind is AutomationManagementKind.ROLLBACK
                else "Soll ich alle abgelaufenen HomeIntent-Aufträge wirklich löschen?"
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
            AutomationManagementKind.DETAIL,
            AutomationManagementKind.DIAGNOSE,
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
                if request.kind is AutomationManagementKind.DIAGNOSE:
                    item = selection.automations[0]
                    live = self._automation_executor.automation_runtime_info(
                        item.automation_id
                    )
                    enabled = item.enabled and (
                        live is None or live.get("state") != "off"
                    )
                    last = live.get("last_triggered") if live else None
                    response.async_set_speech(
                        f"{_automation_label(item)} ist "
                        f"{'aktiv' if enabled else 'deaktiviert'}, hat "
                        f"{len(item.triggers)} Auslöser und {len(item.conditions)} Bedingungen. "
                        + (
                            f"Zuletzt ausgelöst: {last}. " if last else
                            "Home Assistant meldet keine letzte Auslösung. "
                        )
                        + "Ohne gespeicherte Home-Assistant-Ablaufverfolgung kann ich die "
                        "genaue Ursache nicht beweisen; häufig sind Auslöser nicht eingetreten "
                        "oder eine Bedingung war zu diesem Zeitpunkt falsch."
                    )
                elif request.kind is AutomationManagementKind.DETAIL:
                    item = selection.automations[0]
                    response.async_set_speech(
                        f"{_automation_label(item)}: {len(item.triggers)} Auslöser, "
                        f"{len(item.conditions)} Bedingungen und {len(item.actions)} Aktionen. "
                        f"Quelle: {item.source_text or item.alias}."
                    )
                else:
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
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None, last_entities=(), last_area=None,
                        pending_clarification=None,
                        pending_automation_management=PendingAutomationManagement(
                            request=request, candidates=selection.automations
                        ),
                    ),
                )
                response.async_set_speech(
                    "Mehrere Aufträge passen. Bitte nenne das Gerät oder wähle "
                    "einen Auftrag per Name oder Nummer: "
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
                    self._context_store.set(
                        user_input.conversation_id,
                        ConversationContext(
                            last_command=None,
                            last_entities=(),
                            last_area=None,
                            pending_clarification=None,
                            pending_automation_management=PendingAutomationManagement(
                                request, automation, target
                            ),
                        ),
                    )
                    response.async_set_speech(
                        f"Soll ich {_automation_label(automation)} wirklich auf "
                        f"{format_scheduled_time(target.isoformat())} verschieben?"
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
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None, last_entities=(), last_area=None,
                        pending_clarification=None,
                        pending_automation_management=PendingAutomationManagement(
                            request=request, candidates=selection.automations
                        ),
                    ),
                )
                response.async_set_speech(
                    "Mehrere Automationen passen. Welche meinst du? "
                    + labels
                    + "."
                )
            else:
                automation = selection.automations[0]
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None,
                        last_entities=(),
                        last_area=None,
                        pending_clarification=None,
                        pending_automation_management=PendingAutomationManagement(
                            request, automation
                        ),
                    ),
                )
                response.async_set_speech(
                    f"Soll {_automation_label(automation)} wirklich auf "
                    f"{request.max_runs} Ausführungen begrenzt werden?"
                )
        elif request.kind is AutomationManagementKind.DUPLICATE:
            if not selection.automations:
                response.async_set_speech("Ich finde keine passende HomeIntent-Automation.")
            elif len(selection.automations) > 1:
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None, last_entities=(), last_area=None,
                        pending_clarification=None,
                        pending_automation_management=PendingAutomationManagement(
                            request=request, candidates=selection.automations
                        ),
                    ),
                )
                response.async_set_speech(
                    "Mehrere Automationen passen. Welche soll kopiert werden? "
                    + ", ".join(_automation_label(item) for item in selection.automations)
                    + "."
                )
            else:
                automation = selection.automations[0]
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None, last_entities=(), last_area=None,
                        pending_clarification=None,
                        pending_automation_management=PendingAutomationManagement(
                            request=request, automation=automation
                        ),
                    ),
                )
                response.async_set_speech(
                    f"Soll ich {_automation_label(automation)} wirklich duplizieren?"
                )
        elif request.kind is AutomationManagementKind.PAUSE_UNTIL:
            if not selection.automations:
                response.async_set_speech("Ich finde keine passende HomeIntent-Automation.")
            elif len(selection.automations) > 1:
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None, last_entities=(), last_area=None,
                        pending_clarification=None,
                        pending_automation_management=PendingAutomationManagement(
                            request=request, candidates=selection.automations
                        ),
                    ),
                )
                response.async_set_speech(
                    "Mehrere Automationen passen. Welche soll pausiert werden? "
                    + ", ".join(_automation_label(item) for item in selection.automations)
                    + "."
                )
            else:
                target = (now + timedelta(days=request.day_offset)).replace(
                    hour=request.hour, minute=request.minute, second=0, microsecond=0
                )
                if request.day_offset == 0 and target <= now:
                    target += timedelta(days=1)
                automation = selection.automations[0]
                self._context_store.set(
                    user_input.conversation_id,
                    ConversationContext(
                        last_command=None, last_entities=(), last_area=None,
                        pending_clarification=None,
                        pending_automation_management=PendingAutomationManagement(
                            request=request, automation=automation, target=target
                        ),
                    ),
                )
                response.async_set_speech(
                    f"Soll ich {_automation_label(automation)} bis "
                    f"{format_scheduled_time(target.isoformat())} pausieren?"
                )
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    async def _async_handle_automation_management_confirmation(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        pending: PendingAutomationManagement,
    ) -> conversation.ConversationResult:
        if pending.candidates:
            automation = select_candidate_reply(user_input.text, pending.candidates)
            if automation is None:
                response.async_set_speech(
                    "Das ist nicht eindeutig. Bitte nenne eine Automation oder sage "
                    "die erste, die zweite oder die dritte: "
                    + ", ".join(_automation_label(item) for item in pending.candidates)
                    + "."
                )
                return conversation.ConversationResult(
                    response=response, conversation_id=user_input.conversation_id
                )
            request = pending.request
            if request.kind is AutomationManagementKind.RESCHEDULE:
                now = dt_util.now()
                target = datetime.fromisoformat(automation.scheduled_for)
                target = target.replace(hour=request.hour, minute=request.minute, second=0)
                comparable_now = now
                if target.tzinfo is None and now.tzinfo is not None:
                    comparable_now = now.replace(tzinfo=None)
                elif target.tzinfo is not None and now.tzinfo is None:
                    comparable_now = now.replace(tzinfo=target.tzinfo)
                if target <= comparable_now:
                    self._context_store.clear(user_input.conversation_id)
                    response.async_set_speech("Die neue Uhrzeit liegt bereits in der Vergangenheit.")
                    return conversation.ConversationResult(response=response, conversation_id=user_input.conversation_id)
                replacement = PendingAutomationManagement(request, automation, target)
                question = (
                    f"Soll ich {_automation_label(automation)} wirklich auf "
                    f"{format_scheduled_time(target.isoformat())} verschieben?"
                )
            elif request.kind is AutomationManagementKind.DUPLICATE:
                replacement = PendingAutomationManagement(request, automation)
                question = f"Soll ich {_automation_label(automation)} wirklich duplizieren?"
            elif request.kind is AutomationManagementKind.PAUSE_UNTIL:
                now = dt_util.now()
                target = (now + timedelta(days=request.day_offset)).replace(
                    hour=request.hour, minute=request.minute, second=0, microsecond=0
                )
                if request.day_offset == 0 and target <= now:
                    target += timedelta(days=1)
                replacement = PendingAutomationManagement(request, automation, target)
                question = (
                    f"Soll ich {_automation_label(automation)} bis "
                    f"{format_scheduled_time(target.isoformat())} pausieren?"
                )
            else:
                replacement = PendingAutomationManagement(request, automation)
                question = (
                    f"Soll {_automation_label(automation)} wirklich auf "
                    f"{request.max_runs} Ausführungen begrenzt werden?"
                )
            self._context_store.set(
                user_input.conversation_id,
                ConversationContext(
                    last_command=None, last_entities=(), last_area=None,
                    pending_clarification=None,
                    pending_automation_management=replacement,
                ),
            )
            response.async_set_speech(question)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        reply = classify_confirmation_reply(user_input.text)
        if reply is ConfirmationReply.UNCLEAR:
            response.async_set_speech("Bitte antworte mit Ja oder Nein.")
            return conversation.ConversationResult(response=response, conversation_id=user_input.conversation_id)
        self._context_store.clear(user_input.conversation_id)
        if reply is ConfirmationReply.NO:
            response.async_set_speech("Abgebrochen. Es wurde nichts verändert.")
            return conversation.ConversationResult(response=response, conversation_id=user_input.conversation_id)
        assert self._automation_executor is not None
        request = pending.request
        try:
            if request.kind is AutomationManagementKind.CLEAN_EXPIRED:
                removed = await self._automation_executor.async_cleanup_expired_scheduled_automations(dt_util.now())
                response.async_set_speech(
                    "Es waren keine abgelaufenen HomeIntent-Aufträge vorhanden."
                    if not removed else f"{len(removed)} abgelaufene HomeIntent-Aufträge wurden gelöscht."
                )
            elif request.kind is AutomationManagementKind.ROLLBACK:
                operation = await self._automation_executor.async_rollback_last_change()
                response.async_set_speech(
                    f"Die letzte HomeIntent-Änderung ({operation}) wurde rückgängig gemacht."
                )
            elif request.kind is AutomationManagementKind.RESCHEDULE:
                assert pending.automation is not None and pending.target is not None
                await self._automation_executor.async_reschedule_automation(
                    pending.automation.automation_id, pending.target
                )
                response.async_set_speech(
                    "Der Auftrag wurde auf " + format_scheduled_time(pending.target.isoformat()) + " verschoben."
                )
            elif request.kind is AutomationManagementKind.DUPLICATE:
                assert pending.automation is not None
                await self._automation_executor.async_duplicate_automation(
                    pending.automation.automation_id
                )
                response.async_set_speech(
                    f"{_automation_label(pending.automation)} wurde dupliziert."
                )
            elif request.kind is AutomationManagementKind.PAUSE_UNTIL:
                assert pending.automation is not None and pending.target is not None
                await self._automation_executor.async_pause_automation_until(
                    pending.automation.automation_id, pending.target
                )
                response.async_set_speech(
                    f"{_automation_label(pending.automation)} ist bis "
                    f"{format_scheduled_time(pending.target.isoformat())} pausiert."
                )
            else:
                assert pending.automation is not None
                await self._automation_executor.async_set_max_runs(
                    pending.automation.automation_id, request.max_runs
                )
                response.async_set_speech(
                    f"{_automation_label(pending.automation)} wird nur noch {request.max_runs} Mal ausgeführt."
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Automation management failed: %s", err, exc_info=True)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                f"Fehler beim Ändern der Automation: {err}",
            )
        return conversation.ConversationResult(response=response, conversation_id=user_input.conversation_id)

    async def _async_handle_service_confirmation_reply(
        self,
        user_input: conversation.ConversationInput,
        response: intent.IntentResponse,
        confirmation: PendingServiceConfirmation,
        entities: list[EntitySnapshot],
    ) -> conversation.ConversationResult:
        """Confirm a high-risk lock or garage movement before execution."""
        current_user_id = conversation_user_id(user_input)
        if (
            confirmation.requested_by_user_id is not None
            and confirmation.requested_by_user_id != current_user_id
        ):
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                "Diese Bestätigung gehört zu einem anderen Benutzer.",
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
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
            undo = build_undo_plan(
                confirmation.plan,
                entities,
                requested_by_user_id=current_user_id,
            )
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
                self._record_execution(user_input, confirmation.plan)
            except Exception as err:  # noqa: BLE001 - HA service failures are heterogeneous
                _LOGGER.error(
                    "Confirmed service call %s.%s on %s failed: %s",
                    confirmation.plan.domain,
                    confirmation.plan.service,
                    confirmation.plan.entity_id,
                    err,
                    exc_info=True,
                )
                response.async_set_error(
                    intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                    f"Fehler beim Ausführen: {err}",
                )
            else:
                response.async_set_speech(confirmation.success_text)
                if undo is not None:
                    self._context_store.set(
                        user_input.conversation_id,
                        ConversationContext(
                            last_command=None,
                            last_entities=(),
                            last_area=None,
                            pending_clarification=None,
                            pending_undo=undo,
                        ),
                    )
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
