"""Long-lived deterministic coordinator for proactive HomeIntent situations."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import replace
from datetime import timedelta
from typing import Any, Mapping

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .agent_delivery import AgentDelivery
from .agent_event import AgentEvent, AgentEventState, AgentMode, StoredServicePlan
from .agent_event_store import AgentEventStore
from .automation_executor import AutomationExecutor
from .const import (
    CONF_AGENT_COOLDOWN_SECONDS,
    CONF_AGENT_ENABLED,
    DEFAULT_AGENT_COOLDOWN_SECONDS,
)
from .hass_entities import build_entity_snapshots
from .execution_policy import PolicyOutcome, evaluate_service_plan
from .nlu.automation_operations import validate_registered_operation
from .nlu.automation_confirmation import ConfirmationReply, classify_confirmation_reply
from .risk import RiskLevel
from .runtime_data import HaNluRuntimeData
from .service_call import ServiceCallPlan
from .service_executor import async_execute_service_plan

_LOGGER = logging.getLogger(__name__)

NOTIFICATION_ACTION_EVENT = "mobile_app_notification_action"
ACTION_PREFIXES = {
    "HA_NLU_EXECUTE_": "execute",
    "HA_NLU_IGNORE_": "ignore",
    "HA_NLU_SNOOZE_": "snooze",
}

_CORE_ACTIONS: dict[tuple[str, str], frozenset[str]] = {
    ("homeassistant", "turn_on"): frozenset(
        {"light", "switch", "fan", "climate", "humidifier", "input_boolean"}
    ),
    ("homeassistant", "turn_off"): frozenset(
        {"light", "switch", "fan", "climate", "humidifier", "input_boolean"}
    ),
    ("homeassistant", "toggle"): frozenset(
        {"light", "switch", "fan", "input_boolean"}
    ),
    ("cover", "open_cover"): frozenset({"cover"}),
    ("cover", "close_cover"): frozenset({"cover"}),
    ("cover", "stop_cover"): frozenset({"cover"}),
    ("lock", "lock"): frozenset({"lock"}),
    ("lock", "unlock"): frozenset({"lock"}),
    ("alarm_control_panel", "alarm_disarm"): frozenset({"alarm_control_panel"}),
}


class ProactiveAgentRuntime:
    """Connects native HA automation signals to policy, events and delivery."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        runtime_data: HaNluRuntimeData,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._runtime_data = runtime_data
        self._store = AgentEventStore(hass)
        self._delivery = AgentDelivery(hass)
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._entry.options.get(CONF_AGENT_ENABLED, True))

    def async_start(self) -> Any:
        """Register the sole incoming event required by proactive delivery."""
        bus = getattr(self._hass, "bus", None)
        async_listen = getattr(bus, "async_listen", None)
        if async_listen is None:
            return lambda: None
        return async_listen(NOTIFICATION_ACTION_EVENT, self.async_handle_notification_action)

    async def async_recover(self) -> None:
        """Expire stale events and safely re-evaluate overdue snoozes."""
        now = dt_util.utcnow()
        for event in (await self._store.async_load_all()).values():
            if _parse_datetime(event.expires_at) <= now:
                if event.state not in {AgentEventState.RESOLVED, AgentEventState.EXPIRED}:
                    await self._store.async_save(
                        replace(
                            event,
                            state=AgentEventState.EXPIRED,
                            updated_at=now.isoformat(),
                        )
                    )
                continue
            if (
                event.state is AgentEventState.SNOOZED
                and event.snoozed_until is not None
                and _parse_datetime(event.snoozed_until) <= now
            ):
                await self.async_recheck(event.event_id)

    async def async_signal(self, data: Mapping[str, Any]) -> AgentEvent | None:
        """Create/deliver one deduplicated situation from a native automation."""
        if not self.enabled:
            return None
        rule_id = _required_text(data.get("rule_id"), "rule_id", limit=200)
        message = _required_text(data.get("message"), "message", limit=4000)
        title = _optional_text(data.get("title"), limit=200) or "HomeIntent"
        try:
            mode = AgentMode(str(data.get("mode", AgentMode.INFORM.value)).casefold())
        except ValueError as err:
            raise ValueError("mode muss inform, ask oder auto sein") from err
        source_entity_id = _optional_text(data.get("source_entity_id"), limit=255)
        expected_state = _optional_text(data.get("expected_source_state"), limit=255)
        source_comparator = _optional_text(data.get("source_comparator"), limit=20)
        if source_comparator not in {None, "above", "below", "equal"}:
            raise ValueError("source_comparator muss above, below oder equal sein")
        raw_threshold = data.get("source_threshold")
        source_threshold = (
            float(raw_threshold)
            if isinstance(raw_threshold, (int, float)) and not isinstance(raw_threshold, bool)
            else None
        )
        if source_comparator is not None and source_threshold is None:
            raise ValueError("source_threshold fehlt")
        dedupe_suffix = _optional_text(data.get("dedupe_key"), limit=500)
        dedupe_key = f"{rule_id}:{dedupe_suffix or source_entity_id or 'global'}"
        action = self._parse_action(data)
        if mode in {AgentMode.ASK, AgentMode.AUTO} and action is None:
            raise ValueError("ask und auto benötigen eine vollständig validierbare Aktion")
        now = dt_util.utcnow()
        expires_seconds = _bounded_int(data.get("expires_seconds"), 86400, 60, 604800)
        cooldown = _bounded_int(
            data.get("cooldown_seconds"),
            self._configured_cooldown,
            0,
            86400,
        )
        async with self._lock:
            existing = await self._find_duplicate(dedupe_key, now, cooldown)
            if existing is not None:
                return existing
            event = AgentEvent(
                event_id=uuid.uuid4().hex,
                rule_id=rule_id,
                dedupe_key=dedupe_key,
                title=title,
                message=message,
                mode=mode,
                state=AgentEventState.ACTIVE,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=expires_seconds)).isoformat(),
                source_entity_id=source_entity_id,
                expected_source_state=expected_state,
                source_comparator=source_comparator,
                source_threshold=source_threshold,
                proposed_action=(StoredServicePlan.from_plan(action) if action else None),
            )
            await self._store.async_save(event)

        if not self._source_still_matches(event):
            event = replace(
                event, state=AgentEventState.RESOLVED, updated_at=dt_util.utcnow().isoformat()
            )
            await self._store.async_save(event)
            return event

        if mode is AgentMode.AUTO and action is not None:
            entities = build_entity_snapshots(self._hass, self._entry)
            auto_decision = evaluate_service_plan(
                action,
                entities,
                self._entry.options,
                is_admin=False,
                user_id=None,
            )
            if (
                auto_decision.outcome is not PolicyOutcome.ALLOW
                or auto_decision.risk is not RiskLevel.LOW
            ):
                # AUTO can only execute a plan that is both policy-ALLOW and LOW.
                event = replace(event, mode=AgentMode.ASK)
            else:
                result = await async_execute_service_plan(
                    self._hass,
                    action,
                    entities,
                    self._entry.options,
                    is_admin=True,
                    user_id=None,
                    confirmed=False,
                    audit_trail=self._runtime_data.audit_trail,
                    audit_actor_id="proactive-agent",
                )
                event = replace(
                    event,
                    state=(
                        AgentEventState.RESOLVED
                        if result.executed
                        else AgentEventState.ACTIVE
                    ),
                    mode=(AgentMode.AUTO if result.executed else AgentMode.ASK),
                    last_error=result.error,
                )
        return await self._deliver_and_store(event)

    async def async_handle_notification_action(self, event: Any) -> None:
        if not self.enabled:
            return
        raw_action = getattr(event, "data", {}).get("action")
        if not isinstance(raw_action, str):
            return
        operation = None
        event_id = ""
        for prefix, value in ACTION_PREFIXES.items():
            if raw_action.startswith(prefix):
                operation = value
                event_id = raw_action.removeprefix(prefix)
                break
        if operation is None or len(event_id) != 32 or not event_id.isalnum():
            return
        async with self._lock:
            current = (await self._store.async_load_all()).get(event_id)
            if current is None or current.state not in {
                AgentEventState.ACTIVE,
                AgentEventState.NOTIFIED,
                AgentEventState.SNOOZED,
            }:
                return
            if _parse_datetime(current.expires_at) <= dt_util.utcnow():
                await self._store.async_save(
                    replace(
                        current,
                        state=AgentEventState.EXPIRED,
                        updated_at=dt_util.utcnow().isoformat(),
                    )
                )
                return
            if operation == "ignore":
                await self._store.async_save(
                    replace(
                        current,
                        state=AgentEventState.ACKNOWLEDGED,
                        updated_at=dt_util.utcnow().isoformat(),
                    )
                )
                return
            if operation == "snooze":
                await self._async_snooze_locked(current, 1800)
                return
            # Claim the event before physical I/O so parallel clicks are idempotent.
            claimed = replace(
                current,
                state=AgentEventState.ACKNOWLEDGED,
                updated_at=dt_util.utcnow().isoformat(),
            )
            await self._store.async_save(claimed)

        await self._async_execute_claimed(claimed, user_id=None, is_admin=False)

    async def async_handle_voice_reply(
        self, text: str, *, user_id: str | None, is_admin: bool
    ) -> str | None:
        """Resolve yes/no only against one unique, TTS-delivered ASK event."""
        if not self.enabled:
            return None
        reply = classify_confirmation_reply(text)
        if reply is ConfirmationReply.UNCLEAR:
            return None
        now = dt_util.utcnow()
        async with self._lock:
            candidates = [
                event
                for event in (await self._store.async_load_all()).values()
                if event.mode is AgentMode.ASK
                and event.state is AgentEventState.NOTIFIED
                and "tts" in event.delivered_channels
                and _parse_datetime(event.expires_at) > now
            ]
            if not candidates:
                return None
            if len(candidates) > 1:
                return (
                    "Es sind mehrere Agentenfragen offen. Bitte antworte über die "
                    "zugehörige Push-Nachricht oder nenne die gewünschte Aktion vollständig."
                )
            current = candidates[0]
            claimed = replace(
                current,
                state=AgentEventState.ACKNOWLEDGED,
                updated_at=now.isoformat(),
            )
            await self._store.async_save(claimed)
        if reply is ConfirmationReply.NO:
            return "In Ordnung. Ich führe die vorgeschlagene Aktion nicht aus."
        await self._async_execute_claimed(
            claimed, user_id=user_id, is_admin=is_admin
        )
        finished = (await self._store.async_load_all()).get(claimed.event_id)
        if finished is not None and finished.state is AgentEventState.RESOLVED:
            return "Erledigt."
        return (
            "Die Situation ist nicht mehr aktuell oder die Aktion ist nicht mehr erlaubt. "
            "Ich habe nichts ausgeführt."
        )

    async def async_recheck(self, event_id: str) -> None:
        if not self.enabled:
            return
        async with self._lock:
            current = (await self._store.async_load_all()).get(event_id)
            if current is None or current.state is not AgentEventState.SNOOZED:
                return
            if not self._source_still_matches(current):
                await self._store.async_save(
                    replace(
                        current,
                        state=AgentEventState.RESOLVED,
                        updated_at=dt_util.utcnow().isoformat(),
                    )
                )
                return
            automation_entity_id = self._automation_entity_id(current.rule_id)
            if automation_entity_id is not None:
                # Expiring the old instance lets the original automation
                # create a fresh event if and only if all of its current HA
                # conditions still pass. Its trigger is rechecked above.
                expired = replace(
                    current,
                    state=AgentEventState.EXPIRED,
                    updated_at=dt_util.utcnow().isoformat(),
                    snoozed_until=None,
                    reminder_automation_id=None,
                )
                await self._store.async_save(expired)
            else:
                active = replace(
                    current,
                    state=AgentEventState.ACTIVE,
                    updated_at=dt_util.utcnow().isoformat(),
                    snoozed_until=None,
                    reminder_automation_id=None,
                )
        if automation_entity_id is not None:
            try:
                await self._hass.services.async_call(
                    "automation",
                    "trigger",
                    {"entity_id": automation_entity_id, "skip_condition": False},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                await self._store.async_save(
                    replace(
                        current,
                        state=AgentEventState.SNOOZED,
                        updated_at=dt_util.utcnow().isoformat(),
                        last_error=str(err),
                    )
                )
            return
        await self._deliver_and_store(active)

    async def _async_execute_claimed(
        self, event: AgentEvent, *, user_id: str | None, is_admin: bool
    ) -> None:
        action = event.proposed_action
        if action is None or not self._source_still_matches(event):
            await self._store.async_save(
                replace(
                    event,
                    state=AgentEventState.RESOLVED,
                    updated_at=dt_util.utcnow().isoformat(),
                    last_error=(None if action is not None else "Keine Aktion gespeichert"),
                )
            )
            return
        plan = action.to_plan()
        entities = build_entity_snapshots(self._hass, self._entry)
        result = await async_execute_service_plan(
            self._hass,
            plan,
            entities,
            self._entry.options,
            is_admin=is_admin,
            user_id=user_id,
            confirmed=True,
            audit_trail=self._runtime_data.audit_trail,
            audit_actor_id=user_id or "proactive-agent",
        )
        await self._store.async_save(
            replace(
                event,
                state=(AgentEventState.RESOLVED if result.executed else AgentEventState.EXPIRED),
                updated_at=dt_util.utcnow().isoformat(),
                last_error=result.error,
            )
        )

    async def _async_snooze_locked(self, event: AgentEvent, seconds: int) -> None:
        # HA time triggers use configured local wall-clock time. Persisted
        # lifecycle timestamps remain UTC elsewhere in this module.
        due = dt_util.now() + timedelta(seconds=seconds)
        automation_id = uuid.uuid4().hex
        config = {
            "alias": f"HomeIntent: {event.title} erneut prüfen",
            "description": "Von HomeIntent verwaltete Agent-Snooze-Prüfung",
            "triggers": [{"trigger": "time", "at": due.strftime("%H:%M:%S")}],
            "conditions": [
                {
                    "condition": "template",
                    "value_template": "{{ now().date().isoformat() == '"
                    + due.date().isoformat()
                    + "' }}",
                }
            ],
            "actions": [
                {
                    "action": "ha_nlu.recheck_agent_event",
                    "data": {"event_id": event.event_id},
                },
                {
                    "action": "ha_nlu.delete_automation",
                    "data": {"automation_id": automation_id},
                },
            ],
        }
        await AutomationExecutor(self._hass).async_create_automation(
            config,
            automation_id=automation_id,
            scheduled_for=due,
            once=True,
        )
        await self._store.async_save(
            replace(
                event,
                state=AgentEventState.SNOOZED,
                updated_at=dt_util.utcnow().isoformat(),
                snoozed_until=due.isoformat(),
                reminder_automation_id=automation_id,
            )
        )

    async def _deliver_and_store(self, event: AgentEvent) -> AgentEvent:
        result = await self._delivery.async_deliver(event, self._entry.options)
        now = dt_util.utcnow().isoformat()
        updated = replace(
            event,
            state=(event.state if event.state is AgentEventState.RESOLVED else AgentEventState.NOTIFIED),
            updated_at=now,
            delivery_attempts=event.delivery_attempts + 1,
            delivered_channels=result.delivered_channels,
            last_error="; ".join(result.errors) if result.errors else None,
        )
        await self._store.async_save(updated)
        return updated

    async def _find_duplicate(
        self, dedupe_key: str, now: Any, cooldown_seconds: int
    ) -> AgentEvent | None:
        for event in (await self._store.async_load_all()).values():
            if event.dedupe_key != dedupe_key or event.state is AgentEventState.EXPIRED:
                continue
            if event.state in {
                AgentEventState.ACTIVE,
                AgentEventState.NOTIFIED,
                AgentEventState.SNOOZED,
            }:
                return event
            if cooldown_seconds and (
                now - _parse_datetime(event.updated_at)
            ).total_seconds() < cooldown_seconds:
                return event
        return None

    @property
    def _configured_cooldown(self) -> int:
        value = self._entry.options.get(
            CONF_AGENT_COOLDOWN_SECONDS, DEFAULT_AGENT_COOLDOWN_SECONDS
        )
        return value if isinstance(value, int) else DEFAULT_AGENT_COOLDOWN_SECONDS

    def _source_still_matches(self, event: AgentEvent) -> bool:
        if event.source_entity_id is None:
            return True
        state = self._hass.states.get(event.source_entity_id)
        if state is None:
            return False
        if event.expected_source_state is not None:
            return str(state.state) == event.expected_source_state
        if event.source_comparator is not None and event.source_threshold is not None:
            try:
                value = float(state.state)
            except (TypeError, ValueError):
                return False
            if event.source_comparator == "above":
                return value > event.source_threshold
            if event.source_comparator == "below":
                return value < event.source_threshold
            return value == event.source_threshold
        return True

    def _automation_entity_id(self, automation_id: str) -> str | None:
        try:
            from homeassistant.helpers import entity_registry as er

            return er.async_get(self._hass).async_get_entity_id(
                "automation", "automation", automation_id
            )
        except Exception:  # noqa: BLE001 - registry may be unavailable during startup
            return None

    def _parse_action(self, data: Mapping[str, Any]) -> ServiceCallPlan | None:
        domain = _optional_text(data.get("action_domain"), limit=100)
        service = _optional_text(data.get("action_service"), limit=100)
        raw_entity_ids = data.get("action_entity_id")
        if domain is None and service is None and raw_entity_ids is None:
            return None
        if domain is None or service is None:
            raise ValueError("action_domain und action_service müssen zusammen gesetzt sein")
        if isinstance(raw_entity_ids, str):
            entity_ids = [raw_entity_ids]
        elif isinstance(raw_entity_ids, (list, tuple)):
            entity_ids = [str(item) for item in raw_entity_ids if isinstance(item, str)]
        else:
            entity_ids = []
        if not entity_ids:
            raise ValueError("action_entity_id fehlt")
        action_data = data.get("action_data", {})
        if isinstance(action_data, str):
            try:
                action_data = json.loads(action_data) if action_data else {}
            except json.JSONDecodeError as err:
                raise ValueError("action_data ist kein gültiges JSON-Objekt") from err
        if not isinstance(action_data, Mapping):
            raise ValueError("action_data muss ein Objekt sein")
        entity_domains = frozenset(item.split(".", 1)[0] for item in entity_ids)
        core_domains = _CORE_ACTIONS.get((domain, service))
        allowed = (
            core_domains is not None and entity_domains <= core_domains
        ) or validate_registered_operation(
            domain, service, action_data, target_domains=entity_domains
        )
        if not allowed:
            raise ValueError("Die vorgeschlagene Aktion ist nicht freigegeben")
        target: str | list[str] = entity_ids[0] if len(entity_ids) == 1 else entity_ids
        return ServiceCallPlan(domain, service, target, dict(action_data))


def _required_text(value: object, field: str, *, limit: int) -> str:
    result = _optional_text(value, limit=limit)
    if result is None:
        raise ValueError(f"{field} fehlt")
    return result


def _optional_text(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped and len(stripped) <= limit else None


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return max(minimum, min(maximum, int(value)))
    return default


def _parse_datetime(value: str) -> Any:
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return dt_util.utcnow()
    return parsed
