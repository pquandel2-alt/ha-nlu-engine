"""Extended direct-device routing and high-risk confirmation gates."""

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
from ha_nlu.const import SELECTABLE_DOMAINS  # noqa: E402
from ha_nlu.conversation import NluConversationEntity  # noqa: E402
from ha_nlu.device_control import match_device_control  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402

ENTITIES = [
    EntitySnapshot(
        "climate.heizung",
        "Wohnzimmer Heizung",
        "climate",
        "heat",
        attributes={
            "hvac_modes": ["heat", "cool"],
            "min_temp": 8,
            "max_temp": 28,
        },
    ),
    EntitySnapshot(
        "media_player.tv",
        "Wohnzimmer TV",
        "media_player",
        "idle",
        attributes={"source_list": ["HDMI 1", "Netflix"]},
    ),
    EntitySnapshot("vacuum.robi", "Saugroboter", "vacuum", "docked"),
    EntitySnapshot("scene.filmabend", "Filmabend", "scene", "scening"),
    EntitySnapshot("lock.haustuer", "Haustür", "lock", "locked"),
    EntitySnapshot(
        "cover.garage",
        "Garagentor",
        "cover",
        "closed",
        device_class="garage",
    ),
]


def test_climate_mode_is_checked_against_reported_modes():
    result = match_device_control(
        "Stelle Wohnzimmer Heizung auf Kühlbetrieb", ENTITIES
    )
    assert result.plan.service == "set_hvac_mode"
    assert result.plan.data == {"hvac_mode": "cool"}

    unsupported = match_device_control(
        "Stelle Wohnzimmer Heizung auf Automatik", ENTITIES
    )
    assert unsupported.plan is None
    assert "nicht" in unsupported.response_text


def test_climate_temperature_is_checked_against_reported_range():
    result = match_device_control(
        "Stelle Wohnzimmer Heizung auf 21,5 Grad", ENTITIES
    )
    assert result.plan.service == "set_temperature"
    assert result.plan.data == {"temperature": 21.5}

    unsupported = match_device_control(
        "Stelle Wohnzimmer Heizung auf 30 Grad", ENTITIES
    )
    assert unsupported.plan is None
    assert "zwischen 8 und 28" in unsupported.response_text


def test_media_playback_volume_and_source():
    play = match_device_control("Starte Wiedergabe auf Wohnzimmer TV", ENTITIES)
    volume = match_device_control(
        "Stelle die Lautstärke von Wohnzimmer TV auf 35 Prozent", ENTITIES
    )
    source = match_device_control(
        "Wähle auf Wohnzimmer TV die Quelle HDMI 1", ENTITIES
    )
    assert play.plan.service == "media_play"
    assert volume.plan.data == {"volume_level": 0.35}
    assert source.plan.data == {"source": "HDMI 1"}


def test_vacuum_and_scene_services_are_domain_native():
    vacuum = match_device_control("Schicke Saugroboter zur Ladestation", ENTITIES)
    scene = match_device_control("Aktiviere Szene Filmabend", ENTITIES)
    assert (vacuum.plan.domain, vacuum.plan.service) == ("vacuum", "return_to_base")
    assert (scene.plan.domain, scene.plan.service) == ("scene", "turn_on")


@pytest.mark.parametrize(
    ("sentence", "domain", "service", "data"),
    (
        ("Wohnzimmer Heizung bitte auf 22 Grad stellen", "climate", "set_temperature", {"temperature": 22.0}),
        ("Auf 35 Prozent bitte die Lautstärke vom Wohnzimmer TV stellen", "media_player", "volume_set", {"volume_level": 0.35}),
        ("Auf dem Wohnzimmer TV bitte die Wiedergabe starten", "media_player", "media_play", {}),
        ("Netflix als Quelle auf dem Wohnzimmer TV auswählen", "media_player", "select_source", {"source": "Netflix"}),
        ("Den Saugroboter bitte starten", "vacuum", "start", {}),
        ("Zur Ladestation soll der Saugroboter fahren", "vacuum", "return_to_base", {}),
        ("Filmabend bitte aktivieren", "scene", "turn_on", {}),
    ),
)
def test_extended_domain_slots_are_order_independent(sentence, domain, service, data):
    result = match_device_control(sentence, ENTITIES)

    assert result is not None
    assert result.plan is not None
    assert (result.plan.domain, result.plan.service) == (domain, service)
    assert result.plan.data == data


@pytest.mark.parametrize(
    "sentence",
    (
        "Wohnzimmer Heizung bitte nicht auf 22 Grad stellen",
        "Vielleicht den Saugroboter starten",
        "Filmabend normalerweise aktivieren",
    ),
)
def test_extended_domain_composition_rejects_unsafe_modifiers(sentence):
    assert match_device_control(sentence, ENTITIES) is None


def _conversation_entity(monkeypatch, tmp_path):
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    entity.hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    monkeypatch.setattr(
        ha_conversation, "build_entity_snapshots", lambda hass, entry: ENTITIES
    )
    return entity


def _run(entity, text, conversation_id="safe"):
    return asyncio.run(
        entity._async_handle_message(
            ConversationInput(text=text, conversation_id=conversation_id),
            chat_log=None,
        )
    )


def test_unlock_requires_explicit_confirmation(monkeypatch, tmp_path):
    entity = _conversation_entity(monkeypatch, tmp_path)

    preview = _run(entity, "Schließe Haustür auf")
    assert "wirklich" in preview.response.speech
    entity.hass.services.async_call.assert_not_awaited()

    confirmed = _run(entity, "Ja")
    assert "aufschließen" in confirmed.response.speech
    entity.hass.services.async_call.assert_awaited_once_with(
        "lock", "unlock", {"entity_id": "lock.haustuer"}, blocking=True
    )


def test_garage_movement_can_be_cancelled(monkeypatch, tmp_path):
    entity = _conversation_entity(monkeypatch, tmp_path)
    preview = _run(entity, "Öffne Garagentor")
    assert "wirklich" in preview.response.speech

    cancelled = _run(entity, "Nein")
    assert "Abgebrochen" in cancelled.response.speech
    entity.hass.services.async_call.assert_not_awaited()


def test_every_extended_domain_is_selectable_in_live_home_assistant():
    assert {"climate", "media_player", "vacuum", "scene", "lock", "calendar"} <= set(
        SELECTABLE_DOMAINS
    )
