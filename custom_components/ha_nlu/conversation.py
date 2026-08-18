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
from typing import Literal

from homeassistant.components import conversation
from homeassistant.components.conversation import ConversationEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, intent
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NOT_UNDERSTOOD_TEXT
from .engine import CommandPlan, NluEngine
from .hass_entities import build_device_snapshots, build_entity_snapshots
from .nlu.context import ConversationContext, ConversationContextStore
from .service_call import QUERY_INTENTS
from .world_model import WorldModel, build_world_model as assemble_world_model

_LOGGER = logging.getLogger(__name__)

# Single source of truth for "which intents are queries" (V4.2) - read state
# and speak, never call a service - so Assist shows them as a QUERY_ANSWER
# rather than the default ACTION_DONE.
QUERY_INTENT_NAMES = frozenset(QUERY_INTENTS)


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

        if pending is not None and pending.pending_clarification is not None:
            result = self._engine.resolve_clarification(
                user_input.text, pending.pending_clarification, entities
            )
            self._context_store.clear(user_input.conversation_id)
        else:
            result = self._engine.match_followup(user_input.text, pending)
            if result is None:
                result = self._engine.match_reference(user_input.text, entities, pending)
            if result is None:
                result = self._engine.match_query_followup(
                    user_input.text, entities, pending, self._world_model
                )
            if result is None:
                result = self._engine.match_command_followup(user_input.text, entities, pending)
            if result is None:
                result = self._engine.match(user_input.text, entities, self._world_model)

        if result is None:
            response.async_set_error(
                intent.IntentResponseErrorCode.NO_INTENT_MATCH,
                NOT_UNDERSTOOD_TEXT,
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
                    continue  # structurally unreachable - CommandPlan only ever wraps actionable sub-results
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
