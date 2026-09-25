"""V12 room-level presence evidence and the voice-satellite registry.

HOME PRESENCE != ROOM PRESENCE != SPEAKER IDENTITY.

* Whether a person is *home* remains the authority of ``person.*`` (passed in
  as ``person_home``).  ``person.x == home`` alone never yields a room.
* ``RoomPresenceResolver`` only combines explicitly configured or
  authoritative HA evidence (person-room sensors such as Bermuda/BLE area
  sensors, area occupancy sensors, a recent authenticated satellite turn).
  It returns an evidence *class*, never a pretend-calibrated probability,
  and returns AMBIGUOUS instead of guessing between rooms.
* ``SatelliteRegistry`` maps voice satellites to areas from the HA area
  registry or explicit HomeIntent configuration.  It never matches friendly
  names.  Zero or several satellites in an area yield no voice target.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Mapping

from .entities import EntitySnapshot, normalize_for_compare
from .proactive_model import (
    RoomEvidenceClass,
    RoomPresenceResult,
    SatelliteRecord,
    SatelliteResolution,
)


_UNRELIABLE = frozenset({"", "unknown", "unavailable", "none", "not_home", "away", "home"})
_OCCUPIED = frozenset({"on", "detected", "occupied", "home"})
OCCUPANCY_CLASSES = frozenset({"occupancy", "presence"})
MAX_INTERACTIONS = 64


@dataclass(frozen=True)
class RoomPresenceConfig:
    person_room_sensors: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: _empty_sensors()
    )
    evidence_validity: timedelta = timedelta(minutes=10)
    interaction_validity: timedelta = timedelta(minutes=5)
    use_occupancy_sensors: bool = True


def _empty_sensors() -> dict[str, tuple[str, ...]]:
    return {}


@dataclass(frozen=True)
class SatelliteInteraction:
    person_id: str
    area_id: str
    at: datetime


class RoomPresenceResolver:
    """Combine typed evidence into EXACT / STRONG / AMBIGUOUS / UNKNOWN."""

    def __init__(self, config: RoomPresenceConfig | None = None) -> None:
        self.config = config or RoomPresenceConfig()
        self._interactions: OrderedDict[str, SatelliteInteraction] = OrderedDict()

    def record_interaction(self, person_id: str, area_id: str, at: datetime) -> None:
        """Only an authenticated turn (known HA user -> person) may call this."""
        self._interactions.pop(person_id, None)
        self._interactions[person_id] = SatelliteInteraction(person_id, area_id, at)
        while len(self._interactions) > MAX_INTERACTIONS:
            self._interactions.popitem(last=False)

    def resolve(
        self,
        person_id: str,
        *,
        person_home: bool | None,
        entities: Mapping[str, EntitySnapshot],
        area_lookup: Mapping[str, str],
        home_person_ids: Iterable[str],
        now: datetime,
    ) -> RoomPresenceResult:
        """Resolve room evidence that is still valid *now*.

        Every source carries its own ``observed_at``; its validity ends at
        ``observed_at + TTL`` and is never extended by resolving again.  A
        source without a trustworthy timezone-aware timestamp is not evidence.
        """
        if person_home is not True:
            return RoomPresenceResult(person_id, None, RoomEvidenceClass.UNKNOWN, None, None,
                                      ("not_home_or_unknown",))
        exact: list[_Evidence] = []
        strong: list[_Evidence] = []
        ambiguous_sources: list[str] = []
        for sensor_id in self.config.person_room_sensors.get(person_id, ()):
            sensor = entities.get(sensor_id)
            if sensor is None:
                continue
            raw = sensor.state.strip()
            if normalize_for_compare(raw) in _UNRELIABLE:
                continue
            area_id = area_lookup.get(raw) or area_lookup.get(normalize_for_compare(raw))
            if area_id is None:
                # An unmapped value is not evidence; never guess a room.
                ambiguous_sources.append(f"unmapped:{sensor_id}")
                continue
            evidence = _fresh(area_id, sensor_id, _observed_at(sensor, now),
                              self.config.evidence_validity, now)
            if evidence is not None:
                exact.append(evidence)
        interaction = self._interactions.get(person_id)
        if interaction is not None:
            evidence = _fresh(interaction.area_id, "recent_satellite_turn", interaction.at,
                              self.config.interaction_validity, now)
            if evidence is not None:
                strong.append(evidence)
        others_home = tuple(item for item in home_person_ids if item != person_id)
        if self.config.use_occupancy_sensors and not exact and not others_home:
            occupied: dict[str, datetime | None] = {}
            for entity in entities.values():
                if (
                    entity.area_id is not None
                    and entity.domain == "binary_sensor"
                    and (entity.device_class or "") in OCCUPANCY_CLASSES
                    and entity.state in _OCCUPIED
                ):
                    stamp = _observed_at(entity, now)
                    current = occupied.get(entity.area_id)
                    occupied[entity.area_id] = (
                        stamp if current is None or (stamp is not None and stamp > current) else current
                    )
            if len(occupied) > 1:
                ambiguous_sources.append("several_occupied_areas")
            elif len(occupied) == 1:
                area_id, stamp = next(iter(occupied.items()))
                evidence = _fresh(area_id, "sole_person_single_occupied_area", stamp,
                                  self.config.evidence_validity, now)
                if evidence is not None:
                    strong.append(evidence)
        exact_areas = {item.area_id for item in exact}
        if len(exact_areas) == 1:
            area_id = next(iter(exact_areas))
            conflicting = [item for item in strong if item.area_id != area_id]
            if conflicting:
                # Fresh sources disagree: no source silently wins.
                return _combined(person_id, None, RoomEvidenceClass.AMBIGUOUS, (*exact, *conflicting))
            return _combined(person_id, area_id, RoomEvidenceClass.EXACT, tuple(exact))
        if len(exact_areas) > 1:
            return _combined(person_id, None, RoomEvidenceClass.AMBIGUOUS, tuple(exact))
        strong_areas = {item.area_id for item in strong}
        if len(strong_areas) == 1 and not ambiguous_sources:
            return _combined(person_id, next(iter(strong_areas)), RoomEvidenceClass.STRONG, tuple(strong))
        if strong or ambiguous_sources:
            result = _combined(person_id, None, RoomEvidenceClass.AMBIGUOUS, tuple(strong))
            return RoomPresenceResult(
                result.person_id, None, RoomEvidenceClass.AMBIGUOUS, result.observed_at,
                result.valid_until, (*result.sources, *ambiguous_sources),
            )
        return RoomPresenceResult(person_id, None, RoomEvidenceClass.UNKNOWN, None, None,
                                  ("no_room_evidence",))


@dataclass(frozen=True)
class _Evidence:
    area_id: str
    source: str
    observed_at: datetime
    valid_until: datetime


_CLOCK_SKEW = timedelta(minutes=1)


def _observed_at(entity: EntitySnapshot, now: datetime) -> datetime | None:
    """Latest trustworthy HA timestamp of an entity's state/attributes."""
    stamps = [
        item for item in (entity.last_changed, entity.last_updated)
        if item is not None and item.tzinfo is not None
    ]
    if not stamps:
        return None
    latest = max(stamps)
    return None if latest > now + _CLOCK_SKEW else min(latest, now)


