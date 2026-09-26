"""A strict notify service sink for end-to-end push tests.

Replaces the stub's ``hass.services.async_call`` with a recorder that
validates every ``notify.send_message`` call against the exact field schema
Home Assistant 2026.9 registers for that entity service (``message`` required,
``title`` optional, entity targets, *no extra keys* - HA's entity-service
schemas use ``PREVENT_EXTRA``).  A payload real Home Assistant would reject
fails the test here instead of being silently counted as delivered.

It also simulates the execution of a generated automation's action list, so a
delayed push can be followed from confirmation to the exact service call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol

from homeassistant.core import State

SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): vol.All(
            vol.Any(str, [str]), lambda value: [value] if isinstance(value, str) else value
        ),
        vol.Required("message"): str,
        vol.Optional("title"): str,
    },
    extra=vol.PREVENT_EXTRA,
)
LEGACY_NOTIFY_SCHEMA = vol.Schema(
    {vol.Required("message"): str, vol.Optional("title"): str, vol.Optional("data"): dict},
    extra=vol.PREVENT_EXTRA,
)


@dataclass
class NotifySink:
    hass: Any
    fail: bool = False
    notify_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    other_calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    @classmethod
    def install(
        cls,
        hass: Any,
        entity_ids: tuple[str, ...] = (),
        *,
        legacy_services: tuple[str, ...] = (),
        fail: bool = False,
    ) -> "NotifySink":
        sink = cls(hass, fail)
        for entity_id in entity_ids:
            hass.states._states[entity_id] = State(entity_id, "unknown")
        hass.services._handlers[("notify", "send_message")] = sink.async_call
        for service in legacy_services:
            hass.services._handlers[("notify", service)] = sink.async_call
        hass.services.async_call = sink.async_call
        return sink

    async def async_call(
        self, domain: str, service: str, data: dict[str, Any] | None = None,
        blocking: bool = False, **_: Any,
    ) -> None:
        payload = dict(data or {})
        if domain == "notify" and service == "send_message":
            validated = SEND_MESSAGE_SCHEMA(payload)
            for entity_id in validated["entity_id"]:
                state = self.hass.states.get(entity_id)
                assert state is not None, f"unknown notify entity {entity_id}"
            if self.fail:
                raise RuntimeError("provider rejected the push")
            self.notify_calls.append(("send_message", validated))
            return
        if domain == "notify":
            assert ("notify", service) in self.hass.services._handlers, service
            LEGACY_NOTIFY_SCHEMA(payload)
            if self.fail:
                raise RuntimeError("provider rejected the push")
            self.notify_calls.append((service, payload))
            return
        if domain == "persistent_notification":
            raise AssertionError("a push request must never become a persistent notification")
        self.other_calls.append((domain, service, payload))

    async def async_run_automation_actions(self, actions: list[dict[str, Any]]) -> None:
        """Execute a generated automation's actions the way HA's script engine would."""
        from homeassistant.core import ServiceCall

        import homeintent as homeintent_init

        for action in actions:
            if "sequence" in action:
                await self.async_run_automation_actions(action["sequence"])
                continue
            name = action["action"]
            domain, _, service = name.partition(".")
            data = {**action.get("target", {}), **action.get("data", {})}
            if name == "homeintent.delete_automation":
                await homeintent_init._async_delete_automation(self.hass, ServiceCall(data))
                continue
            await self.async_call(domain, service, data, blocking=True)
