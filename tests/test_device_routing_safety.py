"""R3 regression tests through the real pre-engine conversation router."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import ha_nlu.conversation as ha_conversation  # noqa: E402
from ha_nlu.conversation import NluConversationEntity  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


ENTITIES = [
    EntitySnapshot(
        "media_player.radio", "Radio", "media_player", "playing",
        area_id="kueche", area_name="Küche",
    ),
    EntitySnapshot(
        "vacuum.robi", "Saugroboter", "vacuum", "docked",
        area_id="flur", area_name="Flur",
    ),
    EntitySnapshot(
        "light.kueche", "Küchenlicht", "light", "on",
        area_id="kueche", area_name="Küche",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "light.flur", "Flurlicht", "light", "off",
        area_id="flur", area_name="Flur",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
]


def _agent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> NluConversationEntity:
    agent = NluConversationEntity(ConfigEntry())
    agent.hass = HomeAssistant()
    agent.hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    monkeypatch.setattr(
        ha_conversation, "build_entity_snapshots", lambda hass, entry: ENTITIES
    )
    return agent


def _run(agent: NluConversationEntity, text: str):
    return asyncio.run(
        agent._async_handle_message(
            ConversationInput(text=text, conversation_id="r3"), chat_log=None
        )
    )


@pytest.mark.parametrize(
    "question",
    (
        "Soll ich das Radio stumm schalten?",
        "Soll ich den Saugroboter suchen?",
        "War das Radio stumm?",
        "Muss ich den Saugroboter suchen?",
        "Wollen wir das Radio stumm schalten?",
        "Ich frage mich, ob das Radio stumm ist",
        "Soll ich den Ton beim Radio wieder anmachen?",
    ),
)
def test_questions_never_reach_a_device_service_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, question: str
) -> None:
    agent = _agent(monkeypatch, tmp_path)

    _run(agent, question)

    agent.hass.services.async_call.assert_not_awaited()


@pytest.mark.parametrize(
    ("command", "service"),
    (
        ("Schalte das Radio stumm", "volume_mute"),
        ("Mach das Radio stumm", "volume_mute"),
        ("Finde den Saugroboter", "locate"),
    ),
)
def test_explicit_device_commands_still_execute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str, service: str
) -> None:
    agent = _agent(monkeypatch, tmp_path)

    _run(agent, command)

    assert agent.hass.services.async_call.await_args.args[1] == service


@pytest.mark.parametrize(
    "question",
    ("Wo ist der Saugroboter?", "Wo ist das Radio?", "Wo sind die Lichter?"),
)
def test_location_questions_return_speech_without_crashing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, question: str
) -> None:
    result = _run(_agent(monkeypatch, tmp_path), question)

    assert result.response.speech
