"""Integration Wave (Migration Step 5): the 8 end-to-end test cases the
Integration Plan's user prompt specified verbatim, exercised through the
real ``NluConversationEntity._async_handle_message()`` orchestration - not
a second reimplementation of ``engine.match()``/``match_automation()``
(every other test file in this suite calls those directly; this file's job
is to prove the whole live pipeline, automation included, still behaves
correctly end-to-end).

Reuses ``tests/_ha_stub.py`` and the ``_make_entity``/``_run`` harness
pattern ``test_conversation_integration.py`` already established, plus the
entity fixtures ``test_command_followup.py`` and ``test_clarification.py``
already use for these exact sentences - Regel 6, no new test scaffolding
invented where an existing one already fits.

Case 6 ("Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht
ein.") doubles as a mock-assertion for the *first* turn of a spoken
automation: ``hass.services.async_call()`` is still never called on the
turn that only describes and previews an automation (V5.23/V5.26, "Dry
Run") - a real HA write only ever happens after an explicit "ja" reply on a
later turn (see ``test_conversation_automation_confirmation.py`` for that
full confirm/cancel/unclear round-trip).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

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
from homeassistant.helpers import intent  # noqa: E402

STUDIO_LIGHT = EntitySnapshot(
    "light.studio", "Studio", "light", "off",
    area_id="studio", area_name="Studio",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
WOHNZIMMER_LIGHT = EntitySnapshot(
    "light.wohnzimmerlicht", "Wohnzimmerlicht", "light", "off",
    area_id="wohnzimmer", area_name="Wohnzimmer",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
ESSZIMMER_FENSTER = EntitySnapshot(
    "binary_sensor.esszimmer_fenster", "Esszimmer Fenster", "binary_sensor", "on",
    area_id="esszimmer", area_name="Esszimmer", device_class="window",
)
WOHNZIMMER_FENSTER_OFFEN = EntitySnapshot(
    "binary_sensor.wohnzimmer_fenster", "Wohnzimmer Fenster", "binary_sensor", "on",
    area_id="wohnzimmer", area_name="Wohnzimmer", device_class="window",
)
KUECHE_FENSTER_ZU = EntitySnapshot(
    "binary_sensor.kueche_fenster", "Küchenfenster", "binary_sensor", "off",
    area_id="kueche", area_name="Küche", device_class="window",
)
KUECHE_LICHT = EntitySnapshot(
    "light.kueche_licht", "Küchenlicht", "light", "off",
    area_id="kueche", area_name="Küche",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
LIGHT_BUERO_1 = EntitySnapshot(
    "light.buerolicht_1", "Bürolicht", "light", "off",
    area_id="buero_1", area_name="Büro 1",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
LIGHT_BUERO_2 = EntitySnapshot(
    "light.buerolicht_2", "Bürolicht", "light", "off",
    area_id="buero_2", area_name="Büro 2",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)

ALL_ENTITIES = [
    STUDIO_LIGHT,
    WOHNZIMMER_LIGHT,
    ESSZIMMER_FENSTER,
    WOHNZIMMER_FENSTER_OFFEN,
    KUECHE_FENSTER_ZU,
    KUECHE_LICHT,
    LIGHT_BUERO_1,
    LIGHT_BUERO_2,
]


def _make_entity(monkeypatch) -> NluConversationEntity:
    entry = ConfigEntry()
    entity = NluConversationEntity(entry)
    entity.hass = HomeAssistant()
    monkeypatch.setattr(
        ha_conversation, "build_entity_snapshots", lambda hass, entry: ALL_ENTITIES
    )
    return entity


def _run(entity: NluConversationEntity, text: str, conversation_id: str = "conv-1"):
    user_input = ConversationInput(text=text, conversation_id=conversation_id)
    return asyncio.run(entity._async_handle_message(user_input, chat_log=None))


# --- Case 1/2: "Schalte das Studio ein." -> "Und jetzt wieder aus." -------


def test_case_1_studio_on(monkeypatch):
    entity = _make_entity(monkeypatch)
    result = _run(entity, "Schalte das Studio ein.", conversation_id="studio")

    entity.hass.services.async_call.assert_awaited_once()
    call_args = entity.hass.services.async_call.await_args
    assert call_args.args[1] == "turn_on"
    assert call_args.args[2]["entity_id"] == "light.studio"
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE


def test_case_2_studio_on_then_und_jetzt_wieder_aus(monkeypatch):
    entity = _make_entity(monkeypatch)
    _run(entity, "Schalte das Studio ein.", conversation_id="studio")
    entity.hass.services.async_call.reset_mock()

    result = _run(entity, "Und jetzt wieder aus.", conversation_id="studio")

    entity.hass.services.async_call.assert_awaited_once()
    call_args = entity.hass.services.async_call.await_args
    assert call_args.args[1] == "turn_off"
    assert call_args.args[2]["entity_id"] == "light.studio"
    assert result.response.error_code is None


# --- Case 3/4: "Welche Fenster sind offen?" -> "Und im Esszimmer?" --------


def test_case_3_welche_fenster_sind_offen(monkeypatch):
    entity = _make_entity(monkeypatch)
    result = _run(entity, "Welche Fenster sind offen?", conversation_id="fenster")

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.response_type == intent.IntentResponseType.QUERY_ANSWER
    assert "Esszimmer Fenster" in result.response.speech
    assert "Wohnzimmer Fenster" in result.response.speech


def test_case_4_und_im_esszimmer_area_filtered_followup(monkeypatch):
    entity = _make_entity(monkeypatch)
    _run(entity, "Welche Fenster sind offen?", conversation_id="fenster")

    result = _run(entity, "Und im Esszimmer?", conversation_id="fenster")

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.response_type == intent.IntentResponseType.QUERY_ANSWER
    assert "Esszimmer Fenster" in result.response.speech
    assert "Wohnzimmer Fenster" not in result.response.speech


# --- Case 5: "Mach das Wohnzimmerlicht an." -> "Mach es wieder aus." ------


def test_case_5_wohnzimmerlicht_on_then_mach_es_wieder_aus_same_target(monkeypatch):
    entity = _make_entity(monkeypatch)
    _run(entity, "Mach das Wohnzimmerlicht an.", conversation_id="wz")
    entity.hass.services.async_call.reset_mock()

    result = _run(entity, "Mach es wieder aus.", conversation_id="wz")

    entity.hass.services.async_call.assert_awaited_once()
    call_args = entity.hass.services.async_call.await_args
    assert call_args.args[1] == "turn_off"
    assert call_args.args[2]["entity_id"] == "light.wohnzimmerlicht"
    assert result.response.error_code is None


# --- Case 6: "Wenn das Küchenfenster geöffnet wird, schalte das ----------
# --- Küchenlicht ein." -> valid AutomationModel, spoken preview, never a --
# --- service call on this (the describing, not yet confirming) turn -----


def test_case_6_automation_sentence_never_calls_a_service(monkeypatch):
    entity = _make_entity(monkeypatch)

    result = _run(
        entity,
        "Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein.",
        conversation_id="automation",
    )

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.error_code is None
    assert "validation_error" not in result.response.speech
    assert "Automation erkannt" in result.response.speech
    assert "Soll diese Automation erstellt werden?" in result.response.speech


# --- Case 7: ambiguous target -> AMBIGUOUS (clarification, no guess) -----


def test_case_7_ambiguous_target_returns_clarification_not_a_guess(monkeypatch):
    entity = _make_entity(monkeypatch)

    result = _run(entity, "Mach das Bürolicht an", conversation_id="ambiguous")

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.error_code is None
    assert "mehrere passende Lichter" in result.response.speech
    assert "1. Bürolicht im Bereich Büro 1" in result.response.speech
    assert "2. Bürolicht im Bereich Büro 2" in result.response.speech


# --- Case 8: unresolvable reference -> NOT_FOUND (no prior context) ------


def test_case_8_unresolvable_reference_returns_not_understood(monkeypatch):
    entity = _make_entity(monkeypatch)

    # No prior turn on this conversation_id - "es" has nothing to resolve
    # against, and never guesses (Regel 4).
    result = _run(entity, "Mach es aus.", conversation_id="fresh")

    entity.hass.services.async_call.assert_not_awaited()
    assert result.response.error_code == intent.IntentResponseErrorCode.NO_INTENT_MATCH
