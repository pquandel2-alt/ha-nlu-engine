"""Explicit local user, person, household and notification bindings."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Sequence, cast


class BindingStatus(StrEnum):
    RESOLVED = "resolved"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


class NotificationTargetKind(StrEnum):
    ENTITY = "entity"
    SERVICE = "service"


@dataclass(frozen=True)
class NotificationTarget:
    target_id: str
    kind: NotificationTargetKind | None = None
    channel: str = "push"
    label: str = ""
    preferred: bool = False


@dataclass(frozen=True)
class UserContext:
    ha_user_id: str
    person_entity_id: str | None = None
    notification_targets: tuple[NotificationTarget, ...] = ()


@dataclass(frozen=True)
class BindingResult:
    status: BindingStatus
    person_entity_id: str | None = None
    targets: tuple[NotificationTarget, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class HouseholdContext:
    person_entity_ids: tuple[str, ...] = ()


@dataclass
class UserContextStore:
    """Small privacy-preserving store; it never infers bindings from names."""

    path: Path
    _users: dict[str, UserContext] = field(default_factory=lambda: _empty_users(), init=False)
    _household: HouseholdContext = field(default_factory=HouseholdContext, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def async_load(self) -> None:
        raw = await asyncio.to_thread(self._read)
        users_raw = raw.get("users", {})
        users: dict[str, UserContext] = {}
        if isinstance(users_raw, Mapping):
            users_mapping = cast(Mapping[object, object], users_raw)
            for user_id, value in users_mapping.items():
                if not isinstance(user_id, str) or not isinstance(value, Mapping):
                    continue
                user_mapping = cast(Mapping[str, object], value)
                target_values = user_mapping.get("notification_targets", ())
                targets = tuple(
                    NotificationTarget(
                        str(item.get("target_id", "")),
                        _target_kind(item.get("kind")),
                        str(item.get("channel", "push")),
                        str(item.get("label", "")),
                        bool(item.get("preferred", False)),
                    )
                    for item in _mapping_sequence(target_values)
                    if isinstance(item.get("target_id"), str) and item.get("target_id")
                )
                person = user_mapping.get("person_entity_id")
                users[user_id] = UserContext(
                    user_id,
                    person if isinstance(person, str) and person.startswith("person.") else None,
                    targets,
                )
        household_raw = raw.get("household_person_ids", ())
        household = tuple(
            item for item in cast(Sequence[object], household_raw)
            if isinstance(item, str) and item.startswith("person.")
        ) if isinstance(household_raw, (list, tuple)) else ()
        self._users = users
        self._household = HouseholdContext(household)

    async def async_set_user(
        self,
        user_id: str,
        *,
        person_entity_id: str | None,
        notification_targets: Sequence[NotificationTarget] = (),
        confirmed: bool,
        allow_shared_person: bool = False,
    ) -> UserContext:
        if not confirmed:
            raise ValueError("User/person bindings require explicit confirmation")
        if not user_id:
            raise ValueError("A Home Assistant user id is required")
        if person_entity_id is not None and not person_entity_id.startswith("person."):
            raise ValueError("Presence bindings must reference person.*")
        if (
            person_entity_id is not None
            and not allow_shared_person
            and any(
                value.ha_user_id != user_id
                and value.person_entity_id == person_entity_id
                for value in self._users.values()
            )
        ):
            raise ValueError("This person is already explicitly bound to another user")
        for target in notification_targets:
            if not target.target_id.startswith("notify."):
                raise ValueError("Notification targets must be exact notify.* ids")
        context = UserContext(user_id, person_entity_id, tuple(notification_targets))
        async with self._lock:
            self._users[user_id] = context
            await asyncio.to_thread(self._write)
        return context

    async def async_set_household(
        self, person_entity_ids: Sequence[str], *, confirmed: bool
    ) -> HouseholdContext:
        if not confirmed:
            raise ValueError("Household scope requires explicit confirmation")
        values = tuple(dict.fromkeys(person_entity_ids))
        if not values or any(not item.startswith("person.") for item in values):
            raise ValueError("Household scope must contain person.* entities")
        async with self._lock:
            self._household = HouseholdContext(values)
            await asyncio.to_thread(self._write)
        return self._household

    def resolve_current_person(self, user_id: str | None) -> BindingResult:
        if user_id is None or user_id not in self._users:
            return BindingResult(BindingStatus.MISSING, reason="user_person_binding_missing")
        context = self._users[user_id]
        if context.person_entity_id is None:
            return BindingResult(BindingStatus.MISSING, reason="user_person_binding_missing")
        return BindingResult(BindingStatus.RESOLVED, context.person_entity_id)

    def resolve_notification_targets(
        self, person_entity_id: str, *, channel: str = "push"
    ) -> BindingResult:
        contexts = [
            item for item in self._users.values()
            if item.person_entity_id == person_entity_id
        ]
        targets = tuple(
            target for context in contexts for target in context.notification_targets
            if target.channel == channel
        )
        if not targets:
            return BindingResult(
                BindingStatus.MISSING,
                person_entity_id,
                reason="notification_target_missing",
            )
        preferred = tuple(target for target in targets if target.preferred)
        if len(preferred) == 1:
            return BindingResult(BindingStatus.RESOLVED, person_entity_id, preferred)
        if len(targets) == 1:
            return BindingResult(BindingStatus.RESOLVED, person_entity_id, targets)
        return BindingResult(
            BindingStatus.AMBIGUOUS,
            person_entity_id,
            targets,
            "notification_target_ambiguous",
        )

    @property
    def household(self) -> HouseholdContext:
        return self._household

    def nobody_home(self, states: Mapping[str, str]) -> bool | None:
        if not self._household.person_entity_ids:
            return None
        if any(person not in states for person in self._household.person_entity_ids):
            return None
        return all(states[person] != "home" for person in self._household.person_entity_ids)

    def _read(self) -> dict[str, object]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return dict(cast(Mapping[str, object], value)) if isinstance(value, Mapping) else {}

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "users": {
                key: {
                    "person_entity_id": value.person_entity_id,
                    "notification_targets": [asdict(item) for item in value.notification_targets],
                }
                for key, value in sorted(self._users.items())
            },
            "household_person_ids": list(self._household.person_entity_ids),
        }
        descriptor, temporary = tempfile.mkstemp(
            prefix=".homeintent_users_", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    values = cast(Sequence[object], value)
    return tuple(cast(Mapping[str, object], item) for item in values if isinstance(item, Mapping))


def _empty_users() -> dict[str, UserContext]:
    return {}


def _target_kind(value: object) -> NotificationTargetKind | None:
    try:
        return NotificationTargetKind(str(value)) if value is not None else None
    except ValueError:
        return None


__all__ = (
    "BindingResult", "BindingStatus", "HouseholdContext", "NotificationTarget",
    "NotificationTargetKind",
    "UserContext", "UserContextStore",
)
