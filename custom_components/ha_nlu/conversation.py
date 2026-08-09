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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, intent
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NOT_UNDERSTOOD_TEXT
from .engine import NluEngine
from .hass_entities import build_entity_snapshots

_LOGGER = logging.getLogger(__name__)


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
        """Match the utterance and either act on it or say "not understood"."""
        response = intent.IntentResponse(language=user_input.language)

        entities = build_entity_snapshots(self.hass, self.entry)
        result = self._engine.match(user_input.text, entities)

        if result is None:
            response.async_set_error(
                intent.IntentResponseErrorCode.NO_INTENT_MATCH,
                NOT_UNDERSTOOD_TEXT,
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if result.plan is not None:
            try:
                await self.hass.services.async_call(
                    result.plan.domain,
                    result.plan.service,
                    {"entity_id": result.plan.entity_id, **result.plan.data},
                    blocking=True,
                )
            except HomeAssistantError as err:
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

        response.async_set_speech(result.response_text)
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )
