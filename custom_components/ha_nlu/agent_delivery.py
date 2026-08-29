"""HA-facing multi-channel delivery for deterministic agent messages."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping

from homeassistant.core import HomeAssistant

from .agent_event import AgentEvent, AgentEventState, AgentMode
from .const import (
    AGENT_CHANNEL_PUSH,
    AGENT_CHANNEL_TTS,
    CONF_AGENT_DELIVERY_CHANNELS,
    CONF_AGENT_MEDIA_PLAYERS,
    CONF_AGENT_NOTIFY_TARGETS,
    CONF_AGENT_TTS_ENTITY,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeliveryResult:
    delivered_channels: tuple[str, ...]
    errors: tuple[str, ...]


class AgentDelivery:
    """Routes already-reasoned messages; it never evaluates rules or actions."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def async_deliver(
        self, event: AgentEvent, options: Mapping[str, object]
    ) -> DeliveryResult:
        raw_channels = options.get(CONF_AGENT_DELIVERY_CHANNELS, (AGENT_CHANNEL_PUSH,))
        channels = (
            {str(item) for item in raw_channels}
            if isinstance(raw_channels, (list, tuple, set))
            else {AGENT_CHANNEL_PUSH}
        )
        delivered: list[str] = []
        errors: list[str] = []
        if AGENT_CHANNEL_PUSH in channels:
            try:
                await self._async_push(event, options)
                delivered.append(AGENT_CHANNEL_PUSH)
            except Exception as err:  # noqa: BLE001 - HA services fail heterogeneously
                _LOGGER.warning("Agent push delivery failed: %s", err)
                errors.append(f"push: {err}")
        if AGENT_CHANNEL_TTS in channels:
            try:
                await self._async_tts(event, options)
                delivered.append(AGENT_CHANNEL_TTS)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Agent TTS delivery failed: %s", err)
                errors.append(f"tts: {err}")
        return DeliveryResult(tuple(delivered), tuple(errors))

    async def _async_push(
        self, event: AgentEvent, options: Mapping[str, object]
    ) -> None:
        raw_targets = options.get(CONF_AGENT_NOTIFY_TARGETS, ())
        targets = (
            [str(item) for item in raw_targets if isinstance(item, str)]
            if isinstance(raw_targets, (list, tuple))
            else []
        )
        actions = [] if event.state is AgentEventState.RESOLVED else [
            {"action": f"HA_NLU_IGNORE_{event.event_id}", "title": "Ignorieren"},
            {
                "action": f"HA_NLU_SNOOZE_{event.event_id}",
                "title": "In 30 Minuten erinnern",
            },
        ]
        if (
            event.state is not AgentEventState.RESOLVED
            and event.mode is AgentMode.ASK
            and event.proposed_action is not None
        ):
            actions.insert(
                0,
                {
                    "action": f"HA_NLU_EXECUTE_{event.event_id}",
                    "title": "Ausführen",
                },
            )
        if targets:
            await self._hass.services.async_call(
                "notify",
                "send_message",
                {
                    "entity_id": targets,
                    "title": event.title,
                    "message": event.message,
                    "data": {
                        "tag": f"homeintent_{event.event_id}",
                        "actions": actions,
                    },
                },
                blocking=True,
            )
            return
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": event.title,
                "message": event.message,
                "notification_id": f"homeintent_{event.event_id}",
            },
            blocking=True,
        )

    async def _async_tts(
        self, event: AgentEvent, options: Mapping[str, object]
    ) -> None:
        tts_entity = options.get(CONF_AGENT_TTS_ENTITY)
        raw_players = options.get(CONF_AGENT_MEDIA_PLAYERS, ())
        players = (
            [str(item) for item in raw_players if isinstance(item, str)]
            if isinstance(raw_players, (list, tuple))
            else []
        )
        if not isinstance(tts_entity, str) or not tts_entity or not players:
            raise ValueError("TTS-Engine und mindestens ein TTS-Ziel müssen konfiguriert sein")
        await self._hass.services.async_call(
            "tts",
            "speak",
            {
                "entity_id": tts_entity,
                "media_player_entity_id": players,
                "message": event.message,
            },
            blocking=True,
        )
