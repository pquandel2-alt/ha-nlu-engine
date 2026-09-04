"""Bounded verification deadlines for successful HomeIntent service calls."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from .entities import normalize_for_compare
from .service_call import ServiceCallPlan


@dataclass(frozen=True)
class ExpectedEffect:
    effect_id: str
    entity_id: str
    expected_state: str
    registered_at: datetime
    deadline: datetime


ExpiredHandler = Callable[[ExpectedEffect], Awaitable[None]]


class EffectMonitor:
    """Track observable effects; it never retries or performs an action."""

    def __init__(self, *, timeout: timedelta = timedelta(seconds=10)) -> None:
        self.timeout = timeout
        self._pending: dict[str, ExpectedEffect] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._handler: ExpiredHandler | None = None

    def set_expired_handler(self, handler: ExpiredHandler | None) -> None:
        self._handler = handler

    def register(
        self, plan: ServiceCallPlan, *, now: datetime | None = None
    ) -> tuple[ExpectedEffect, ...]:
        expected = _expected_state(plan)
        if expected is None:
            return ()
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("Wirkungsprüfung benötigt eine Zeitzone")
        entity_ids = (
            (plan.entity_id,)
            if isinstance(plan.entity_id, str)
            else tuple(plan.entity_id)
        )
        registered: list[ExpectedEffect] = []
        for entity_id in entity_ids:
            effect = ExpectedEffect(
                f"effect_{uuid.uuid4().hex}",
                entity_id,
                expected,
                current,
                current + self.timeout,
            )
            previous = next(
                (
                    item_id
                    for item_id, item in self._pending.items()
                    if item.entity_id == entity_id
                ),
                None,
            )
            if previous is not None:
                self._discard(previous)
            self._pending[effect.effect_id] = effect
            self._tasks[effect.effect_id] = asyncio.create_task(
                self._expire_after(effect),
                name=f"homeintent-effect-{effect.effect_id}",
            )
            registered.append(effect)
        return tuple(registered)

    def observe(self, entity_id: str, state: str) -> bool:
        normalized = normalize_for_compare(state)
        matched = [
            effect_id
            for effect_id, effect in self._pending.items()
            if effect.entity_id == entity_id
            and normalize_for_compare(effect.expected_state) == normalized
        ]
        for effect_id in matched:
            self._discard(effect_id)
        return bool(matched)

    @property
    def pending(self) -> tuple[ExpectedEffect, ...]:
        return tuple(sorted(self._pending.values(), key=lambda item: item.effect_id))

    async def async_close(self) -> None:
        tasks = tuple(self._tasks.values())
        self._tasks.clear()
        self._pending.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _expire_after(self, effect: ExpectedEffect) -> None:
        delay = max(
            0.0,
            (effect.deadline - datetime.now(timezone.utc)).total_seconds(),
        )
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if self._pending.pop(effect.effect_id, None) is None:
            return
        self._tasks.pop(effect.effect_id, None)
        if self._handler is not None:
            await self._handler(effect)

    def _discard(self, effect_id: str) -> None:
        self._pending.pop(effect_id, None)
        task = self._tasks.pop(effect_id, None)
        if task is not None:
            task.cancel()


def _expected_state(plan: ServiceCallPlan) -> str | None:
    return {
        "turn_on": "on",
        "turn_off": "off",
        "open_cover": "open",
        "open_valve": "open",
        "close_cover": "closed",
        "close_valve": "closed",
        "lock": "locked",
        "unlock": "unlocked",
        "alarm_disarm": "disarmed",
    }.get(plan.service)


__all__ = ("EffectMonitor", "ExpectedEffect")
