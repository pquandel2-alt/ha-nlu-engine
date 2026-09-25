"""V12 PendingProposal / ActiveGoalSession store and reply resolution.

A proposal is continuation context around a question such as "Die Garage ist
noch offen. Soll ich sie schließen?".  Creating it performs no device action.

Binding rules (identity is never inferred from room occupancy):

* An authenticated HA user may answer only proposals that list them as a
  recipient, on any channel (cross-channel continuation).
* An unauthenticated voice turn may answer only a PUBLIC/HOUSEHOLD proposal
  that was voiced on that exact satellite device.
* Several eligible proposals and a bare "Ja" produce a clarification; the
  latest proposal never silently wins.
* Resolution is idempotent: a resolved/expired proposal cannot be answered
  again (replay protection for voice and push).
"""

from __future__ import annotations

import re
import secrets
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Mapping, Sequence, cast

from .entities import normalize_for_compare
from .proactive_model import (
    ActiveGoalSession,
    CommunicationChannel,
    PendingProposal,
    PrivacyLevel,
    ProposalChoice,
    ProposalState,
    ProposedGoal,
    SessionState,
    TargetState,
)


SCHEMA_VERSION = 1
MAX_PROPOSALS = 64
DEFAULT_PROPOSAL_TTL = timedelta(minutes=30)
PROPOSAL_ID_RE = re.compile(r"^p[0-9a-f]{32}$")


# -- reply classification -------------------------------------------------------

_ACCEPT = frozenset({
    "ja", "ja bitte", "ja gerne", "gerne", "bitte", "ok", "okay", "mach das",
    "ja mach das", "mach", "mach es", "tu das", "ja bitte schliessen",
    "schliessen", "schliess sie", "schliess es", "schliess ihn", "mach sie zu",
    "mach es zu", "mach ihn zu", "ausschalten", "mach es aus", "mach sie aus",
    "schalte es aus", "schalte sie aus", "ja schliessen", "ja ausschalten",
    "starten", "ja starten", "starte sie", "starte die routine", "genau",
    "jawohl", "klar",
})
_REJECT = frozenset({
    "nein", "nein danke", "nee", "noe", "lieber nicht", "nicht noetig",
    "nicht notwendig", "brauchst du nicht", "nein lass", "nein lass es",
    "lass es", "lass mal",
})
_IGNORE = frozenset({
    "ignorieren", "ignorier es", "ignoriere es", "ignoriere das", "ignorier das",
    "ist in ordnung so", "passt so",
})
_LATER = frozenset({
    "spaeter", "nicht jetzt", "erinnere mich spaeter", "spaeter bitte",
    "bitte spaeter", "frag mich spaeter", "jetzt nicht",
})
_LATER_MINUTES_RE = re.compile(
    r"^(?:erinnere\s+mich|frag\s+mich|sag\s+es\s+mir)?\s*(?:bitte\s+)?"
    r"in\s+(?P<n>\d{1,3}|einer|eins|zwei|drei|fuenf|zehn|fuenfzehn|zwanzig|dreissig|vierzig|fuenfzig|sechzig)\s+"
    r"(?P<unit>minute|minuten|stunde|stunden)(?:\s+nochmal|\s+noch\s+einmal|\s+erneut)?(?:\s+bitte)?$"
)
_NUMBER_WORDS = {
    "einer": 1, "eins": 1, "zwei": 2, "drei": 3, "fuenf": 5, "zehn": 10,
    "fuenfzehn": 15, "zwanzig": 20, "dreissig": 30, "vierzig": 40,
    "fuenfzig": 50, "sechzig": 60,
}
DEFAULT_SNOOZE = timedelta(minutes=30)
MAX_SNOOZE = timedelta(hours=12)


@dataclass(frozen=True)
class ProposalReply:
    choice: ProposalChoice
    snooze: timedelta | None = None


def classify_proposal_reply(text: str) -> ProposalReply | None:
    """Exact short replies only; anything longer is not a proposal answer."""
    normalized = normalize_for_compare(text)
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    normalized = " ".join(normalized.split())
    if not normalized or len(normalized.split()) > 8:
        return None
    if normalized in _ACCEPT:
        return ProposalReply(ProposalChoice.ACCEPT)
    if normalized in _REJECT:
        return ProposalReply(ProposalChoice.REJECT)
    if normalized in _IGNORE:
        return ProposalReply(ProposalChoice.IGNORE)
    if normalized in _LATER:
        return ProposalReply(ProposalChoice.LATER, DEFAULT_SNOOZE)
    match = _LATER_MINUTES_RE.fullmatch(normalized)
    if match is not None:
        raw = match.group("n")
        amount = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
        unit = timedelta(hours=1) if match.group("unit").startswith("stunde") else timedelta(minutes=1)
        snooze = min(MAX_SNOOZE, max(timedelta(minutes=1), unit * amount))
        return ProposalReply(ProposalChoice.LATER, snooze)
    return None


