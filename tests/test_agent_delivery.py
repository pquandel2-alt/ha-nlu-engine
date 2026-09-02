from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

from ha_nlu.agent_delivery import AgentDelivery  # noqa: E402
from ha_nlu.agent_event import AgentEvent, AgentEventState, AgentMode  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


def _event(*, critical: bool) -> AgentEvent:
    now = datetime.now(timezone.utc)
    return AgentEvent(
        "a" * 32,
        "safety" if critical else "comfort",
        "key",
        "HomeIntent",
        "Meldung",
        AgentMode.INFORM,
        AgentEventState.ACTIVE,
        now.isoformat(),
        now.isoformat(),
        (now + timedelta(hours=1)).isoformat(),
        safety_critical=critical,
    )


def test_quiet_hours_suppress_comfort_tts_but_never_critical_tts():
    hass = HomeAssistant()
    delivery = AgentDelivery(hass)
    options = {
        "agent_delivery_channels": ["tts"],
        "agent_tts_entity": "tts.piper",
        "agent_media_players": ["media_player.hall"],
        "agent_quiet_start": "00:00",
        "agent_quiet_end": "00:00",
    }
    comfort = asyncio.run(delivery.async_deliver(_event(critical=False), options))
    critical = asyncio.run(delivery.async_deliver(_event(critical=True), options))
    assert comfort.delivered_channels == ()
    assert critical.delivered_channels == ("tts",)
    hass.services.async_call.assert_awaited_once()
