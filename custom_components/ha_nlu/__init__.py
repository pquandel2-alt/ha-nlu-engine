"""The ha_nlu integration: a deterministic, LLM-free Assist conversation agent.

Setup only forwards to the ``conversation`` platform - all matching logic
lives in ``engine.py``/``entities.py``/``service_call.py`` and is loaded
lazily by ``NluConversationEntity`` itself.

Generated one-shot and run-limited automations use the internal services
``ha_nlu.delete_automation`` and ``ha_nlu.record_automation_run``. They exist
so an automation can complete its own lifecycle; users manage automations
through the conversation agent rather than raw automation ids.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .const import (
    CONF_CONTEXT_TTL_SECONDS,
    CONF_DOCUMENTS_DIRECTORY,
    CONF_DOCUMENTS_ENABLED,
    CONF_MEMORY_ENABLED,
    CONF_MEMORY_RETENTION_DAYS,
    DOMAIN,
)
from .memory import MemoryKind, MemoryStore
from .nlu.context import ConversationContextStore
from .runtime_data import HaNluRuntimeData

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall

PLATFORMS = ["conversation"]

_LOGGER = logging.getLogger(__name__)

SERVICE_DELETE_AUTOMATION = "delete_automation"
SERVICE_RECORD_AUTOMATION_RUN = "record_automation_run"
SERVICE_ENABLE_AUTOMATION = "enable_automation"
SERVICE_PROACTIVE_MESSAGE = "proactive_message"
SERVICE_RECHECK_AGENT_EVENT = "recheck_agent_event"

# A self-deleting automation must finish the service action that requested
# its deletion before ``automation.reload`` removes/unloads that automation.
# Without this grace period the reload waits for the running action script,
# while that script waits for this service handler: a circular wait.
SELF_DELETE_GRACE_SECONDS = 0.1
SELF_DELETE_RETRY_SECONDS = (1.0, 5.0)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    configured_ttl = entry.options.get(CONF_CONTEXT_TTL_SECONDS, 30)
    context_ttl = (
        float(configured_ttl)
        if isinstance(configured_ttl, (int, float)) and configured_ttl >= 10
        else 30.0
    )
    configured_retention = entry.options.get(CONF_MEMORY_RETENTION_DAYS, 90)
    retention_days = (
        configured_retention
        if isinstance(configured_retention, int) and configured_retention >= 1
        else 90
    )
    memory = MemoryStore(
        hass.config.path(".storage", "ha_nlu_memory.sqlite3"),
        enabled=bool(entry.options.get(CONF_MEMORY_ENABLED, False)),
        retention_days=retention_days,
    )
    entry.runtime_data = HaNluRuntimeData(
        context_store=ConversationContextStore(ttl_seconds=context_ttl),
        memory=memory,
    )
    await memory.async_initialize()
    if memory.enabled:
        await memory.async_apply_retention(
            {kind: retention_days for kind in MemoryKind}
        )
    if bool(entry.options.get(CONF_DOCUMENTS_ENABLED, False)):
        from pathlib import Path

        from .adapters import LocalDocumentIndex

        configured_directory = entry.options.get(
            CONF_DOCUMENTS_DIRECTORY, "homeintent_documents"
        )
        relative = (
            Path(configured_directory)
            if isinstance(configured_directory, str)
            else Path("homeintent_documents")
        )
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or str(relative) in {"", "."}
        ):
            _LOGGER.warning("HomeIntent document directory must stay below the HA config directory")
        else:
            document_index = LocalDocumentIndex(
                hass.config.path(*relative.parts),
                hass.config.path(".storage", "ha_nlu_documents.sqlite3"),
                enabled=True,
            )
            entry.runtime_data.document_index = document_index
            indexing_task = hass.async_create_task(
                document_index.async_reindex(),
                name="HomeIntent local document indexing",
            )
            entry.async_on_unload(indexing_task.cancel)
    from .agent_runtime import ProactiveAgentRuntime

    proactive_agent = ProactiveAgentRuntime(hass, entry, entry.runtime_data)
    entry.runtime_data.proactive_agent = proactive_agent
    entry.async_on_unload(proactive_agent.async_start())
    from .event_runtime import SituationRuntime

    situation_runtime = SituationRuntime(hass, entry, entry.runtime_data)
    entry.runtime_data.situation_runtime = situation_runtime
    entry.async_on_unload(situation_runtime.async_start())
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Single-instance-only integration (config_flow.py's own
    # ``_async_abort_entries_match({})``) - guarded anyway so a second
    # ``async_setup_entry`` call (e.g. re-added after a full removal) never
    # raises on an already-registered service.
    if not hass.services.has_service(DOMAIN, SERVICE_DELETE_AUTOMATION):

        async def _handle_delete_automation(call: ServiceCall) -> None:
            automation_id = _automation_id_from_call(call)
            if automation_id is None:
                return
            # Do not await the delete here. This handler is itself the last
            # action of the automation being deleted. Returning lets that
            # action script finish before the background task reloads HA's
            # automation component and unloads it.
            hass.async_create_task(
                _async_delete_automation_after_action(hass, automation_id),
                name=f"HomeIntent self-delete automation {automation_id}",
            )

        hass.services.async_register(DOMAIN, SERVICE_DELETE_AUTOMATION, _handle_delete_automation)

    if not hass.services.has_service(DOMAIN, SERVICE_RECORD_AUTOMATION_RUN):

        async def _handle_record_automation_run(call: ServiceCall) -> None:
            automation_id = _automation_id_from_call(call)
            if automation_id is None:
                return
            hass.async_create_task(
                _async_record_automation_run_after_action(hass, automation_id),
                name=f"HomeIntent record automation run {automation_id}",
            )

        hass.services.async_register(
            DOMAIN, SERVICE_RECORD_AUTOMATION_RUN, _handle_record_automation_run
        )

    if not hass.services.has_service(DOMAIN, SERVICE_ENABLE_AUTOMATION):

        async def _handle_enable_automation(call: ServiceCall) -> None:
            automation_id = _automation_id_from_call(call)
            if automation_id is None:
                return
            hass.async_create_task(
                _async_enable_automation_after_action(hass, automation_id),
                name=f"HomeIntent resume automation {automation_id}",
            )

        hass.services.async_register(
            DOMAIN, SERVICE_ENABLE_AUTOMATION, _handle_enable_automation
        )

    if not hass.services.has_service(DOMAIN, SERVICE_PROACTIVE_MESSAGE):

        async def _handle_proactive_message(call: ServiceCall) -> None:
            try:
                await proactive_agent.async_signal(call.data)
            except ValueError as err:
                _LOGGER.warning("Invalid proactive message request: %s", err)

        hass.services.async_register(
            DOMAIN, SERVICE_PROACTIVE_MESSAGE, _handle_proactive_message
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RECHECK_AGENT_EVENT):

        async def _handle_recheck_agent_event(call: ServiceCall) -> None:
            event_id = call.data.get("event_id")
            if isinstance(event_id, str):
                await proactive_agent.async_recheck(event_id)

        hass.services.async_register(
            DOMAIN, SERVICE_RECHECK_AGENT_EVENT, _handle_recheck_agent_event
        )

    # Reconcile persistence before expiring missed one-shots. This recovers
    # a crash-interrupted transaction, removes orphan sidecar metadata and
    # repairs category assignments for every known HomeIntent automation.
    if hass.services.has_service("automation", "reload"):
        hass.async_create_task(
            _async_reconcile_and_cleanup_automations(hass),
            name="HomeIntent reconcile automation persistence",
        )
    # Recovery is a bounded atomic sidecar read and must finish before an
    # incoming notification action can address a persisted event.
    await proactive_agent.async_recover()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and hass.services.has_service(DOMAIN, SERVICE_DELETE_AUTOMATION):
        hass.services.async_remove(DOMAIN, SERVICE_DELETE_AUTOMATION)
    if unloaded and hass.services.has_service(DOMAIN, SERVICE_RECORD_AUTOMATION_RUN):
        hass.services.async_remove(DOMAIN, SERVICE_RECORD_AUTOMATION_RUN)
    if unloaded and hass.services.has_service(DOMAIN, SERVICE_ENABLE_AUTOMATION):
        hass.services.async_remove(DOMAIN, SERVICE_ENABLE_AUTOMATION)
    if unloaded and hass.services.has_service(DOMAIN, SERVICE_PROACTIVE_MESSAGE):
        hass.services.async_remove(DOMAIN, SERVICE_PROACTIVE_MESSAGE)
    if unloaded and hass.services.has_service(DOMAIN, SERVICE_RECHECK_AGENT_EVENT):
        hass.services.async_remove(DOMAIN, SERVICE_RECHECK_AGENT_EVENT)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_delete_automation(hass: HomeAssistant, call: ServiceCall) -> None:
    """Deletes the automation named by ``call.data["automation_id"]`` -
    reuses ``AutomationExecutor.async_delete_automation()`` (Wave 10)
    verbatim (Regel 6), rather than a second, parallel deletion mechanism.

    Manual validation (no voluptuous schema): ``vol``/``config_validation``
    aren't exercised anywhere else in this codebase's test suite (only
    imported, untested, by ``config_flow.py``) - keeping this handler pure
    Python keeps it directly testable the same way the rest of this
    integration already is.

    A fresh ``AutomationExecutor`` is created per call rather than sharing
    the conversation entity's own instance. Executor instances belonging to
    the same Home Assistant instance share their mutation lock and additionally
    protect the file with optimistic fingerprint checks.

    Swallows the documented ``ValueError`` race (see
    ``async_delete_automation``'s own docstring): if the automation was
    already deleted by something else between generation and this call
    firing, there is nothing left to do.
    """
    automation_id = _automation_id_from_call(call)
    if automation_id is None:
        return
    await _async_delete_automation_by_id(hass, automation_id)


def _automation_id_from_call(call: ServiceCall) -> str | None:
    """Return a validated automation id from the custom service call."""
    automation_id = call.data.get("automation_id")
    if not isinstance(automation_id, str) or not automation_id:
        _LOGGER.warning("ha_nlu.delete_automation called without a valid automation_id: %r", automation_id)
        return None
    return automation_id


async def _async_delete_automation_after_action(
    hass: HomeAssistant, automation_id: str
) -> None:
    """Delete after the calling automation has left its final action."""
    delays = (SELF_DELETE_GRACE_SECONDS, *SELF_DELETE_RETRY_SECONDS)
    for attempt, delay in enumerate(delays, start=1):
        await asyncio.sleep(delay)
        try:
            await _async_delete_automation_by_id(hass, automation_id)
            return
        except Exception:  # noqa: BLE001 - HA reload/file failures are heterogeneous
            if attempt == len(delays):
                _LOGGER.exception(
                    "Self-delete of automation %s failed after %d attempts",
                    automation_id,
                    attempt,
                )
            else:
                _LOGGER.warning(
                    "Self-delete attempt %d for automation %s failed; retrying",
                    attempt,
                    automation_id,
                    exc_info=True,
                )


async def _async_record_automation_run_after_action(
    hass: HomeAssistant, automation_id: str
) -> None:
    """Record a successful run after its service action has returned."""
    delays = (SELF_DELETE_GRACE_SECONDS, *SELF_DELETE_RETRY_SECONDS)
    for attempt, delay in enumerate(delays, start=1):
        await asyncio.sleep(delay)
        try:
            from .automation_executor import AutomationExecutor

            await AutomationExecutor(hass).async_record_automation_run(automation_id)
            return
        except Exception:  # noqa: BLE001 - HA reload/file failures are heterogeneous
            if attempt == len(delays):
                _LOGGER.exception(
                    "Recording run of automation %s failed after %d attempts",
                    automation_id,
                    attempt,
                )
            else:
                _LOGGER.warning(
                    "Recording run attempt %d for automation %s failed; retrying",
                    attempt,
                    automation_id,
                    exc_info=True,
                )


async def _async_enable_automation_after_action(
    hass: HomeAssistant, automation_id: str
) -> None:
    """Enable after the calling automation action has returned."""
    await asyncio.sleep(SELF_DELETE_GRACE_SECONDS)
    try:
        from .automation_executor import AutomationExecutor

        await AutomationExecutor(hass).async_enable_automation(automation_id)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Resuming automation %s failed", automation_id)


async def _async_cleanup_expired_scheduled_automations(
    hass: HomeAssistant,
) -> None:
    """Reconcile date-bound one-shots after Home Assistant startup."""
    from homeassistant.util import dt as dt_util

    from .automation_executor import AutomationExecutor

    try:
        expired = await AutomationExecutor(
            hass
        ).async_cleanup_expired_scheduled_automations(dt_util.now())
    except Exception:  # noqa: BLE001 - startup cleanup must not unload HomeIntent
        _LOGGER.exception("Cleanup of expired HomeIntent automations failed")
        return
    if expired:
        _LOGGER.info("Removed %d expired HomeIntent automations", len(expired))


async def _async_reconcile_and_cleanup_automations(hass: HomeAssistant) -> None:
    """Repair durable state first, then apply the missed-schedule policy."""
    from .automation_executor import AutomationExecutor

    executor = AutomationExecutor(hass)
    try:
        recovered = await executor.async_recover_incomplete_transaction()
        orphan_metadata = await executor.async_reconcile_homeintent_state()
    except Exception:  # noqa: BLE001 - startup recovery must not unload HomeIntent
        _LOGGER.exception("HomeIntent automation persistence reconciliation failed")
        return
    if recovered:
        _LOGGER.warning("Recovered an interrupted HomeIntent automation transaction")
    if orphan_metadata:
        _LOGGER.info(
            "Removed %d orphan HomeIntent automation metadata entries",
            len(orphan_metadata),
        )
    await _async_cleanup_expired_scheduled_automations(hass)


async def _async_delete_automation_by_id(
    hass: HomeAssistant, automation_id: str
) -> None:
    """Delete one automation immediately; callers decide when it is safe."""
    # Function-local import: automation_executor.py imports the real
    # ``homeassistant.core``/``homeassistant.util`` at module level (no
    # HA-free path exists there, see its own module docstring) - keeping
    # that import out of this module's top level is what lets every
    # existing ``ha_nlu.engine``-only unit test keep importing bare
    # ``ha_nlu.*`` (which always runs this package's ``__init__.py`` first)
    # without the real ``homeassistant`` package installed, exactly as
    # before this wave.
    from .automation_executor import AutomationExecutor

    executor = AutomationExecutor(hass)
    try:
        await executor.async_delete_automation(automation_id)
    except ValueError:
        _LOGGER.debug("ha_nlu.delete_automation: automation %s already gone", automation_id)
