"""Automation Metadata Store (HomeIntent V5 Teil 8/10, V5.30/V5.31/V5.32):
per-automation identity/metadata for automations this integration created,
kept in a sidecar JSON file physically separate from ``automations.yaml``.

Cannot live as extra keys on the automation dict itself (the obvious first
idea): confirmed against the real upstream source
(``homeassistant/components/automation/config.py``'s ``PLATFORM_SCHEMA``,
built via ``script.make_script_schema({...}, script.SCRIPT_MODE_SINGLE)``
in ``homeassistant/helpers/script.py``) that this schema is built with its
default ``extra=vol.PREVENT_EXTRA`` - no ``extra=vol.ALLOW_EXTRA`` override
anywhere on that call path. An unrecognized top-level key on an automation
config makes ``PLATFORM_SCHEMA(config)`` raise ``vol.Invalid``, and Home
Assistant disables that automation with ``ValidationStatus.FAILED_SCHEMA``
instead of loading it - the exact "silently do something wrong" outcome
Regel 4 exists to prevent. A sidecar file is therefore not a stylistic
choice but the only way to attach metadata without risking every automation
this integration creates failing to load.

Same physical-separation precedent ``automation_executor.py``'s own
docstring already sets one layer up (that module's job is real HA I/O
kept out of ``nlu/``; this module's job is metadata kept out of the
schema-governed ``automations.yaml`` HA itself owns and validates).

V5.32 (Automation Versioning) only needs a ``version`` field to exist and
start at 1 today - there is no V5.27 (Automation Modification) yet to ever
write anything but 1, so incrementing it is future work, not simulated
here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.file import write_utf8_file_atomic

METADATA_FILENAME = "ha_nlu_automation_metadata.json"

# The only value this integration itself ever writes - a future V5.29
# (Automation Query) needs to tell "created by HomeIntent" apart from
# "created by hand in the UI", which is exactly what ``created_by`` records.
CREATED_BY_HOMEINTENT = "homeintent"

# v1 intent YAMLs are German-only (see ``conversation.py``'s own
# ``supported_languages`` property) - no language-detection mechanism
# exists anywhere in this project, so this is the one truthful value,
# not an invented default.
SOURCE_LANGUAGE_DE = "de"


@dataclass(frozen=True)
class AutomationMetadata:
    """One entry in the sidecar store, keyed by ``automation_id`` (the same
    id ``AutomationExecutor`` assigns as the automation's ``id`` field in
    ``automations.yaml`` - Regel 6: one identity, not a second parallel id
    scheme). ``created_at`` is an ISO 8601 UTC timestamp string (JSON has no
    native datetime type)."""

    automation_id: str
    source_text: str
    created_at: str
    created_by: str = CREATED_BY_HOMEINTENT
    version: int = 1
    source_language: str = SOURCE_LANGUAGE_DE


class AutomationMetadataStore:
    """Owned exclusively by ``AutomationExecutor`` (private collaborator, not
    a second top-level entry point conversation.py talks to directly) -
    mirrors that class's own instance-level ``asyncio.Lock()`` precedent so
    two concurrent creations can't race each other's read-modify-write of
    the metadata file either.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def async_save(self, metadata: AutomationMetadata) -> None:
        """Adds or overwrites ``metadata``'s entry, keyed by its
        ``automation_id``. Must be called under the caller's own lock (the
        same lock guarding the paired ``automations.yaml`` write) - this
        method has no lock of its own, since it must never be interleaved
        with the automation-file half of the same transaction."""
        path = self._hass.config.path(METADATA_FILENAME)
        entries = await self._hass.async_add_executor_job(self._read, path)
        entries[metadata.automation_id] = asdict(metadata)
        await self._hass.async_add_executor_job(self._write, path, entries)

    async def async_delete(self, automation_id: str) -> None:
        """Removes ``automation_id``'s entry if present - a no-op otherwise
        (rollback calling this for an id whose metadata write never
        succeeded must not itself raise)."""
        path = self._hass.config.path(METADATA_FILENAME)
        entries = await self._hass.async_add_executor_job(self._read, path)
        if automation_id in entries:
            del entries[automation_id]
            await self._hass.async_add_executor_job(self._write, path, entries)

    @staticmethod
    def _read(path: str) -> dict[str, Any]:
        try:
            with open(path, encoding="utf-8") as handle:
                content = json.load(handle)
        except FileNotFoundError:
            return {}
        return content if content else {}

    @staticmethod
    def _write(path: str, entries: dict[str, Any]) -> None:
        write_utf8_file_atomic(path, json.dumps(entries, ensure_ascii=False, indent=2))


def utcnow_isoformat() -> str:
    """Small wrapper so ``AutomationExecutor`` doesn't need its own
    ``dt_util`` import just for this one call site."""
    return dt_util.utcnow().isoformat()
