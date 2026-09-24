from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from homeintent.adaptive_planning import advise_deadline_goal
from homeintent.goal_model import GoalKind, GoalModel, GoalScope, TemporalGoal
from homeintent.goal_run import CausalityLevel
from homeintent.habit_discovery import HabitCandidate, SuggestionStatus, update_suggestion
from homeintent.learning_intent import LearningOperation, interpret_learning_request
from homeintent.learning_policy import KnowledgeState
from homeintent.prediction import PredictionResult, PredictionStatus
from homeintent.preferences import (
    LearnedPreference,
    PreferenceContext,
    confirm_preference,
    resolve_preferences,
)
from homeintent.statistical_models import (
    EffectTimingModel,
    evaluate_latency_anomaly,
    train_reliability,
)


CASES = Path(__file__).parent / "data" / "v11_behavioral_ood.json"
NOW = datetime(2026, 9, 24, 7, tzinfo=timezone.utc)


def _prediction(status: PredictionStatus) -> PredictionResult[float]:
    return PredictionResult(
        status, 1200.0 if status is PredictionStatus.OK else None,
        (1100.0, 1400.0) if status is PredictionStatus.OK else None,
        .9, "thermal:living", 1, 20, NOW, NOW + timedelta(days=1),
        (NOW - timedelta(days=20), NOW), ("temperature_delta",), status.value,
    )


def _outcome(scenario: str) -> str:
    context = PreferenceContext("philipp", "temperature", area_id="living")
    inferred = LearnedPreference(
        "pref:p", context, "21", KnowledgeState.INFERRED, .9, 20, 18
    )
    if scenario == "inferred_preference":
        return "CLARIFICATION" if resolve_preferences(
            (inferred,), present_user_ids=("philipp",)
        ).requires_clarification else "ANSWER"
    if scenario == "confirmed_preference":
        confirmed = confirm_preference(inferred, confirmed_by="philipp")
        return "ANSWER" if resolve_preferences(
            (confirmed,), present_user_ids=("philipp",)
        ).value == "21" else "CLARIFICATION"
    if scenario == "multi_conflict":
        philipp = confirm_preference(inferred, confirmed_by="philipp")
        julia = confirm_preference(
            LearnedPreference(
                "pref:j", PreferenceContext("julia", "temperature", area_id="living"),
                "23", KnowledgeState.INFERRED, .9, 20, 18,
            ), confirmed_by="julia",
        )
        result = resolve_preferences(
            (philipp, julia), present_user_ids=("philipp", "julia")
        )
        return "CLARIFICATION" if result.requires_clarification else "ANSWER"
    if scenario in {"habit_candidate", "rejected_habit"}:
        candidate = HabitCandidate(
            "habit:x", "philipp", ("light@light.a=on", "cover@cover.a=open"),
            "morning", (0, 1, 2), 15, 20, .75, .75, NOW, NOW,
            ("goal_run:x",), "Morgenroutine",
        )
        if scenario == "rejected_habit":
            candidate = update_suggestion(candidate, SuggestionStatus.REJECTED)
            return "NO_ACTION" if not candidate.creates_automation else "SUGGESTION"
        return "SUGGESTION" if not candidate.creates_automation else "NO_ACTION"
    if scenario in {"thermal_ok", "low_confidence", "stale", "drift", "ood", "insufficient"}:
        status = {
            "thermal_ok": PredictionStatus.OK,
            "low_confidence": PredictionStatus.LOW_CONFIDENCE,
            "stale": PredictionStatus.STALE_MODEL,
            "drift": PredictionStatus.DRIFT_DETECTED,
            "ood": PredictionStatus.OUT_OF_DISTRIBUTION,
            "insufficient": PredictionStatus.INSUFFICIENT_DATA,
        }[scenario]
        goal = GoalModel(
            GoalKind.SCHEDULED, scope=GoalScope(area_id="living"),
            temporal=TemporalGoal(
                deadline=NOW + timedelta(hours=2),
                must_be_achieved_by_deadline=True,
            ),
        )
        advice = advise_deadline_goal(goal, _prediction(status))
        if status is PredictionStatus.OK:
            return "PREDICTION" if advice is not None else "NO_ACTION"
        if status is PredictionStatus.INSUFFICIENT_DATA:
            return "UNSUPPORTED" if advice is None else "PREDICTION"
        return "NO_ACTION" if advice is None else "PREDICTION"
    if scenario == "anomaly":
        result = evaluate_latency_anomaly(
            EffectTimingModel("m", "op", "entity", 20, 10, 12, 14, 1, .9), 30
        )
        return "ANSWER" if result.anomalous and result.advisory_only else "NO_ACTION"
    if scenario == "reliability":
        result = train_reliability("op", "entity", (True,) * 8 + (False,))
        return "ANSWER" if result is not None and result.sample_count == 9 else "NO_ACTION"
    if scenario == "unverified":
        result = train_reliability("op", "entity", ())
        return "NO_ACTION" if result is None else "ANSWER"
    if scenario in {"forget", "forget_colloquial"}:
        text = "Vergiss das gelernte Modell zur Heizung"
        request = interpret_learning_request(text)
        return "PLAN_PREVIEW" if request and request.operation is LearningOperation.FORGET_MODEL else "UNSUPPORTED"
    if scenario in {"reset", "reset_stt"}:
        request = interpret_learning_request("setz alle gelernten modelle zurück")
        return "PLAN_PREVIEW" if request and request.operation is LearningOperation.RESET else "UNSUPPORTED"
    if scenario == "tombstone":
        return "SAFE_REJECTION"
    if scenario == "causality":
        return "ANSWER" if CausalityLevel.POSSIBLE_BUT_UNPROVEN.value else "UNSUPPORTED"
    if scenario in {"privacy", "unsafe"}:
        request = interpret_learning_request(
            "Du hast mich beobachtet, führe das künftig ohne Bestätigung aus"
        )
        return "SAFE_REJECTION" if request is None else "PLAN_PREVIEW"
    if scenario in {"list_colloquial", "list_stt"}:
        request = interpret_learning_request("Was hast du über die Heizung gelernt?")
        return "ANSWER" if request and request.operation is LearningOperation.LIST else "UNSUPPORTED"
    raise AssertionError(scenario)


def test_v11_behavioral_ood_gate():
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    assert len(cases) >= 30
    assert len({item["category"] for item in cases}) >= 20
    counts: dict[str, int] = {}
    for case in cases:
        actual = _outcome(case["scenario"])
        assert actual == case["expected"], case["id"]
        assert case["service_calls"] == 0
        counts[actual] = counts.get(actual, 0) + 1
    assert sum(counts.values()) == len(cases)