# -- store ----------------------------------------------------------------------

class ReplyOutcome(StrEnum):
    NOT_ADDRESSED = "not_addressed"
    APPLIED = "applied"
    CLARIFY = "clarify"
    WRONG_USER = "wrong_user"


@dataclass(frozen=True)
class ReplyResolution:
    outcome: ReplyOutcome
    proposal: PendingProposal | None = None
    candidates: tuple[PendingProposal, ...] = ()


class ProposalStore:
    """Bounded proposal + session store with explicit, idempotent transitions."""

    def __init__(self) -> None:
        self._proposals: OrderedDict[str, PendingProposal] = OrderedDict()
        self._sessions: OrderedDict[str, ActiveGoalSession] = OrderedDict()

    # -- creation ------------------------------------------------------------
    def create(
        self,
        *,
        situation_id: str,
        recipient_user_ids: tuple[str, ...],
        recipient_person_id: str | None,
        proposed_goal: ProposedGoal,
        channel: CommunicationChannel,
        privacy_level: PrivacyLevel,
        subject_label: str,
        question: str,
        now: datetime,
        origin_device_id: str | None = None,
        ttl: timedelta = DEFAULT_PROPOSAL_TTL,
    ) -> PendingProposal:
        # One open proposal per situation: re-asking replaces, never stacks.
        for existing in self.open_for_situation(situation_id, now):
            self.transition(existing.proposal_id, ProposalState.CANCELLED, now=now,
                            by="superseded")
        proposal = PendingProposal(
            f"p{secrets.token_hex(16)}", situation_id, recipient_user_ids,
            proposed_goal, now, now + ttl, channel, True, ProposalState.PENDING,
            privacy_level, subject_label, origin_device_id,
        )
        self._proposals[proposal.proposal_id] = proposal
        session = ActiveGoalSession(
            f"s{secrets.token_hex(12)}", situation_id, proposal.proposal_id,
            recipient_user_ids[0] if len(recipient_user_ids) == 1 else None,
            recipient_person_id, channel, now, now + ttl,
            SessionState.WAITING_FOR_REPLY, question,
        )
        self._sessions[proposal.proposal_id] = session
        self._evict()
        return proposal

    def _evict(self) -> None:
        while len(self._proposals) > MAX_PROPOSALS:
            victim = next(
                (key for key, item in self._proposals.items()
                 if item.state is not ProposalState.PENDING),
                next(iter(self._proposals)),
            )
            self._proposals.pop(victim, None)
            self._sessions.pop(victim, None)

    def bind_origin_device(self, proposal_id: str, device_id: str) -> PendingProposal | None:
        """Record the satellite that voiced the question (first binding wins)."""
        current = self._proposals.get(proposal_id)
        if current is None or current.origin_device_id is not None:
            return current
        updated = replace(current, origin_device_id=device_id)
        self._proposals[proposal_id] = updated
        return updated

    # -- lookup ----------------------------------------------------------------
    def get(self, proposal_id: str) -> PendingProposal | None:
        return self._proposals.get(proposal_id)

    def session(self, proposal_id: str) -> ActiveGoalSession | None:
        return self._sessions.get(proposal_id)

    def open_proposals(self, now: datetime) -> tuple[PendingProposal, ...]:
        return tuple(
            item for item in self._proposals.values()
            if item.state is ProposalState.PENDING and item.expires_at > now
        )

    def open_for_situation(self, situation_id: str, now: datetime) -> tuple[PendingProposal, ...]:
        return tuple(item for item in self.open_proposals(now) if item.situation_id == situation_id)

    def all(self) -> tuple[PendingProposal, ...]:
        return tuple(self._proposals.values())

    # -- transitions -------------------------------------------------------------
    def transition(
        self, proposal_id: str, state: ProposalState, *, now: datetime,
        by: str | None = None, run_id: str | None = None, result: str | None = None,
    ) -> PendingProposal | None:
        current = self._proposals.get(proposal_id)
        if current is None:
            return None
        allowed = _TRANSITIONS.get(current.state, frozenset())
        if state not in allowed:
            return None
        updated = replace(
            current, state=state,
            resolved_at=now if state is not ProposalState.EXECUTING else current.resolved_at,
            resolved_by=by or current.resolved_by,
            run_id=run_id or current.run_id,
            result=result or current.result,
        )
        self._proposals[proposal_id] = updated
        session = self._sessions.get(proposal_id)
        if session is not None:
            self._sessions[proposal_id] = replace(session, state=_SESSION_FOR.get(state, session.state))
        return updated

    def claim_for_execution(self, proposal_id: str, *, now: datetime, by: str) -> PendingProposal | None:
        """Atomic PENDING -> EXECUTING claim; a second claim returns None."""
        current = self._proposals.get(proposal_id)
        if current is None or current.state is not ProposalState.PENDING or current.expires_at <= now:
            return None
        return self.transition(proposal_id, ProposalState.EXECUTING, now=now, by=by)

    def expire(self, now: datetime) -> tuple[PendingProposal, ...]:
        expired: list[PendingProposal] = []
        for key, item in tuple(self._proposals.items()):
            if item.state is ProposalState.PENDING and item.expires_at <= now:
                updated = self.transition(key, ProposalState.EXPIRED, now=now, by="expiry")
                if updated is not None:
                    expired.append(updated)
        return tuple(expired)

    # -- reply binding -------------------------------------------------------------
    def eligible(
        self, *, user_id: str | None, device_id: str | None, now: datetime,
    ) -> tuple[tuple[PendingProposal, ...], bool]:
        """Return (eligible proposals, whether another user's question is here)."""
        eligible: list[PendingProposal] = []
        foreign_here = False
        for item in self.open_proposals(now):
            if user_id is not None:
                if user_id in item.recipient_user_ids:
                    eligible.append(item)
                elif device_id is not None and item.origin_device_id == device_id:
                    foreign_here = True
                continue
            if (
                device_id is not None
                and item.origin_device_id == device_id
                and item.privacy_level <= PrivacyLevel.HOUSEHOLD
            ):
                eligible.append(item)
        return tuple(eligible), foreign_here

    def resolve_target(
        self, *, user_id: str | None, device_id: str | None, now: datetime,
    ) -> ReplyResolution:
        eligible, foreign_here = self.eligible(user_id=user_id, device_id=device_id, now=now)
        if not eligible:
            return ReplyResolution(
                ReplyOutcome.WRONG_USER if foreign_here else ReplyOutcome.NOT_ADDRESSED,
            )
        if len(eligible) > 1:
            return ReplyResolution(ReplyOutcome.CLARIFY, candidates=eligible)
        return ReplyResolution(ReplyOutcome.APPLIED, next(iter(eligible)))

    # -- persistence -------------------------------------------------------------------
    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "proposals": [_proposal_dict(item) for item in self._proposals.values()],
            "sessions": [_session_dict(item) for item in self._sessions.values()],
        }

    @classmethod
    def from_dict(cls, raw: object) -> "ProposalStore":
        """Corrupt or unknown documents restore *nothing* (fail closed)."""
        store = cls()
        if not isinstance(raw, Mapping):
            return store
        document = cast(Mapping[str, object], raw)
        if document.get("schema_version") != SCHEMA_VERSION:
            return store
        proposals = document.get("proposals")
        if isinstance(proposals, list):
            for item in cast(Sequence[object], proposals)[-MAX_PROPOSALS:]:
                parsed = _proposal_from(item)
                if parsed is not None:
                    store._proposals[parsed.proposal_id] = parsed
        sessions = document.get("sessions")
        if isinstance(sessions, list):
            for item in cast(Sequence[object], sessions)[-MAX_PROPOSALS:]:
                session = _session_from(item)
                if session is not None and session.proposal_id in store._proposals:
                    store._sessions[session.proposal_id] = session
        return store


