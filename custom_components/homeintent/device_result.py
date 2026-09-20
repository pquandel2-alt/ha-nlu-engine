"""Typed result shared by read-only domain adapters and safe dialogs."""

from __future__ import annotations

from dataclasses import dataclass

from .entities import EntitySnapshot
from .service_call import ServiceCallPlan


@dataclass(frozen=True)
class DeviceControlResult:
    """A response plus an optional already-typed service request."""

    plan: ServiceCallPlan | None
    response_text: str
    requires_confirmation: bool = False
    entity: EntitySnapshot | None = None
    entities: tuple[EntitySnapshot, ...] = ()
    is_query: bool = False

    @property
    def resolved_entities(self) -> tuple[EntitySnapshot, ...]:
        if self.entities:
            return self.entities
        return (self.entity,) if self.entity is not None else ()
