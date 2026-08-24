from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import ha_nlu.conversation as ha_conversation  # noqa: E402
from ha_nlu.automation_wizard import parse_lifetime, starts_automation_wizard  # noqa: E402
from ha_nlu.conversation import NluConversationEntity  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


WINDOW = EntitySnapshot(
    "binary_sensor.kueche_fenster", "Küchenfenster", "binary_sensor", "off",
    area_id="kueche", area_name="Küche", device_class="window",
)
LIGHT = EntitySnapshot(
    "light.kueche", "Küchenlicht", "light", "off",
    area_id="kueche", area_name="Küche",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
PERSON = EntitySnapshot("person.philipp", "Philipp", "person", "home")


def _agent(monkeypatch):
    agent = NluConversationEntity(ConfigEntry())
    agent.hass = HomeAssistant()
    monkeypatch.setattr(
        ha_conversation, "build_entity_snapshots",
        lambda hass, entry: [WINDOW, LIGHT, PERSON],
    )
    return agent


def _run(agent, text, cid="wizard"):
    return asyncio.run(agent._async_handle_message(
        ConversationInput(text=text, conversation_id=cid), chat_log=None
    ))


def test_wizard_start_and_lifetime_are_bounded():
    assert starts_automation_wizard("Erstelle eine neue Automation")
    assert parse_lifetime("dauerhaft") == (False, None)
    assert parse_lifetime("nur dreimal") == (False, 3)
    assert parse_lifetime("einmalig") == (True, None)


def test_complete_automation_can_be_composed_over_multiple_turns(monkeypatch):
    agent = _agent(monkeypatch)
    start = _run(agent, "Erstelle eine neue Automation")
    trigger = _run(agent, "Wenn das Küchenfenster geöffnet wird")
    decision = _run(agent, "ja")
    condition = _run(agent, "nur wenn jemand zuhause ist")
    action = _run(agent, "Schalte das Küchenlicht ein")
    preview = _run(agent, "dauerhaft")

    assert "Was soll die Automation auslösen" in start.response.speech
    assert "Bedingung" in trigger.response.speech
    assert "Welche Bedingung" in decision.response.speech
    assert "Was soll dann passieren" in condition.response.speech
    assert "dauerhaft" in action.response.speech
    assert "Automation erkannt" in preview.response.speech
    pending = agent._context_store.get("wizard")
    assert pending.pending_automation_confirmation is not None
    model = pending.pending_automation_confirmation.model
    assert len(model.triggers) == len(model.conditions) == len(model.actions) == 1


def test_wizard_can_be_cancelled_without_service_call(monkeypatch):
    agent = _agent(monkeypatch)
    _run(agent, "Erstelle eine Automation", "cancel")
    result = _run(agent, "Abbrechen", "cancel")
    assert "verworfen" in result.response.speech
    assert agent._context_store.get("cancel") is None
    agent.hass.services.async_call.assert_not_awaited()