_TRANSITIONS: Mapping[ProposalState, frozenset[ProposalState]] = {
    ProposalState.PENDING: frozenset({
        ProposalState.ACCEPTED, ProposalState.REJECTED, ProposalState.SNOOZED,
        ProposalState.DISMISSED, ProposalState.EXECUTING, ProposalState.EXPIRED,
        ProposalState.CANCELLED,
    }),
    ProposalState.EXECUTING: frozenset({ProposalState.EXECUTED, ProposalState.FAILED}),
    ProposalState.ACCEPTED: frozenset({ProposalState.EXECUTING, ProposalState.CANCELLED}),
}
_SESSION_FOR: Mapping[ProposalState, SessionState] = {
    ProposalState.ACCEPTED: SessionState.CONFIRMED,
    ProposalState.EXECUTING: SessionState.EXECUTING,
    ProposalState.EXECUTED: SessionState.RESOLVED,
    ProposalState.FAILED: SessionState.RESOLVED,
    ProposalState.REJECTED: SessionState.CANCELLED,
    ProposalState.DISMISSED: SessionState.CANCELLED,
    ProposalState.SNOOZED: SessionState.CANCELLED,
    ProposalState.CANCELLED: SessionState.CANCELLED,
    ProposalState.EXPIRED: SessionState.EXPIRED,
}


