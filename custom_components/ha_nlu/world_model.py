"""World Model: a single per-turn object bundling Entities, Devices, Areas,
Floors and their relationships (V6 architecture plan, World Model Wave,
2026-08-13 - see docs/architecture-v6.md).

HA stays the sole source of truth; ``WorldModel`` is a semantic view computed
fresh per conversation turn from already-fetched snapshots, never a persisted
second database (same principle ``EntitySnapshot``/``AreaSnapshot``/
``FloorSnapshot`` already follow). This module does not recompute anything
those snapshot modules already do: it reuses ``entities.build_entity_index()``,
``areas.area_snapshots()`` and ``floors.floor_snapshots()`` rather than
re-deriving "distinct areas/floors referenced by these entities" a third time.

Not yet consumed by ``engine.py``/``conversation.py`` (see this module's
Brain/docs entry) - built and tested as real infrastructure first, mirroring
how ``nlu/reasoning.py``'s ``ReasoningEngine`` already sat built-and-tested
before being wired into the live pipeline, to avoid introducing a second,
parallel resolution/lookup path next to the ones parsers already use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .areas import AreaSnapshot, area_snapshots
from .devices import DeviceSnapshot
from .entities import EntityIndex, EntitySnapshot, build_entity_index
from .floors import FloorSnapshot, floor_snapshots


@dataclass(frozen=True)
class WorldModel:
    """Bundled semantic view over one conversation turn's entities/devices/
    areas/floors, plus precomputed lookups and relationship accessors.

    The ``*_by_*`` fields are plain public ``Mapping``s (same style
    ``EntityIndex`` already uses) for callers that just want ``.get()``; the
    methods below are thin convenience wrappers over those same fields.
    """

    entities: tuple[EntitySnapshot, ...]
    devices: tuple[DeviceSnapshot, ...]
    areas: tuple[AreaSnapshot, ...]
    floors: tuple[FloorSnapshot, ...]
    entity_index: EntityIndex
    entities_by_id: Mapping[str, EntitySnapshot]
    devices_by_id: Mapping[str, DeviceSnapshot]
    devices_by_area_id: Mapping[str, tuple[DeviceSnapshot, ...]]
    device_id_by_entity_id: Mapping[str, str]
    entities_by_domain: Mapping[str, tuple[EntitySnapshot, ...]]
    entities_by_device_class: Mapping[str, tuple[EntitySnapshot, ...]]
    entities_by_area_id: Mapping[str, tuple[EntitySnapshot, ...]]
    entities_by_floor_id: Mapping[str, tuple[EntitySnapshot, ...]]
    entities_by_capability: Mapping[str, tuple[EntitySnapshot, ...]]

    def device_for_entity(self, entity_id: str) -> DeviceSnapshot | None:
        """The device owning ``entity_id``, or ``None`` if it has no device
        (or its device isn't part of this WorldModel's entity set)."""
        device_id = self.device_id_by_entity_id.get(entity_id)
        return self.devices_by_id.get(device_id) if device_id is not None else None

    def entities_for_device(self, device_id: str) -> tuple[EntitySnapshot, ...]:
        """Entities of ``device_id`` that are actually present in this
        WorldModel's ``entities`` - a device can own entities that aren't
        selected/exposed this turn, so ``device.entity_ids`` alone is never
        trusted blindly; only entities this WorldModel was actually handed
        are ever returned."""
        device = self.devices_by_id.get(device_id)
        if device is None:
            return ()
        return tuple(
            entity
            for entity_id in device.entity_ids
            if (entity := self.entities_by_id.get(entity_id)) is not None
        )

    def devices_in_area(self, area_id: str) -> tuple[DeviceSnapshot, ...]:
        """Devices whose own registry area is ``area_id``. A device with
        ``area_id=None`` never appears here, though it's still reachable via
        ``devices_by_id``."""
        return self.devices_by_area_id.get(area_id, ())

    def select_entities(
        self,
        *,
        domain: str | None = None,
        device_class: str | None = None,
        area_id: str | None = None,
        floor_id: str | None = None,
        capability: str | None = None,
    ) -> tuple[EntitySnapshot, ...]:
        """Select entities through the smallest available precomputed index.

        All supplied constraints are hard filters.  The method never widens
        an unknown area/floor/device class to the whole house.
        """
        pools = [
            pool for value, pool in (
                (domain, self.entities_by_domain.get(domain, ())),
                (device_class, self.entities_by_device_class.get(device_class, ())),
                (area_id, self.entities_by_area_id.get(area_id, ())),
                (floor_id, self.entities_by_floor_id.get(floor_id, ())),
                (capability, self.entities_by_capability.get(capability, ())),
            ) if value is not None
        ]
        candidates = min(pools, key=len) if pools else self.entities
        return tuple(
            entity for entity in candidates
            if (domain is None or entity.domain == domain)
            and (device_class is None or entity.device_class == device_class)
            and (area_id is None or entity.area_id == area_id)
            and (floor_id is None or entity.floor_id == floor_id)
            and (capability is None or capability in entity.capabilities)
        )


def build_world_model(
    entities: list[EntitySnapshot], devices: list[DeviceSnapshot]
) -> WorldModel:
    """Construct a ``WorldModel`` from already-fetched entity/device
    snapshots - hass-free, reuses ``build_entity_index()``/
    ``area_snapshots()``/``floor_snapshots()`` rather than reimplementing any
    of them (Regel 6: no parallel implementation of something that already
    exists)."""
    entities_by_id = {e.entity_id: e for e in entities}
    devices_by_id = {d.device_id: d for d in devices}

    devices_by_area_id: dict[str, list[DeviceSnapshot]] = {}
    for device in devices:
        if device.area_id is not None:
            devices_by_area_id.setdefault(device.area_id, []).append(device)

    device_id_by_entity_id: dict[str, str] = {
        entity_id: device.device_id for device in devices for entity_id in device.entity_ids
    }

    def group(attribute: str) -> dict[str, tuple[EntitySnapshot, ...]]:
        grouped: dict[str, list[EntitySnapshot]] = {}
        for entity in entities:
            value = getattr(entity, attribute)
            if value is not None:
                grouped.setdefault(value, []).append(entity)
        return {value: tuple(items) for value, items in grouped.items()}

    by_capability: dict[str, list[EntitySnapshot]] = {}
    for entity in entities:
        for capability in entity.capabilities:
            by_capability.setdefault(capability, []).append(entity)

    return WorldModel(
        entities=tuple(entities),
        devices=tuple(devices),
        areas=area_snapshots(entities),
        floors=floor_snapshots(entities),
        entity_index=build_entity_index(entities),
        entities_by_id=entities_by_id,
        devices_by_id=devices_by_id,
        devices_by_area_id={area_id: tuple(ds) for area_id, ds in devices_by_area_id.items()},
        device_id_by_entity_id=device_id_by_entity_id,
        entities_by_domain=group("domain"),
        entities_by_device_class=group("device_class"),
        entities_by_area_id=group("area_id"),
        entities_by_floor_id=group("floor_id"),
        entities_by_capability={key: tuple(items) for key, items in by_capability.items()},
    )
