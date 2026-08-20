"""Automation Executor (HomeIntent V5 Teil 7/10, V5.26): the sole
persistence path from a confirmed ``AutomationModel`` into a real Home
Assistant automation - kept structurally and physically separate from
``conversation.py``'s existing command-execution code (``hass.services.
async_call()`` for TURN_ON/TURN_OFF/etc. plans), since writing
``automations.yaml`` is a categorically different, far harder to reverse
action than a single service call (see ``context.py``'s
``PendingAutomationConfirmation`` docstring: "the single most hard-to-
reverse action anywhere in this engine").

Mirrors the exact read-modify-write Home Assistant's own
``EditAutomationConfigView._write_value`` (upstream ``homeassistant/
components/config/automation.py``) performs when a user edits an automation
through the UI - same file, same YAML dump, same atomic write, same reload
call - so an automation created this way is indistinguishable from one a
human created by hand through the UI editor. Only ``config/automation.py``'s
own service-data shape for the plain, no-argument ``automation.reload``
service call is used (Regel 4: no invented ``id``-scoped reload variant -
the always-correct, fully-verified call reloads every automation from disk,
including the one just appended).

Takes a already-``generate_ha_automation_config()``-clean config dict as
input - no re-validation, no re-generation, purely the disk/service-call
side effect (same "purely renders/persists whatever it is given" division
of labor ``automation_preview.py``'s ``render_automation_preview()`` and
``ha_automation_generator.py`` already establish one stage earlier each).

Lives at the top level of ``custom_components/ha_nlu/``, not inside
``nlu/``: every module in ``nlu/`` (``ha_automation_generator.py`` included)
deliberately stays hass-free, and this module's entire job is real
``homeassistant.core``/``homeassistant.util`` I/O - same layering precedent
``hass_entities.py`` already sets for "real HA access lives one package
level up from the pure NLU code".
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import yaml as yaml_util
from homeassistant.util.file import write_utf8_file_atomic

AUTOMATIONS_YAML_FILENAME = "automations.yaml"


class AutomationExecutor:
    """One instance per config entry (same lifetime/ownership as
    ``NluEngine``/``ConversationContextStore`` on ``NluConversationEntity``),
    owning the ``asyncio.Lock()`` that guards ``automations.yaml``'s
    read-modify-write cycle against two concurrent confirmations racing each
    other - a module-level lock would leak across config entries/tests, an
    instance-level one matches every other piece of this integration's own
    per-entry state.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._lock = asyncio.Lock()

    async def async_create_automation(self, config: dict[str, Any]) -> str:
        """Appends ``config`` (a ``GenerationResult.config`` dict, no ``id``
        key yet - see ``ha_automation_generator.py``'s ``GenerationResult``
        docstring) as a new automation, persists it to ``automations.yaml``,
        and reloads the automation integration so it takes effect
        immediately - the same three steps Home Assistant's own
        config/automation UI editor performs. Returns the freshly assigned
        automation id.

        File I/O runs off the event loop via ``hass.async_add_executor_job``
        (``load_yaml``/``write_utf8_file_atomic`` are both blocking calls),
        same as every other filesystem-touching HA core code path.
        """
        automation_id = uuid.uuid4().hex
        path = self._hass.config.path(AUTOMATIONS_YAML_FILENAME)
        async with self._lock:
            automations = await self._hass.async_add_executor_job(self._read_automations, path)
            automations.append({"id": automation_id, **config})
            await self._hass.async_add_executor_job(self._write_automations, path, automations)
        await self._hass.services.async_call("automation", "reload", {}, blocking=True)
        return automation_id

    @staticmethod
    def _read_automations(path: str) -> list[dict[str, Any]]:
        """Mirrors upstream ``config/automation.py``'s own ``_read()``
        helper: a not-yet-existing ``automations.yaml`` (a fresh HA install
        that never created one) is an empty automation list, not an error."""
        try:
            content = yaml_util.load_yaml(path)
        except FileNotFoundError:
            return []
        return content if content else []

    @staticmethod
    def _write_automations(path: str, automations: list[dict[str, Any]]) -> None:
        write_utf8_file_atomic(path, yaml_util.dump(automations))
