"""Automation Executor (HomeIntent V5 Teil 7/10 + Teil 8/10 - V5.26, V5.35,
V5.36): the sole persistence path from a confirmed ``AutomationModel`` into
a real Home Assistant automation - kept structurally and physically
separate from ``conversation.py``'s existing command-execution code
(``hass.services.async_call()`` for TURN_ON/TURN_OFF/etc. plans), since
writing ``automations.yaml`` is a categorically different, far harder to
reverse action than a single service call (see ``context.py``'s
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

V5.35 (Automation Transactions)/V5.36 (Rollback): the whole
write-reload-record_metadata sequence runs under one lock as a single
unit - if the reload or the metadata write fails partway through, the
YAML change is rolled back (and, if it was the metadata step that failed,
HA is reloaded a second time to make its live state match the rolled-back
file) before the exception propagates. Before this wave, a reload failure
left a silently orphaned entry in ``automations.yaml`` - the file said the
automation existed even though the user was told creation failed and HA
itself may never have picked it up. "No half-created automations" (the
plan's own V5.36 wording) means the file must never disagree with what the
user was actually told.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import yaml as yaml_util
from homeassistant.util.file import write_utf8_file_atomic

from .automation_metadata_store import AutomationMetadata, AutomationMetadataStore, utcnow_isoformat
from .automation_summary import AutomationSummary

AUTOMATIONS_YAML_FILENAME = "automations.yaml"


def _collect_entity_ids(value: Any) -> set[str]:
    """Every ``entity_id`` value found anywhere in ``value`` (a raw
    automation config dict/list node) - deliberately shape-blind (walks
    every dict/list node instead of hand-enumerating known trigger/
    condition/action shapes), since automation YAML has enough structural
    variety (single trigger dict vs. list of triggers, service-call target
    blocks, nested conditions) that enumerating every shape risks silently
    missing one. See ``AutomationSummary``'s own docstring for why this
    shallow "mentions X somewhere" collection - not a re-derivation of
    trigger/condition/action semantics - is enough for V5.29's scope.
    """
    found: set[str] = set()
    if isinstance(value, dict):
        for key, val in value.items():
            if key == "entity_id":
                if isinstance(val, str):
                    found.add(val)
                elif isinstance(val, list):
                    found.update(v for v in val if isinstance(v, str))
            else:
                found.update(_collect_entity_ids(val))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_entity_ids(item))
    return found


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
        self._metadata_store = AutomationMetadataStore(hass)

    async def async_create_automation(self, config: dict[str, Any]) -> str:
        """Appends ``config`` (a ``GenerationResult.config`` dict, no ``id``
        key yet - see ``ha_automation_generator.py``'s ``GenerationResult``
        docstring) as a new automation, persists it to ``automations.yaml``,
        reloads the automation integration so it takes effect immediately,
        and records its identity/metadata (V5.30/V5.31) in the sidecar
        store - the same three HA-facing steps Home Assistant's own
        config/automation UI editor performs, plus this integration's own
        bookkeeping. Returns the freshly assigned automation id.

        Every step runs inside the same lock, and a failure at the reload or
        metadata step rolls the YAML file back to what it was before this
        call (V5.35/V5.36) - either every step succeeds and all three pieces
        of state (file, HA's live config, metadata) agree, or none of them
        change.

        File I/O runs off the event loop via ``hass.async_add_executor_job``
        (``load_yaml``/``write_utf8_file_atomic`` are both blocking calls),
        same as every other filesystem-touching HA core code path.
        """
        automation_id = uuid.uuid4().hex
        path = self._hass.config.path(AUTOMATIONS_YAML_FILENAME)
        async with self._lock:
            original_automations = await self._hass.async_add_executor_job(self._read_automations, path)
            automations = [*original_automations, {"id": automation_id, **config}]
            await self._hass.async_add_executor_job(self._write_automations, path, automations)

            try:
                await self._hass.services.async_call("automation", "reload", {}, blocking=True)
            except Exception:
                await self._hass.async_add_executor_job(
                    self._write_automations, path, original_automations
                )
                raise

            metadata = AutomationMetadata(
                automation_id=automation_id,
                source_text=config.get("alias", ""),
                created_at=utcnow_isoformat(),
            )
            try:
                await self._metadata_store.async_save(metadata)
            except Exception:
                await self._hass.async_add_executor_job(
                    self._write_automations, path, original_automations
                )
                # Best-effort: HA's live config should reflect the rollback
                # too, but a second reload failure must not mask the
                # original metadata error, which is what actually caused
                # this rollback - the file is already correct either way.
                try:
                    await self._hass.services.async_call("automation", "reload", {}, blocking=True)
                except Exception:  # noqa: BLE001 - see comment above
                    pass
                raise

        return automation_id

    async def async_list_automations(self) -> tuple[AutomationSummary, ...]:
        """V5.29 (Automation Query): a read-only survey of every automation
        currently in ``automations.yaml``, cross-referenced against the
        metadata sidecar - the read half of this class's job, mirroring
        ``async_create_automation``'s write half but with none of its
        locking (nothing here writes, so concurrent reads never race each
        other or a write; a read started just before a concurrent
        ``async_create_automation`` simply may or may not see the new
        automation yet, the same eventually-consistent guarantee any other
        read of live HA state already has - see ``matches_semantic_state``'s
        "never cached" precedent for entity state).

        Callers gate this behind a cheap sentence pre-check first (see
        ``engine.py``'s ``_AUTOMATION_QUERY_RE``) - reading and parsing
        ``automations.yaml`` on every single conversation turn regardless of
        its content would be real, unnecessary per-turn I/O cost.
        """
        path = self._hass.config.path(AUTOMATIONS_YAML_FILENAME)
        automations = await self._hass.async_add_executor_job(self._read_automations, path)
        metadata = await self._metadata_store.async_load_all()

        summaries = []
        for automation in automations:
            automation_id = automation.get("id", "")
            entry = metadata.get(automation_id)
            summaries.append(
                AutomationSummary(
                    automation_id=automation_id,
                    alias=automation.get("alias", ""),
                    source_text=entry.get("source_text") if entry else None,
                    created_by=entry.get("created_by") if entry else None,
                    referenced_entity_ids=frozenset(_collect_entity_ids(automation)),
                )
            )
        return tuple(summaries)

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