def _fresh(
    area_id: str, source: str, observed_at: datetime | None, ttl: timedelta, now: datetime,
) -> _Evidence | None:
    if observed_at is None or observed_at.tzinfo is None:
        return None
    valid_until = observed_at + ttl
    if now > valid_until:
        return None
    return _Evidence(area_id, source, observed_at, valid_until)


def _combined(
    person_id: str, area_id: str | None, evidence_class: RoomEvidenceClass,
    items: tuple[_Evidence, ...],
) -> RoomPresenceResult:
    """The result is only as fresh as its oldest contributing source."""
    return RoomPresenceResult(
        person_id, area_id, evidence_class,
        max((item.observed_at for item in items), default=None),
        min((item.valid_until for item in items), default=None),
        tuple(item.source for item in items),
    )


def build_area_lookup(entities: Iterable[EntitySnapshot]) -> dict[str, str]:
    """Area id/name/alias -> area id, from HA registry data carried on snapshots.

    A name shared by two areas is removed rather than resolved to either.
    """
    lookup: dict[str, str] = {}
    conflicts: set[str] = set()
    for entity in entities:
        if entity.area_id is None:
            continue
        for key in (entity.area_id, entity.area_name or "", *entity.area_aliases):
            if not key:
                continue
            for variant in {key, normalize_for_compare(key)}:
                current = lookup.get(variant)
                if current is not None and current != entity.area_id:
                    conflicts.add(variant)
                lookup[variant] = entity.area_id
    for key in conflicts:
        lookup.pop(key, None)
    return lookup


class SatelliteRegistry:
    """Authoritative voice-satellite <-> area mapping."""

    def __init__(
        self,
        registry_records: Iterable[SatelliteRecord] = (),
        configured_areas: Mapping[str, str] | None = None,
    ) -> None:
        configured = dict(configured_areas or {})
        records: dict[str, SatelliteRecord] = {}
        for record in registry_records:
            records[record.entity_id] = record
        for entity_id, area_id in configured.items():
            base = records.get(entity_id)
            records[entity_id] = SatelliteRecord(
                entity_id, area_id, base.device_id if base is not None else None,
                "homeintent_configuration",
            )
        self._records = records

    @property
    def records(self) -> tuple[SatelliteRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def for_area(self, area_id: str | None) -> SatelliteResolution:
        if area_id is None:
            return SatelliteResolution(None, None, "no_area")
        matches = [item for item in self._records.values() if item.area_id == area_id]
        if not matches:
            return SatelliteResolution(area_id, None, "no_satellite_in_area")
        if len(matches) > 1:
            return SatelliteResolution(area_id, None, "multiple_satellites_in_area")
        return SatelliteResolution(area_id, matches[0], "unique_satellite")

    def by_device(self, device_id: str | None) -> SatelliteRecord | None:
        if device_id is None:
            return None
        matches = [item for item in self._records.values() if item.device_id == device_id]
        return matches[0] if len(matches) == 1 else None

    def by_entity(self, entity_id: str | None) -> SatelliteRecord | None:
        return self._records.get(entity_id or "")


def parse_mapping_lines(value: object, *, key_prefix: str, value_prefix: str | None = None) -> dict[str, tuple[str, ...]]:
    """Parse ``key=value[,value]`` lines; malformed lines are ignored (fail closed)."""
    result: dict[str, tuple[str, ...]] = {}
    if not isinstance(value, str):
        return result
    for line in value.splitlines():
        key, separator, raw_values = line.strip().partition("=")
        key = key.strip()
        if not separator or not key.startswith(key_prefix):
            continue
        values = tuple(
            item.strip() for item in raw_values.split(",")
            if item.strip() and (value_prefix is None or item.strip().startswith(value_prefix))
        )
        if values:
            result[key] = values
    return result


__all__ = (
    "OCCUPANCY_CLASSES",
    "RoomPresenceConfig",
    "RoomPresenceResolver",
    "SatelliteRegistry",
    "build_area_lookup",
    "parse_mapping_lines",
)
