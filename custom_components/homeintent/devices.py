"""Device snapshot: the HA Device Registry concept, as a hass-free dataclass
(World Model Wave, 2026-08-13).

Mirrors ``entities.EntitySnapshot``/``areas.AreaSnapshot``/``floors.FloorSnapshot``:
a plain, frozen dataclass populated once per conversation turn from live HA
data (see ``hass_entities.build_device_snapshots``), never a persisted second
database. Deliberately data-only - there is no lexicon/grammar vocabulary
anywhere in this codebase for "resolve a spoken device name" (no sentence
template asks "welches Gerät"), so unlike ``entities.py``/``areas.py``/
``floors.py`` this module holds no ``resolve_*`` function; adding one now
would be inventing a feature nobody asked for.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceSnapshot:
    """Hass-free view of a Home Assistant device (Device Registry entry).

    ``area_id``/``area_name``/``floor_id``/``floor_name``/``floor_level`` are
    the device's own registry area/floor - HA allows a per-entity area
    override (see ``hass_entities._area_info()``), so an entity in
    ``entity_ids`` can legitimately report a *different* effective area than
    its device here. That's correct HA behaviour, not a bug to reconcile.
    """

    device_id: str
    name: str
    manufacturer: str | None = None
    model: str | None = None
    area_id: str | None = None
    area_name: str | None = None
    floor_id: str | None = None
    floor_name: str | None = None
    floor_level: int | None = None
    entity_ids: tuple[str, ...] = ()
