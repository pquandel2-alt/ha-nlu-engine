"""V12 policy units: priority, privacy, quiet hours (DST), opportunity."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import _ha_stub

_ha_stub.install()

from homeintent.proactive_model import (  # noqa: E402
    AnticipationKind,
    AnticipationResult,
    ModelEvidenceStatus,
    ModelReference,
    OpportunityOutcome,
    PriorityLevel,
    PrivacyLevel,
    ProactiveSituation,
    QuietHoursWindow,
    SituationEvidence,
    SituationKind,
    SituationState,
)
from homeintent.proactive_policy import (  # noqa: E402
    OpportunityContext,
    OpportunityPolicy,
    PriorityPolicy,
    PrivacyPolicy,
    QuietHoursPolicy,
    parse_quiet_window,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def situation(kind: SituationKind, *, hazard: str | None = None,
              state: SituationState = SituationState.ACTIVE,
              started: datetime | None = None, hint: PriorityLevel = PriorityLevel.CRITICAL,
              **changes) -> ProactiveSituation:
    evidence = (SituationEvidence("hazard", hazard),) if hazard else ()
    base = ProactiveSituation(
        "sit", kind, ("x.y",), None, started or NOW - timedelta(hours=1), NOW, state,
        evidence, (), (), hint, PrivacyLevel.PUBLIC, f"{kind.value}:x.y",
    )
    return replace(base, **changes)


@pytest.mark.parametrize(("kind", "hazard", "expected"), [
    (SituationKind.APPLIANCE_FINISHED, None, PriorityLevel.INFO),
    (SituationKind.HABIT_OPPORTUNITY, None, PriorityLevel.SUGGESTION),
    (SituationKind.ENTRY_LEFT_OPEN, None, PriorityLevel.IMPORTANT),
    (SituationKind.CRITICAL_SAFETY_EVENT, "smoke", PriorityLevel.CRITICAL),
    (SituationKind.CRITICAL_SAFETY_EVENT, "carbon_monoxide", PriorityLevel.CRITICAL),
    (SituationKind.CRITICAL_SAFETY_EVENT, "gas", PriorityLevel.CRITICAL),
    (SituationKind.CRITICAL_SAFETY_EVENT, "water_leak", PriorityLevel.URGENT),
    (SituationKind.THERMAL_GOAL_AT_RISK, None, PriorityLevel.IMPORTANT),
    (SituationKind.DEVICE_EFFECT_ANOMALY, None, PriorityLevel.INFO),
    (SituationKind.DEVICE_LEFT_ON_WHEN_LEAVING, None, PriorityLevel.SUGGESTION),
])
def test_priority_mapping_is_explicit(kind, hazard, expected):
    assert PriorityPolicy().decide(situation(kind, hazard=hazard)).level is expected


def test_v11_anomaly_can_never_be_critical():
    decision = PriorityPolicy().decide(situation(SituationKind.DEVICE_EFFECT_ANOMALY, hint=PriorityLevel.CRITICAL))
    assert decision.level is PriorityLevel.INFO
    unknown = PriorityPolicy().decide(situation(SituationKind.CRITICAL_SAFETY_EVENT, hazard="unknown"))
    assert unknown.level is PriorityLevel.IMPORTANT


def test_hint_only_lowers_priority():
    assert PriorityPolicy().decide(
        situation(SituationKind.ENTRY_LEFT_OPEN, hint=PriorityLevel.INFO)
    ).level is PriorityLevel.INFO


def test_privacy_levels_and_tightening():
    policy = PrivacyPolicy()
    assert policy.classify(situation(SituationKind.CRITICAL_SAFETY_EVENT)).level is PrivacyLevel.PUBLIC
    assert policy.classify(situation(SituationKind.ENTRY_LEFT_OPEN)).level is PrivacyLevel.HOUSEHOLD
    assert policy.classify(situation(SituationKind.APPLIANCE_FINISHED)).level is PrivacyLevel.HOUSEHOLD
    assert policy.classify(situation(SituationKind.HABIT_OPPORTUNITY)).level is PrivacyLevel.PERSONAL
    tightened = situation(SituationKind.ENTRY_LEFT_OPEN, privacy_level=PrivacyLevel.SENSITIVE)
    assert policy.classify(tightened).level is PrivacyLevel.SENSITIVE


def test_quiet_window_parsing_fails_closed():
    assert parse_quiet_window("22:00-07:00") == QuietHoursWindow(22 * 60, 7 * 60)
    for bad in ("", "22-07", "25:00-07:00", None, 5, "22:00"):
        assert parse_quiet_window(bad) is None


def test_quiet_hours_overnight_and_per_user():
    policy = QuietHoursPolicy(parse_quiet_window("22:00-07:00"),
                              {"anna": parse_quiet_window("13:00-15:00")})
    berlin = ZoneInfo("Europe/Berlin")
    assert policy.is_quiet("philipp", datetime(2026, 9, 24, 23, 30, tzinfo=berlin))
    assert policy.is_quiet("philipp", datetime(2026, 9, 24, 6, 59, tzinfo=berlin))
    assert not policy.is_quiet("philipp", datetime(2026, 9, 24, 7, 0, tzinfo=berlin))
    assert policy.is_quiet("anna", datetime(2026, 9, 24, 14, 0, tzinfo=berlin))
    assert not policy.is_quiet("anna", datetime(2026, 9, 24, 23, 0, tzinfo=berlin))
    with pytest.raises(ValueError):
        policy.is_quiet("philipp", datetime(2026, 9, 24, 23, 0))


def test_quiet_hours_are_dst_safe_wall_clock():
    policy = QuietHoursPolicy(parse_quiet_window("22:00-07:00"))
    berlin = ZoneInfo("Europe/Berlin")
    # 2026-10-25: CEST -> CET. 06:30 local exists twice in UTC terms? No -
    # the repeated hour is 02:00-03:00; both instances are quiet.
    first = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc).astimezone(berlin)
    second = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc).astimezone(berlin)
    assert first.hour == 2 and second.hour == 2
    assert policy.is_quiet(None, first) and policy.is_quiet(None, second)
    # Spring forward (2026-03-29): 07:00 local is still the boundary.
    after = datetime(2026, 3, 29, 5, 0, tzinfo=timezone.utc).astimezone(berlin)
    assert after.hour == 7 and not policy.is_quiet(None, after)
    before = datetime(2026, 3, 29, 4, 59, tzinfo=timezone.utc).astimezone(berlin)
    assert before.hour == 6 and policy.is_quiet(None, before)


def _ctx(**changes) -> OpportunityContext:
    return replace(OpportunityContext(NOW), **changes)


def _usable(ok: bool) -> AnticipationResult:
    return AnticipationResult(
        AnticipationKind.ROUTINE_OPPORTUNITY, "sit",
        ModelReference("m", ModelEvidenceStatus.OK if ok else ModelEvidenceStatus.STALE),
        "", ok, ("v11_status_stale_model",) if not ok else (),
    )


def test_opportunity_rules_and_reasons():
    policy = OpportunityPolicy()
    garage = situation(SituationKind.ENTRY_LEFT_OPEN)
    decide = policy.decide
    assert decide(garage, PriorityLevel.IMPORTANT, _ctx()).outcome is OpportunityOutcome.COMMUNICATE
    young = replace(garage, started_at=NOW - timedelta(minutes=5))
    assert decide(young, PriorityLevel.IMPORTANT, _ctx()).reasons == ("duration_below_threshold",)
    resolved = replace(garage, state=SituationState.RESOLVED)
    assert decide(resolved, PriorityLevel.IMPORTANT, _ctx()).reasons == ("situation_resolved",)
    ack = replace(garage, state=SituationState.ACKNOWLEDGED)
    assert decide(ack, PriorityLevel.IMPORTANT, _ctx()).outcome is OpportunityOutcome.SUPPRESS
    snoozed = replace(garage, state=SituationState.SNOOZED, snooze_until=NOW + timedelta(minutes=5))
    assert decide(snoozed, PriorityLevel.IMPORTANT, _ctx()).reasons == ("snoozed",)
    recent = replace(garage, communicated_at=NOW - timedelta(minutes=5))
    assert decide(recent, PriorityLevel.IMPORTANT, _ctx()).reasons == ("already_communicated",)
    assert decide(garage, PriorityLevel.IMPORTANT, _ctx(active_goal_subjects=frozenset({"x.y"}))).reasons == ("goal_already_active",)
    assert decide(garage, PriorityLevel.IMPORTANT, _ctx(reachable=False)).outcome is OpportunityOutcome.HISTORY_ONLY
    assert decide(garage, PriorityLevel.IMPORTANT, _ctx(muted_by_user=True)).outcome is OpportunityOutcome.HISTORY_ONLY


def test_quiet_hours_opportunity_matrix():
    policy = OpportunityPolicy()
    quiet = _ctx(all_recipients_quiet=True, any_recipient_quiet=True, anticipation=_usable(True))
    habit = situation(SituationKind.HABIT_OPPORTUNITY)
    appliance = situation(SituationKind.APPLIANCE_FINISHED)
    garage = situation(SituationKind.ENTRY_LEFT_OPEN)
    smoke = situation(SituationKind.CRITICAL_SAFETY_EVENT, hazard="smoke")
    assert policy.decide(habit, PriorityLevel.SUGGESTION, quiet).outcome is OpportunityOutcome.SUPPRESS
    assert policy.decide(appliance, PriorityLevel.INFO, quiet).outcome is OpportunityOutcome.HISTORY_ONLY
    assert policy.decide(garage, PriorityLevel.IMPORTANT, quiet).reasons == ("quiet_hours_private_route",)
    assert policy.decide(smoke, PriorityLevel.CRITICAL, quiet).outcome is OpportunityOutcome.ESCALATE


def test_critical_escalates_even_when_acknowledged_snoozed_or_muted():
    policy = OpportunityPolicy()
    smoke = situation(SituationKind.CRITICAL_SAFETY_EVENT, hazard="smoke")
    for variant in (
        replace(smoke, state=SituationState.ACKNOWLEDGED),
        replace(smoke, state=SituationState.SNOOZED, snooze_until=NOW + timedelta(hours=1)),
    ):
        assert policy.decide(variant, PriorityLevel.CRITICAL, _ctx(muted_by_user=True)).outcome is OpportunityOutcome.ESCALATE
    recent = replace(smoke, state=SituationState.COMMUNICATED, communicated_at=NOW - timedelta(minutes=1))
    assert policy.decide(recent, PriorityLevel.CRITICAL, _ctx()).outcome is OpportunityOutcome.HISTORY_ONLY
    later = replace(recent, communicated_at=NOW - timedelta(minutes=6))
    assert policy.decide(later, PriorityLevel.CRITICAL, _ctx()).outcome is OpportunityOutcome.ESCALATE


def test_model_dependent_situations_need_usable_v11_evidence():
    policy = OpportunityPolicy()
    habit = situation(SituationKind.HABIT_OPPORTUNITY)
    stale = policy.decide(habit, PriorityLevel.SUGGESTION, _ctx(anticipation=_usable(False)))
    assert stale.outcome is OpportunityOutcome.HISTORY_ONLY
    assert "model_evidence_not_usable" in stale.reasons
    assert policy.decide(habit, PriorityLevel.SUGGESTION, _ctx()).outcome is OpportunityOutcome.HISTORY_ONLY
    ok = policy.decide(habit, PriorityLevel.SUGGESTION, _ctx(anticipation=_usable(True)))
    assert ok.outcome is OpportunityOutcome.COMMUNICATE


def test_timer_expiry_is_history_only_for_v12():
    policy = OpportunityPolicy()
    timer = situation(SituationKind.TIMER_FINISHED)
    decision = policy.decide(timer, PriorityLevel.INFO, _ctx())
    assert decision.outcome is OpportunityOutcome.HISTORY_ONLY
    assert decision.reasons == ("announced_by_native_timer",)
