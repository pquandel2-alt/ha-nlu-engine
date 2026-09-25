"""V12 units: detection, reply classification, permission parsing, messages, forecast."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from v12_harness import NOW, entity, garage_states

from homeintent.context_forecast import ContextForecastEngine, HabitEvidence, map_prediction_status
from homeintent.learning_policy import LearningPolicy
from homeintent.prediction import PredictionStatus
from homeintent.predictive_house_model import PredictiveHouseModel
from homeintent.proactive_messages import (
    accept_label,
    clarification_question,
    finish_sentence,
    grouped_message,
    outcome_message,
    situation_message,
)
from homeintent.proactive_model import (
    AnticipationKind,
    CommunicationChannel,
    ModelEvidenceStatus,
    PriorityLevel,
    PrivacyLevel,
    ProactiveSituation,
    ProposalChoice,
    ProposalState,
    ProposedGoal,
    SituationEvidence,
    SituationKind,
    SituationState,
    TargetState,
)
from homeintent.proactive_session import ProposalStore, classify_proposal_reply
from homeintent.room_presence import build_area_lookup
from homeintent.situation_detection import (
    DetectorConfig,
    SituationDetector,
    parse_habit_sequence,
)
from homeintent.standing_permission import (
    AutoExecutionPolicy,
    looks_like_permission_request,
    parse_permission_request,
)
from homeintent.proactive_model import AutoOperator


# -- reply classification --------------------------------------------------------

@pytest.mark.parametrize(("text", "choice", "minutes"), [
    ("Ja", ProposalChoice.ACCEPT, None), ("ja bitte.", ProposalChoice.ACCEPT, None),
    ("Ja, mach das!", ProposalChoice.ACCEPT, None), ("Schließ sie.", ProposalChoice.ACCEPT, None),
    ("okay", ProposalChoice.ACCEPT, None), ("Mach sie zu", ProposalChoice.ACCEPT, None),
    ("Nein", ProposalChoice.REJECT, None), ("nee", ProposalChoice.REJECT, None),
    ("Lieber nicht.", ProposalChoice.REJECT, None), ("Ignorieren", ProposalChoice.IGNORE, None),
    ("Später", ProposalChoice.LATER, 30), ("nicht jetzt", ProposalChoice.LATER, 30),
    ("Erinnere mich in 20 Minuten.", ProposalChoice.LATER, 20),
    ("erinnere mich in zwanzig minuten", ProposalChoice.LATER, 20),
    ("In einer Stunde", ProposalChoice.LATER, 60),
    ("Frag mich in 5 Minuten nochmal", ProposalChoice.LATER, 5),
    ("in 999 stunden", ProposalChoice.LATER, 720),
])
def test_reply_classification(text, choice, minutes):
    reply = classify_proposal_reply(text)
    assert reply is not None and reply.choice is choice
    if minutes is not None:
        assert reply.snooze == timedelta(minutes=minutes)


@pytest.mark.parametrize("text", [
    "", "Wie lange läuft der Nudeltimer noch?", "Stoppe den Timer.", "den ersten",
    "Lösche alle Timer.", "Mach das Licht an", "Ja und mach auch das Licht im Flur an bitte jetzt sofort",
    "Nudeln", "egal", "ohne Namen", "Erinnere mich morgen an den Müll", "Wie spät ist es?",
])
def test_non_replies_are_not_claimed(text):
    assert classify_proposal_reply(text) is None


# -- detection -----------------------------------------------------------------

def test_detector_filters_irrelevant_entities_cheaply():
    detector = SituationDetector(DetectorConfig(appliance_entity_ids=frozenset({"sensor.washer"})))
    assert detector.is_relevant("cover.garage", "garage")
    assert not detector.is_relevant("cover.blinds", "shutter")
    assert detector.is_relevant("binary_sensor.smoke", "smoke")
    assert not detector.is_relevant("binary_sensor.motion", "motion")
    assert detector.is_relevant("sensor.washer", None)
    assert not detector.is_relevant("sensor.temperature", "temperature")
    assert detector.is_relevant("light.x", None) and detector.is_relevant("person.p", None)


def test_detector_entry_safety_appliance_and_unknown_states():
    detector = SituationDetector(DetectorConfig(appliance_entity_ids=frozenset({"sensor.washer"})))
    states = {item.entity_id: item for item in garage_states()}
    garage = replace(states["cover.garage"], state="open", last_changed=NOW - timedelta(minutes=3))
    signals = detector.detect_state_change(garage, "closed", entities=states.values(), now=NOW, nobody_home=False)
    assert signals[0].active and signals[0].started_at == NOW - timedelta(minutes=3)
    assert signals[0].proposed_goal.targets == (TargetState("cover.garage", "closed", "Garage"),)
    unknown = replace(garage, state="unavailable")
    assert detector.detect_state_change(unknown, "open", entities=(), now=NOW, nobody_home=False) == ()
    door = entity("binary_sensor.front_door", "Haustür", "on", device_class="door")
    door_signal = detector.detect_state_change(door, "off", entities=(), now=NOW, nobody_home=False)[0]
    assert door_signal.active and door_signal.proposed_goal is None  # a sensor cannot be closed
    leak = entity("binary_sensor.leak", "Wassermelder", "on", device_class="moisture")
    assert detector.detect_state_change(leak, "off", entities=(), now=NOW, nobody_home=False)[0].extra["hazard"] == "water_leak"
    washer = entity("sensor.washer", "Waschmaschine", "finished")
    assert detector.detect_state_change(washer, "running", entities=(), now=NOW, nobody_home=True)[0].active
    assert detector.detect_state_change(washer, "idle", entities=(), now=NOW, nobody_home=True) == ()
    restart = replace(washer, state="running")
    assert not detector.detect_state_change(restart, "finished", entities=(), now=NOW, nobody_home=True)[0].active
    with pytest.raises(ValueError):
        detector.detect_state_change(washer, "running", entities=(), now=NOW.replace(tzinfo=None), nobody_home=True)


def test_detector_left_on_is_per_area_and_needs_nobody_home():
    detector = SituationDetector()
    states = [replace(item, state="on") if item.entity_id == "light.living" else item for item in garage_states()]
    active = detector.detect_left_on(tuple(states), now=NOW, nobody_home=True)
    living = next(item for item in active if item.area_id == "living_room")
    assert living.active and living.subject_ids == ("light.living",)
    assert not next(item for item in active if item.area_id == "kitchen").active
    home = detector.detect_left_on(tuple(states), now=NOW, nobody_home=False)
    assert not any(item.active for item in home)
    unknown = detector.detect_left_on(tuple(states), now=NOW, nobody_home=None)
    assert not any(item.active for item in unknown)


def test_still_active_rechecks_live_state():
    detector = SituationDetector()
    states = {item.entity_id: item for item in garage_states()}
    assert detector.still_active(SituationKind.ENTRY_LEFT_OPEN, ("cover.garage",), states, nobody_home=None) is False
    states["cover.garage"] = replace(states["cover.garage"], state="unknown")
    assert detector.still_active(SituationKind.ENTRY_LEFT_OPEN, ("cover.garage",), states, nobody_home=None) is None
    assert detector.still_active(SituationKind.ENTRY_LEFT_OPEN, ("cover.missing",), states, nobody_home=None) is None
    assert detector.still_active(SituationKind.CRITICAL_SAFETY_EVENT, ("binary_sensor.smoke_hall",), states, nobody_home=None) is False
    assert detector.still_active(SituationKind.DEVICE_LEFT_ON_WHEN_LEAVING, ("light.living",), states, nobody_home=False) is False
    assert detector.still_active(SituationKind.APPLIANCE_FINISHED, ("sensor.none",), states, nobody_home=None) is None
    assert detector.still_active(SituationKind.THERMAL_GOAL_AT_RISK, (), states, nobody_home=None) is True


def test_habit_sequence_parsing_is_closed():
    assert parse_habit_sequence("LIGHT_TURN_ON@light.k=on|COVER_OPEN_COVER@cover.k=open") == (
        ("light.k", "on"), ("cover.k", "open"),
    )
    for junk in ("LOCK_UNLOCK@lock.front=unlocked", "garbage", "X@light=on", "X@light.k=blue"):
        assert parse_habit_sequence(junk) == ()


# -- permission parsing ------------------------------------------------------------

LOOKUP = build_area_lookup(garage_states())


@pytest.mark.parametrize("text", [
    "Wenn niemand zuhause ist und im Wohnzimmer noch Licht an ist, darfst du es automatisch ausschalten.",
    "Wenn keiner zu Hause ist und im Wohnzimmer das Licht noch an ist, darfst du es ausschalten",
    "wenn niemand mehr daheim ist und im wohnzimmer licht brennt dann darfst du es automatisch ausmachen",
    "Wenn niemand zu Hause ist und im Wohnzimmer noch Lampen an sind, du darfst sie automatisch abschalten!",
])
def test_permission_parser_accepts_supported_sentences(text):
    assert looks_like_permission_request(text)
    parsed = parse_permission_request(text, owner_user_id="philipp", entities=garage_states(),
                                      area_lookup=LOOKUP, now=NOW)
    assert parsed.error is None, text
    assert parsed.draft.entity_ids == ("light.living", "light.living_floor")
    assert parsed.draft.operator is AutoOperator.LIGHT_TURN_OFF


@pytest.mark.parametrize(("text", "error"), [
    ("Wenn niemand zuhause ist und im Wohnzimmer noch Licht an ist, darfst du es automatisch ausschalten und die Heizung aufdrehen.", "unsupported"),
    ("Wenn niemand zuhause ist und im Dachboden noch Licht an ist, darfst du es automatisch ausschalten.", "area_unknown"),
    ("Wenn niemand zuhause ist und in der Küche noch Licht an ist, darfst du es automatisch einschalten.", "unsupported"),
    ("Du darfst die Garage automatisch schließen.", "never_auto"),
    ("Wenn ich komme, darfst du die Haustür entriegeln.", "never_auto"),
    ("Wenn niemand zuhause ist und im Flur noch Licht an ist, darfst du es automatisch ausschalten.", "no_lights_in_area"),
])
def test_permission_parser_rejects_everything_else(text, error):
    parsed = parse_permission_request(text, owner_user_id="philipp", entities=garage_states(),
                                      area_lookup=LOOKUP, now=NOW)
    assert parsed.draft is None and parsed.error == error


def test_permission_parser_needs_an_owner():
    parsed = parse_permission_request(
        "Wenn niemand zuhause ist und im Wohnzimmer noch Licht an ist, darfst du es automatisch ausschalten.",
        owner_user_id=None, entities=garage_states(), area_lookup=LOOKUP, now=NOW,
    )
    assert parsed.error == "owner_unknown"


def test_never_auto_policy_blocks_dangerous_actuators():
    policy = AutoExecutionPolicy()
    for item in (
        entity("lock.front", "Haustür", "locked"),
        entity("cover.garage", "Garage", "open", device_class="garage"),
        entity("switch.herd", "Herd", "on"),
        entity("switch.backofen", "Backofen", "on"),
        entity("switch.alarm", "Alarmanlage", "on"),
        entity("siren.hall", "Sirene", "on"),
        entity("valve.main", "Hauptventil", "open"),
        entity("climate.living", "Heizung", "heat"),
    ):
        assert policy.never_auto_reason(item, AutoOperator.SWITCH_TURN_OFF) is not None, item.entity_id
    assert policy.never_auto_reason(None, AutoOperator.LIGHT_TURN_OFF) == "unknown_actuator"
    assert policy.never_auto_reason(entity("light.living", "Wohnzimmerlicht", "on"), AutoOperator.LIGHT_TURN_OFF) is None
    assert policy.never_auto_reason(entity("light.living", "Wohnzimmerlicht", "on"), AutoOperator.SWITCH_TURN_OFF) == "operator_not_auto_eligible"


# -- messages -----------------------------------------------------------------------

def _situation(kind, name, **changes):
    base = ProactiveSituation(
        "sit", kind, ("x.y",), "living_room", NOW, NOW, SituationState.ACTIVE, (), (), (),
        PriorityLevel.INFO, PrivacyLevel.HOUSEHOLD, "k", subject_name=name,
    )
    return replace(base, **changes)


GOAL = ProposedGoal((TargetState("cover.garage", "closed", "Garage"),), "")


@pytest.mark.parametrize(("kind", "name", "goal", "expected"), [
    (SituationKind.ENTRY_LEFT_OPEN, "Garage", GOAL, "Die Garage ist noch offen. Soll ich sie schließen?"),
    (SituationKind.ENTRY_LEFT_OPEN, "Garagentor", GOAL, "Das Garagentor ist noch offen. Soll ich es schließen?"),
    (SituationKind.ENTRY_LEFT_OPEN, "Rollladen Einfahrt", GOAL, "Das Gerät „Rollladen Einfahrt“ ist noch offen. Soll ich es schließen?"),
    (SituationKind.ENTRY_LEFT_OPEN, "Haustür", None, "Die Haustür ist noch offen."),
    (SituationKind.APPLIANCE_FINISHED, "Waschmaschine", None, "Die Waschmaschine ist fertig."),
    (SituationKind.APPLIANCE_FINISHED, "Trockner", None, "Der Trockner ist fertig."),
    (SituationKind.THERMAL_GOAL_AT_RISK, "Wohnzimmer", None, "Das Wohnzimmer wird voraussichtlich nicht rechtzeitig warm."),
    (SituationKind.THERMAL_GOAL_AT_RISK, "Küche", None, "Die Küche wird voraussichtlich nicht rechtzeitig warm."),
    (SituationKind.DEVICE_LEFT_ON_WHEN_LEAVING, "Wohnzimmer", GOAL, "Im Wohnzimmer ist noch Licht an, obwohl niemand zu Hause ist. Soll ich es ausschalten?"),
    (SituationKind.DEVICE_LEFT_ON_WHEN_LEAVING, "Küche", GOAL, "In der Küche ist noch Licht an, obwohl niemand zu Hause ist. Soll ich es ausschalten?"),
    (SituationKind.PENDING_GOAL_REQUIRES_ATTENTION, "Wohnzimmer um 7 Uhr auf 21,5 Grad", None,
     "„Wohnzimmer um 7 Uhr auf 21,5 Grad“ konnte nicht wie geplant erreicht werden."),
    (SituationKind.DEVICE_EFFECT_ANOMALY, "Küchenlicht", None, "Das Küchenlicht reagiert ungewöhnlich langsam oder gar nicht."),
])
def test_german_messages(kind, name, goal, expected):
    from homeintent.proactive_messages import full_message

    statement, question = situation_message(_situation(kind, name), goal)
    assert full_message(statement, question) == expected
    assert ".." not in expected and " ." not in expected


def test_safety_messages_and_punctuation_helpers():
    smoke = _situation(SituationKind.CRITICAL_SAFETY_EVENT, "Rauchmelder Flur",
                       evidence=(SituationEvidence("hazard", "smoke"),))
    assert situation_message(smoke, None)[0] == "Achtung: Das Gerät „Rauchmelder Flur“ meldet Rauch!"
    assert finish_sentence("Hallo..") == "Hallo."
    assert finish_sentence("Wirklich?!") == "Wirklich?"
    assert finish_sentence("  ") == ""
    assert grouped_message(["A ist fertig.", "B ist fertig"]) == "Kurz zusammengefasst: A ist fertig. B ist fertig."
    assert grouped_message(["Nur eins"]) == "Nur eins."
    assert clarification_question(["die Garage", "das Licht in der Küche", "die Routine"]) == (
        "Welche Rückfrage meinst du: die Garage, das Licht in der Küche und die Routine?"
    )
    assert accept_label(GOAL) == "Schließen"
    mixed = ProposedGoal((TargetState("light.a", "on"), TargetState("cover.b", "open")), "")
    assert accept_label(mixed) == "Starten"
    assert outcome_message(GOAL, success=True, status="executed") == (
        "Erledigt. Ich habe die Garage geschlossen und die Wirkung geprüft."
    )
    assert outcome_message(mixed, success=True, status="executed").startswith("Erledigt. Alle Schritte")
    for status in ("blocked", "stale", "conflict", "failed"):
        text = outcome_message(GOAL, success=False, status=status)
        assert text.endswith(".") and ".." not in text


# -- forecast (V11 consumption) --------------------------------------------------------

def test_forecast_never_invents_usable_predictions():
    house = PredictiveHouseModel(LearningPolicy())
    engine = ContextForecastEngine(house)
    thermal = _situation(SituationKind.THERMAL_GOAL_AT_RISK, "Wohnzimmer")
    assert not engine.anticipate(thermal, now=NOW).usable
    missing_model = engine.anticipate(thermal, now=NOW, thermal_inputs=(19.0, 21.0, None))
    assert not missing_model.usable and missing_model.model.status is ModelEvidenceStatus.INSUFFICIENT
    anomaly = _situation(SituationKind.DEVICE_EFFECT_ANOMALY, "Licht")
    assert not engine.anticipate(anomaly, now=NOW, effect_operator="LIGHT_TURN_ON").usable
    habit = _situation(SituationKind.HABIT_OPPORTUNITY, "Routine")
    assert not engine.anticipate(habit, now=NOW).usable
    ok = HabitEvidence("m", "philipp", True, True, False, False, 0.9)
    assert engine.anticipate(habit, now=NOW, habit=ok).kind is AnticipationKind.ROUTINE_OPPORTUNITY
    assert engine.anticipate(habit, now=NOW, habit=ok).usable
    for flags in ((False, True, False, False), (True, True, True, False), (True, True, False, True)):
        weak = HabitEvidence("m", "philipp", flags[0], flags[1], flags[2], flags[3], 0.9)
        assert not engine.anticipate(habit, now=NOW, habit=weak).usable
    observed = engine.anticipate(_situation(SituationKind.ENTRY_LEFT_OPEN, "Garage"), now=NOW)
    assert observed.usable and observed.model.status is ModelEvidenceStatus.NOT_USED
    assert not hasattr(observed, "action")
    assert map_prediction_status(PredictionStatus.OUT_OF_DISTRIBUTION) is ModelEvidenceStatus.OUT_OF_DISTRIBUTION
    assert map_prediction_status(PredictionStatus.OK) is ModelEvidenceStatus.OK
    assert ContextForecastEngine(None).anticipate(thermal, now=NOW, thermal_inputs=(1.0, 2.0, None)).usable is False


# -- proposal store transitions ------------------------------------------------------------

def test_proposal_transitions_are_closed_and_idempotent():
    store = ProposalStore()
    proposal = store.create(
        situation_id="s", recipient_user_ids=("philipp",), recipient_person_id="person.philipp",
        proposed_goal=GOAL, channel=CommunicationChannel.VOICE, privacy_level=PrivacyLevel.HOUSEHOLD,
        subject_label="die Garage", question="?", now=NOW,
    )
    assert store.session(proposal.proposal_id).recipient_user_id == "philipp"
    assert store.claim_for_execution(proposal.proposal_id, now=NOW, by="a") is not None
    assert store.claim_for_execution(proposal.proposal_id, now=NOW, by="b") is None
    assert store.transition(proposal.proposal_id, ProposalState.REJECTED, now=NOW) is None
    assert store.transition(proposal.proposal_id, ProposalState.EXECUTED, now=NOW).state is ProposalState.EXECUTED
    assert store.transition(proposal.proposal_id, ProposalState.FAILED, now=NOW) is None
    assert store.transition("missing", ProposalState.EXECUTED, now=NOW) is None
    second = store.create(
        situation_id="s2", recipient_user_ids=("philipp",), recipient_person_id=None,
        proposed_goal=GOAL, channel=CommunicationChannel.PUSH, privacy_level=PrivacyLevel.HOUSEHOLD,
        subject_label="x", question="?", now=NOW,
    )
    replacement = store.create(
        situation_id="s2", recipient_user_ids=("philipp",), recipient_person_id=None,
        proposed_goal=GOAL, channel=CommunicationChannel.PUSH, privacy_level=PrivacyLevel.HOUSEHOLD,
        subject_label="x", question="?", now=NOW,
    )
    assert store.get(second.proposal_id).state is ProposalState.CANCELLED
    assert store.open_for_situation("s2", NOW) == (replacement,)
    assert store.expire(NOW + timedelta(hours=1))[0].proposal_id == replacement.proposal_id
    assert store.claim_for_execution(replacement.proposal_id, now=NOW + timedelta(hours=1), by="late") is None
    restored = ProposalStore.from_dict(store.to_dict())
    assert {item.proposal_id for item in restored.all()} == {item.proposal_id for item in store.all()}
    assert restored.session(proposal.proposal_id) is not None
    assert ProposalStore.from_dict("garbage").all() == ()
    assert ProposalStore.from_dict({"schema_version": 1, "proposals": "x"}).all() == ()


def test_anonymous_binding_requires_household_privacy_and_origin_device():
    store = ProposalStore()
    personal = store.create(
        situation_id="s", recipient_user_ids=("philipp",), recipient_person_id=None,
        proposed_goal=GOAL, channel=CommunicationChannel.VOICE, privacy_level=PrivacyLevel.PERSONAL,
        subject_label="x", question="?", now=NOW, origin_device_id="dev",
    )
    eligible, _ = store.eligible(user_id=None, device_id="dev", now=NOW)
    assert eligible == ()
    store.transition(personal.proposal_id, ProposalState.CANCELLED, now=NOW)
    household = store.create(
        situation_id="t", recipient_user_ids=("philipp",), recipient_person_id=None,
        proposed_goal=GOAL, channel=CommunicationChannel.VOICE, privacy_level=PrivacyLevel.HOUSEHOLD,
        subject_label="x", question="?", now=NOW, origin_device_id="dev",
    )
    assert store.eligible(user_id=None, device_id="dev", now=NOW)[0] == (household,)
    assert store.eligible(user_id=None, device_id="other", now=NOW)[0] == ()
    assert store.bind_origin_device(household.proposal_id, "later").origin_device_id == "dev"


def test_aware_timestamps_required():
    naive = datetime(2026, 1, 1, 12, 0)
    from homeintent.proactive_policy import QuietHoursPolicy

    with pytest.raises(ValueError):
        QuietHoursPolicy().is_quiet(None, naive)
    assert NOW.tzinfo is timezone.utc
