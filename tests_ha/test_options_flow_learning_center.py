"""Realistic regression scenario on a REAL Home Assistant:

Settings -> Devices & Services -> HomeIntent -> Configure opens, the five
learning/proactive switches are enabled and saved, HomeIntent reloads, and
the Learning Center (sidebar panel, summary, Autonomy tab) reports the new
states. Guards the 7.1.1 options flow fix against regressing the 7.1
Learning Center.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homeintent.const import (
    CONF_EXPERIENCE_LEARNING_ENABLED,
    CONF_HABIT_DISCOVERY_ENABLED,
    CONF_PREDICTIVE_MODELS_ENABLED,
    CONF_PROACTIVE_CONTEXT_ENABLED,
    CONF_PROACTIVE_SUGGESTIONS_ENABLED,
    DOMAIN,
)

from .test_options_flow import SETUP_OPTIONS, _open_configure, _submit

PREFIX = "homeintent/learning_center"


async def _setup_homeintent(hass: HomeAssistant) -> MockConfigEntry:
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "config", {})
    entry = MockConfigEntry(domain=DOMAIN, title="HomeIntent", data={}, options=dict(SETUP_OPTIONS))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def _ws(client: Any, command: str, **payload: Any) -> dict[str, Any]:
    await client.send_json_auto_id({"type": f"{PREFIX}/{command}", **payload})
    msg = await client.receive_json()
    assert msg["success"], msg
    return msg["result"]


async def _features(client: Any) -> dict[str, Any]:
    summary = await _ws(client, "summary")
    return summary["features"]


async def test_configure_enable_learning_then_learning_center_reflects_it(
    hass: HomeAssistant, hass_client, hass_ws_client
) -> None:
    entry = await _setup_homeintent(hass)
    client = await hass_client()

    # Sidebar panel + its module are served.
    panels = hass.data["frontend_panels"]
    assert DOMAIN in panels
    module_url = panels[DOMAIN].config["_panel_custom"]["module_url"]
    resp = await client.get(module_url)
    assert resp.status == HTTPStatus.OK

    ws = await hass_ws_client(hass)
    entries = await _ws(ws, "entries")
    assert [item["entry_id"] for item in entries["entries"]] == [entry.entry_id]
    before = await _features(ws)
    assert before["learning_enabled"] is False
    assert before["proactive_enabled"] is False

    # Settings -> Devices & Services -> HomeIntent -> Configure, enable, Save.
    data = await _open_configure(hass, client, entry)
    result = await _submit(client, data, {
        CONF_EXPERIENCE_LEARNING_ENABLED: True,
        CONF_PREDICTIVE_MODELS_ENABLED: True,
        CONF_HABIT_DISCOVERY_ENABLED: True,
        CONF_PROACTIVE_SUGGESTIONS_ENABLED: True,
        CONF_PROACTIVE_CONTEXT_ENABLED: True,
    })
    assert result["type"] == "create_entry", result
    # HomeIntent's update listener reloads the entry.
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    for key in (CONF_EXPERIENCE_LEARNING_ENABLED, CONF_PREDICTIVE_MODELS_ENABLED,
                CONF_HABIT_DISCOVERY_ENABLED, CONF_PROACTIVE_SUGGESTIONS_ENABLED,
                CONF_PROACTIVE_CONTEXT_ENABLED):
        assert entry.options[key] is True, key

    # Learning Center summary (overview tab) reflects the saved options.
    summary = await _ws(ws, "summary")
    features = summary["features"]
    assert features["learning_enabled"] is True
    assert features["learning_mode"] != "off"
    assert features["predictive_models_enabled"] is True
    assert features["habit_discovery_enabled"] is True
    assert features["suggestions_enabled"] is True
    assert features["proactive_enabled"] is True

    # Autonomy tab loads (permissions + mutes) with the same feature state.
    permissions = await _ws(ws, "permissions/list")
    mutes = await _ws(ws, "mutes/list")
    assert isinstance(permissions["permissions"], list)
    assert isinstance(mutes["mutes"], list)
    assert permissions["features"]["proactive_enabled"] is True
    assert permissions["features"]["learning_enabled"] is True

    # Panel still registered after the reload.
    assert DOMAIN in hass.data["frontend_panels"]

    # Configure still opens on the reloaded entry and shows the saved values.
    reopened = await _open_configure(hass, client, entry)
    fields = {field["name"]: field for field in reopened["data_schema"]}
    assert fields[CONF_EXPERIENCE_LEARNING_ENABLED]["default"] is True
    assert fields[CONF_PROACTIVE_CONTEXT_ENABLED]["default"] is True