def _proposal_dict(item: PendingProposal) -> dict[str, object]:
    return {
        "proposal_id": item.proposal_id,
        "situation_id": item.situation_id,
        "recipient_user_ids": list(item.recipient_user_ids),
        "targets": [
            {"entity_id": target.entity_id, "desired_state": target.desired_state,
             "name": target.name}
            for target in item.proposed_goal.targets
        ],
        "description": item.proposed_goal.description,
        "created_at": item.created_at.isoformat(),
        "expires_at": item.expires_at.isoformat(),
        "channel": item.channel.value,
        "state": item.state.value,
        "privacy_level": int(item.privacy_level),
        "subject_label": item.subject_label,
        "origin_device_id": item.origin_device_id,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        "resolved_by": item.resolved_by,
        "run_id": item.run_id,
        "result": item.result,
    }


_ALLOWED_DESIRED = frozenset({"off", "on", "closed", "open"})


def _proposal_from(raw: object) -> PendingProposal | None:
    if not isinstance(raw, Mapping):
        return None
    value = cast(Mapping[str, object], raw)
    try:
        proposal_id = str(value["proposal_id"])
        if not PROPOSAL_ID_RE.fullmatch(proposal_id):
            return None
        recipients = value["recipient_user_ids"]
        targets_raw = value["targets"]
        if not isinstance(recipients, list) or not isinstance(targets_raw, list):
            return None
        targets: list[TargetState] = []
        for target in cast(Sequence[object], targets_raw):
            if not isinstance(target, Mapping):
                return None
            target_map = cast(Mapping[str, object], target)
            entity_id = target_map.get("entity_id")
            desired = target_map.get("desired_state")
            if (
                not isinstance(entity_id, str) or "." not in entity_id
                or desired not in _ALLOWED_DESIRED
            ):
                return None
            targets.append(TargetState(entity_id, str(desired), str(target_map.get("name", ""))))
        if not targets:
            return None
        created = _aware(value["created_at"])
        expires = _aware(value["expires_at"])
        if created is None or expires is None:
            return None
        origin = value.get("origin_device_id")
        return PendingProposal(
            proposal_id, str(value["situation_id"]),
            tuple(str(item) for item in cast(Sequence[object], recipients) if isinstance(item, str)),
            ProposedGoal(tuple(targets), str(value.get("description", ""))),
            created, expires, CommunicationChannel(str(value["channel"])), True,
            ProposalState(str(value["state"])),
            PrivacyLevel(int(cast(int, value["privacy_level"]))),
            str(value.get("subject_label", "")),
            origin if isinstance(origin, str) else None,
            _aware(value.get("resolved_at")),
            _text(value.get("resolved_by")),
            _text(value.get("run_id")),
            _text(value.get("result")),
        )
    except (KeyError, ValueError, TypeError):
        return None


def _session_dict(item: ActiveGoalSession) -> dict[str, object]:
    return {
        "session_id": item.session_id,
        "originating_situation_id": item.originating_situation_id,
        "proposal_id": item.proposal_id,
        "recipient_user_id": item.recipient_user_id,
        "recipient_person_id": item.recipient_person_id,
        "originating_channel": item.originating_channel.value,
        "created_at": item.created_at.isoformat(),
        "expires_at": item.expires_at.isoformat(),
        "state": item.state.value,
        "pending_question": item.pending_question,
        "goal_id": item.goal_id,
    }


def _session_from(raw: object) -> ActiveGoalSession | None:
    if not isinstance(raw, Mapping):
        return None
    value = cast(Mapping[str, object], raw)
    try:
        created = _aware(value["created_at"])
        expires = _aware(value["expires_at"])
        if created is None or expires is None:
            return None
        return ActiveGoalSession(
            str(value["session_id"]), str(value["originating_situation_id"]),
            str(value["proposal_id"]), _text(value.get("recipient_user_id")),
            _text(value.get("recipient_person_id")),
            CommunicationChannel(str(value["originating_channel"])),
            created, expires, SessionState(str(value["state"])),
            str(value.get("pending_question", ""))[:500], _text(value.get("goal_id")),
        )
    except (KeyError, ValueError, TypeError):
        return None


def _aware(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = (
    "DEFAULT_PROPOSAL_TTL",
    "DEFAULT_SNOOZE",
    "MAX_PROPOSALS",
    "PROPOSAL_ID_RE",
    "ProposalReply",
    "ProposalStore",
    "ReplyOutcome",
    "ReplyResolution",
    "classify_proposal_reply",
)
