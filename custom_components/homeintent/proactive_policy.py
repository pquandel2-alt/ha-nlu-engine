"""Central deterministic V12 policies: priority, privacy, quiet hours, opportunity.

Each policy answers exactly one question and returns explicit reason codes.
No policy here authorizes or performs a device action:

* PRIORITY != AUTHORIZATION
* OPPORTUNITY != PERMISSION
* CONFIDENCE != CONSENT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Mapping

from .proactive_model import (
    AnticipationResult,
    OpportunityDecision,
    OpportunityOutcome,
    PriorityDecision,
    PriorityLevel,
    PrivacyDecision,
    PrivacyLevel,
    ProactiveSituation,
    QuietHoursWindow,
    SituationKind,
    SituationState,
)


# -- Priority -----------------------------------------------------------------

_SAFETY_PRIORITY: Mapping[str, PriorityLevel] = {
    "smoke": PriorityLevel.CRITICAL,
    "carbon_monoxide": PriorityLevel.CRITICAL,
    "gas": PriorityLevel.CRITICAL,
    "water_leak": PriorityLevel.URGENT,
}
_KIND_PRIORITY: Mapping[SituationKind, PriorityLevel] = {
    SituationKind.APPLIANCE_FINISHED: PriorityLevel.INFO,
    SituationKind.HABIT_OPPORTUNITY: PriorityLevel.SUGGESTION,
    SituationKind.DEVICE_LEFT_ON_WHEN_LEAVING: PriorityLevel.SUGGESTION,
    SituationKind.ENTRY_LEFT_OPEN: PriorityLevel.IMPORTANT,
    SituationKind.THERMAL_GOAL_AT_RISK: PriorityLevel.IMPORTANT,
    SituationKind.PENDING_GOAL_REQUIRES_ATTENTION: PriorityLevel.IMPORTANT,
    SituationKind.DEVICE_EFFECT_ANOMALY: PriorityLevel.INFO,
    SituationKind.TIMER_FINISHED: PriorityLevel.INFO,
}


class PriorityPolicy:
    """Explicit mapping. Only an authoritative safety device can be CRITICAL."""

    def decide(self, situation: ProactiveSituation) -> PriorityDecision:
        if situation.kind is SituationKind.CRITICAL_SAFETY_EVENT:
            hazard = situation.evidence_value("hazard")
            level = _SAFETY_PRIORITY.get(hazard or "")
            if level is None:
                return PriorityDecision(
                    PriorityLevel.IMPORTANT, "unknown_hazard_capped",
                    ("safety_event_without_mapped_hazard",),
                )
            return PriorityDecision(level, f"safety_{hazard}", ("authoritative_device_class",))
        level = _KIND_PRIORITY.get(situation.kind, PriorityLevel.INFO)
        reasons = [f"kind_{situation.kind.value}"]
        # A hint (e.g. from a V11 anomaly) may lower but never raise the
        # mapped level, and nothing but a mapped safety device reaches CRITICAL.
        if situation.priority_hint < level:
            level = situation.priority_hint
            reasons.append("lowered_by_hint")
        if level >= PriorityLevel.CRITICAL:
            level = PriorityLevel.IMPORTANT
            reasons.append("critical_reserved_for_safety_devices")
        return PriorityDecision(level, f"kind_{situation.kind.value}", tuple(reasons))


# -- Privacy ------------------------------------------------------------------

_KIND_PRIVACY: Mapping[SituationKind, PrivacyLevel] = {
    SituationKind.CRITICAL_SAFETY_EVENT: PrivacyLevel.PUBLIC,
    SituationKind.ENTRY_LEFT_OPEN: PrivacyLevel.HOUSEHOLD,
    SituationKind.APPLIANCE_FINISHED: PrivacyLevel.HOUSEHOLD,
    SituationKind.DEVICE_LEFT_ON_WHEN_LEAVING: PrivacyLevel.HOUSEHOLD,
    SituationKind.THERMAL_GOAL_AT_RISK: PrivacyLevel.HOUSEHOLD,
    SituationKind.DEVICE_EFFECT_ANOMALY: PrivacyLevel.HOUSEHOLD,
    SituationKind.HABIT_OPPORTUNITY: PrivacyLevel.PERSONAL,
    SituationKind.PENDING_GOAL_REQUIRES_ATTENTION: PrivacyLevel.PERSONAL,
    SituationKind.TIMER_FINISHED: PrivacyLevel.HOUSEHOLD,
}


class PrivacyPolicy:
    """Every proactive communication carries one classification."""

    def classify(self, situation: ProactiveSituation) -> PrivacyDecision:
        level = _KIND_PRIVACY.get(situation.kind, PrivacyLevel.PERSONAL)
        if situation.privacy_level > level:
            # A detector may tighten privacy (never loosen it).
            return PrivacyDecision(situation.privacy_level, "tightened_by_detector")
        return PrivacyDecision(level, f"kind_{situation.kind.value}")


# -- Quiet hours ---------------------------------------------------------------

def parse_quiet_window(value: object) -> QuietHoursWindow | None:
    """Parse ``HH:MM-HH:MM``; invalid input yields no window (fail closed)."""
    if not isinstance(value, str) or "-" not in value:
        return None
    start_text, _separator, end_text = value.strip().partition("-")
    start = _parse_clock(start_text)
    end = _parse_clock(end_text)
    if start is None or end is None:
        return None
    return QuietHoursWindow(start.hour * 60 + start.minute, end.hour * 60 + end.minute)


def _parse_clock(value: str) -> time | None:
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        return time(int(hour_text), int(minute_text))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class QuietHoursPolicy:
    """Per-user quiet hours evaluated on HA-local wall-clock time.

    Wall-clock minutes are compared, so a DST shift moves the absolute
    instant but never the configured local window (22:00 stays 22:00).
    """

    default_window: QuietHoursWindow | None = None
    user_windows: Mapping[str, QuietHoursWindow] = field(default_factory=lambda: _no_windows())

    def is_quiet(self, user_id: str | None, local_now: datetime) -> bool:
        if local_now.tzinfo is None:
            raise ValueError("Ruhezeiten benötigen eine lokale Zeitzone")
        window = self.user_windows.get(user_id or "", self.default_window)
        if window is None:
            return False
        return window.contains(local_now.hour * 60 + local_now.minute)


def _no_windows() -> dict[str, QuietHoursWindow]:
    return {}


# -- Opportunity ---------------------------------------------------------------

_MIN_DURATION: Mapping[SituationKind, timedelta] = {
    SituationKind.ENTRY_LEFT_OPEN: timedelta(minutes=15),
    SituationKind.DEVICE_LEFT_ON_WHEN_LEAVING: timedelta(minutes=5),
}
_MODEL_DEPENDENT = frozenset({
    SituationKind.HABIT_OPPORTUNITY,
    SituationKind.THERMAL_GOAL_AT_RISK,
    SituationKind.DEVICE_EFFECT_ANOMALY,
})


@dataclass(frozen=True)
class OpportunityContext:
    now: datetime
    min_duration: Mapping[SituationKind, timedelta] = field(
        default_factory=lambda: dict(_MIN_DURATION)
    )
    active_goal_subjects: frozenset[str] = frozenset()
    cooldown: timedelta = timedelta(minutes=30)
    reachable: bool = True
    any_recipient_quiet: bool = False
    all_recipients_quiet: bool = False
    muted_by_user: bool = False
    anticipation: AnticipationResult | None = None


class OpportunityPolicy:
    """Answers only: is this worth interrupting the user for?"""

    def decide(
        self,
        situation: ProactiveSituation,
        priority: PriorityLevel,
        context: OpportunityContext,
    ) -> OpportunityDecision:
        state = situation.state
        if situation.kind is SituationKind.TIMER_FINISHED:
            return OpportunityDecision(
                OpportunityOutcome.HISTORY_ONLY, ("announced_by_native_timer",),
            )
        if state in {SituationState.RESOLVED, SituationState.EXPIRED}:
            return OpportunityDecision(OpportunityOutcome.SUPPRESS, ("situation_resolved",))
        critical = priority >= PriorityLevel.URGENT
        if state is SituationState.SNOOZED and situation.snooze_until is not None:
            if context.now < situation.snooze_until and not critical:
                return OpportunityDecision(OpportunityOutcome.SUPPRESS, ("snoozed",))
        if state in {SituationState.ACKNOWLEDGED, SituationState.SUPPRESSED} and not critical:
            return OpportunityDecision(OpportunityOutcome.SUPPRESS, ("acknowledged",))
        if critical:
            reasons = ["priority_escalation"]
            if state is SituationState.COMMUNICATED and situation.communicated_at is not None:
                # Critical items are not silenced, but one ongoing alarm is not
                # re-broadcast on every sensor flicker either.
                if context.now - situation.communicated_at < timedelta(minutes=5):
                    return OpportunityDecision(
                        OpportunityOutcome.HISTORY_ONLY,
                        ("critical_already_escalated_recently",),
                    )
                reasons.append("critical_reminder")
            return OpportunityDecision(OpportunityOutcome.ESCALATE, tuple(reasons))
        minimum = context.min_duration.get(situation.kind)
        if minimum is not None and context.now - situation.started_at < minimum:
            return OpportunityDecision(OpportunityOutcome.SUPPRESS, ("duration_below_threshold",))
        if any(item in context.active_goal_subjects for item in situation.subject_ids):
            return OpportunityDecision(OpportunityOutcome.SUPPRESS, ("goal_already_active",))
        if situation.communicated_at is not None and (
            context.now - situation.communicated_at < context.cooldown
        ):
            return OpportunityDecision(OpportunityOutcome.SUPPRESS, ("already_communicated",))
        if situation.kind in _MODEL_DEPENDENT and situation.kind is not SituationKind.DEVICE_EFFECT_ANOMALY:
            anticipation = context.anticipation
            if anticipation is None or not anticipation.usable:
                return OpportunityDecision(
                    OpportunityOutcome.HISTORY_ONLY,
                    ("model_evidence_not_usable",
                     *(anticipation.reasons if anticipation is not None else ())),
                )
        if context.muted_by_user:
            return OpportunityDecision(OpportunityOutcome.HISTORY_ONLY, ("muted_by_confirmed_preference",))
        if not context.reachable:
            return OpportunityDecision(OpportunityOutcome.HISTORY_ONLY, ("no_reachable_recipient",))
        if context.all_recipients_quiet:
            if priority is PriorityLevel.SUGGESTION:
                return OpportunityDecision(OpportunityOutcome.SUPPRESS, ("quiet_hours_suggestion",))
            if priority is PriorityLevel.INFO:
                return OpportunityDecision(OpportunityOutcome.HISTORY_ONLY, ("quiet_hours_deferred",))
            return OpportunityDecision(
                OpportunityOutcome.COMMUNICATE, ("quiet_hours_private_route",),
            )
        return OpportunityDecision(OpportunityOutcome.COMMUNICATE, (f"priority_{priority.name.lower()}",))


__all__ = (
    "OpportunityContext",
    "OpportunityPolicy",
    "PriorityPolicy",
    "PrivacyPolicy",
    "QuietHoursPolicy",
    "parse_quiet_window",
)
