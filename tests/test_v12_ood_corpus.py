"""V12 handwritten OOD corpus (tests/data/v12_ood_de.json).

Every expected value is written by hand in the JSON file; nothing here
derives an expectation from production code.  Case kinds:

* ``reply``      - bare-answer classification (STT-like / colloquial German)
* ``permission`` - StandingPermission request parsing incl. NEVER_AUTO
* ``scenario``   - behavioral: real SituationDetector, Opportunity/Priority/
  Attention/Privacy policies, CommunicationRouter, proposals, permissions and
  the real V10 execution path writing into an instrumented service sink
* ``dialog``     - behavioral: the real ``conversation.py`` with timers,
  automations, security confirmations and V12 proposals competing

Behavioral cases assert ``actual_device_service_calls`` from the sink.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from v12_harness import (
    NOW,
    anna,
    build_world,
    entity,
    garage_states,
    living_satellite,
    philipp,
)
from homeintent.context_forecast import HabitEvidence
from homeintent.proactive_engine import ProactiveConfig
from homeintent.proactive_model import (
    AutoOperator,
    PermissionCondition,
    ProposalChoice,
    RoomEvidenceClass,
    RoomPresenceResult,
    SatelliteRecord,
    SituationEvidence,
    SituationKind,
    StandingPermission,
)
from homeintent.proactive_policy import QuietHoursPolicy, parse_quiet_window
from homeintent.proactive_session import classify_proposal_reply
from homeintent.room_presence import build_area_lookup
from homeintent.situation_detection import (
    DetectionSignal,
    DetectorConfig,
    HabitCandidate,
    SituationDetector,
    habit_signal,
)
from homeintent.standing_permission import parse_permission_request


CASES_PATH = Path(__file__).parent / "data" / "v12_ood_de.json"
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))
REQUIRED_CATEGORIES = {
    "situation_detection", "situation_resolution", "duration", "duplicate_suppression",
    "snooze", "dismiss", "quiet_hours", "attention_budget", "grouping", "critical_bypass",
    "privacy", "room_exact", "room_ambiguous", "room_unknown", "satellite_missing",
    "satellite_multiple", "voice_routing", "push_routing", "interactive_push",
    "cross_channel", "proposal_continuation", "multiple_proposals", "proposal_expiry",
    "wrong_user", "timer_naming_collision", "timer_ambiguity_collision",
    "timer_confirmation_collision", "timer_expiry_dedupe", "automation_dialog_collision",
    "security_dialog_collision", "habit_opportunity", "thermal_goal_risk", "effect_anomaly",
    "standing_permission", "permission_expiry", "permission_revocation", "NEVER_AUTO",
    "lock_safety", "gate_safety", "critical_safety", "restart", "event_storm",
    "stale_prediction", "OOD_prediction", "STT_like_German", "colloquial_German",
    "explainability", "history_queries",
}


def test_corpus_size_and_coverage():
    assert len(CASES) >= 200
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))
    categories = Counter(case["category"] for case in CASES)
    assert REQUIRED_CATEGORIES <= set(categories), REQUIRED_CATEGORIES - set(categories)
    behavioral = [case for case in CASES if case["kind"] in {"scenario", "dialog"}]
    assert len(behavioral) >= 100
    for case in CASES:
        assert case["kind"] in {"reply", "permission", "scenario", "dialog"}
        assert "expected" in case


# ---------------------------------------------------------------------------
# reply / permission cases


@pytest.mark.parametrize("case", [c for c in CASES if c["kind"] == "reply"], ids=lambda c: c["id"])
def test_reply_case(case):
    reply = classify_proposal_reply(case["text"])
    expected = case["expected"]
    if expected["choice"] is None:
        assert reply is None
        return
    assert reply is not None and reply.choice is ProposalChoice(expected["choice"])
    if "minutes" in expected:
        assert reply.snooze == timedelta(minutes=expected["minutes"])


@pytest.mark.parametrize("case", [c for c in CASES if c["kind"] == "permission"], ids=lambda c: c["id"])
def test_permission_case(case):
    states = garage_states()
    parsed = parse_permission_request(
        case["text"], owner_user_id=case.get("owner", "philipp"), entities=states,
        area_lookup=build_area_lookup(states), now=NOW,
    )
    expected = case["expected"]
    if expected["result"] == "accepted":
        assert parsed.draft is not None, parsed.error
        assert list(parsed.draft.entity_ids) == expected["entity_ids"]
    else:
        assert parsed.draft is None and parsed.error == expected["result"]


# ---------------------------------------------------------------------------
# behavioral scenario runner


def _satellites(kind: str) -> list[SatelliteRecord]:
    if kind == "none":
        return []
    if kind == "two":
        return [living_satellite(), SatelliteRecord("assist_satellite.wz2", "living_room", "dev_living2")]
    return [living_satellite()]


def _room(kind: str) -> RoomPresenceResult | None:
    if kind == "exact":
        return RoomPresenceResult("person.philipp", "living_room", RoomEvidenceClass.EXACT, NOW, None)
    if kind == "strong":
        return RoomPresenceResult("person.philipp", "living_room", RoomEvidenceClass.STRONG, NOW, None)
    if kind == "ambiguous":
        return RoomPresenceResult("person.philipp", None, RoomEvidenceClass.AMBIGUOUS, NOW, None)
    return None


def _build(tmp_path: Path, setup: dict):
    extra = [
        entity("sensor.washer", "Waschmaschine", "running", area="bath"),
        entity("sensor.dryer", "Trockner", "running", area="bath"),
        entity("sensor.dishwasher", "Geschirrspüler", "running", area="kitchen"),
        entity("cover.gate", "Hoftor", "closed", area="yard", area_name="Hof", device_class="gate"),
        entity("cover.kitchen", "Küchenrollladen", "closed", area="kitchen", area_name="Küche"),
        entity("binary_sensor.front_door", "Haustür", "off", area="hall", device_class="door"),
        entity("binary_sensor.co_hall", "CO-Melder", "off", area="hall", device_class="carbon_monoxide"),
    ]
    quiet = setup.get("quiet")
    config = ProactiveConfig(
        enabled=setup.get("enabled", True),
        standing_permissions_enabled=setup.get("standing", False),
        quiet=QuietHoursPolicy(parse_quiet_window(quiet)) if quiet else QuietHoursPolicy(),
    )
    home = setup.get("home", {"person.philipp": "home", "person.anna": "not_home"})
    recipients = {"philipp": philipp()}
    if setup.get("anna_recipient"):
        recipients["anna"] = anna()
    if setup.get("philipp_push") is False:
        recipients["philipp"] = replace(philipp(), push_target_ids=())
    world = build_world(
        tmp_path, garage_states() + extra, config=config, recipients=recipients,
        rooms={"person.philipp": room} if (room := _room(setup.get("room", "exact"))) else {},
        satellite_records=_satellites(setup.get("satellites", "one")),
        household=dict(home),
    )
    world.engine.detector = SituationDetector(DetectorConfig(
        appliance_entity_ids=frozenset({"sensor.washer", "sensor.dryer", "sensor.dishwasher"}),
    ))
    if setup.get("night"):
        world.ports.clock = datetime(2026, 9, 24, 21, 30, tzinfo=timezone.utc)  # 23:30 local
    for raw in setup.get("permissions", ()):
        permission = StandingPermission(
            raw.get("id", "perm_1"), raw.get("owner", "philipp"),
            SituationKind(raw.get("kind", "device_left_on_when_leaving")),
            AutoOperator(raw.get("operator", "light_turn_off")), tuple(raw["entities"]),
            raw.get("area", "living_room"),
            tuple(PermissionCondition(item) for item in raw.get("conditions", ["nobody_home"])),
            NOW - timedelta(days=1),
            NOW + timedelta(days=raw.get("days", 30)), raw.get("confirmed", True),
            raw.get("revoked", False),
        )
        if permission.confirmed and permission.situation_kind is SituationKind.DEVICE_LEFT_ON_WHEN_LEAVING:
            world.engine.permissions.add(permission)
        else:
            # Unconfirmed or non-eligible records can only exist in a tampered
            # store; insert them past the boundary check to prove fail-closed.
            world.engine.permissions._items[permission.permission_id] = permission
    return world, config


def _install_thermal(world, *, stale: bool) -> None:
    from homeintent.thermal_model import ThermalBinding, ThermalObservation, train_thermal_model

    policy = world.learning.policy
    observations = []
    for index in range(20):
        delta = 1.5 + (index % 6) * 0.3
        start = 18.5 + (index % 4) * 0.3
        outdoor = 8.0 + (index % 6) * 2.0
        duration = 300.0 + 600.0 * delta + 15.0 * (start - outdoor)
        stamp = NOW - timedelta(days=20 - index)
        observations.append(ThermalObservation(
            stamp, stamp + timedelta(seconds=duration), "living_room", "sensor.living",
            "climate.living", start, start + delta, duration, True, outdoor,
        ))
    model = train_thermal_model(
        ThermalBinding("living_room", "sensor.living", "climate.living", confirmed=True),
        tuple(observations), policy, now=NOW if not stale else NOW - timedelta(days=400),
    )
    assert model is not None
    world.learning.predictive_house.install_thermal(model)


async def _step(world, step: dict, state: dict, tmp_path: Path, config) -> None:
    op = step["op"]
    if op == "change":
        await world.change(step["entity"], step["state"])
    elif op == "advance":
        await world.ports.advance(timedelta(minutes=step.get("minutes", 0), seconds=step.get("seconds", 0)))
    elif op == "person":
        await world.person(step["person"], step["state"])
    elif op == "reply":
        result = await world.engine.async_handle_reply(
            step["text"], user_id=step.get("user", "philipp"), device_id=step.get("device"),
            is_admin=step.get("admin", step.get("user", "philipp") == "philipp"),
        )
        state["reply"] = result
        if result is not None and result.clarification_ids:
            state["clarify"] = result.clarification_ids
    elif op == "select":
        state["reply"] = await world.engine.async_select_and_apply(
            state["clarify"], step["text"], ProposalChoice.ACCEPT,
            user_id=step.get("user", "philipp"), is_admin=True,
        )
    elif op == "push":
        proposal = next(item.proposal_id for item in reversed(world.ports.delivered) if item.proposal_id)
        raw = step.get("raw") or f"HOMEINTENT_V12_{step['choice']}_{proposal}"
        state["reply"] = await world.engine.async_handle_push_action(
            raw.replace("{pid}", proposal), user_id=step.get("user", "philipp"), device_id=None,
        )
    elif op == "restart":
        await world.engine.async_persist()
        fresh, _ = _build(tmp_path, state["setup"])
        fresh.ports.states.update(world.ports.states)
        fresh.ports.clock = world.ports.clock + timedelta(minutes=step.get("minutes", 0))
        fresh.ports.household.update(world.ports.household)
        await fresh.engine.async_restore()
        fresh.sink.calls[:0] = world.sink.calls
        fresh.ports.delivered[:0] = world.ports.delivered
        state["world"] = fresh
    elif op == "thermal":
        if step.get("model") in {"valid", "stale"}:
            _install_thermal(world, stale=step["model"] == "stale")
        await world.engine.async_report_situation(DetectionSignal(
            SituationKind.THERMAL_GOAL_AT_RISK, "thermal_goal_at_risk:g1", (), "living_room", True,
            world.ports.clock,
            (SituationEvidence("current_celsius", str(step["current"])),
             SituationEvidence("target_celsius", str(step["target"])),
             SituationEvidence("area_name", "Wohnzimmer")),
            "Wohnzimmer", owner_user_id=None,
        ))
    elif op == "anomaly":
        await world.engine.async_report_situation(DetectionSignal(
            SituationKind.DEVICE_EFFECT_ANOMALY, f"device_effect_anomaly:{step['entity']}",
            (step["entity"],), None, True, world.ports.clock,
            (SituationEvidence("operator_id", "LIGHT_TURN_ON"),), step.get("name", "Küchenlicht"),
        ))
    elif op == "habit":
        candidate = HabitCandidate(
            "habit:m1", "philipp", "morning", 0,
            (("light.kitchen", "on"), ("cover.kitchen", "open"), ("light.living", "on")),
        )
        world.ports.states["light.kitchen"] = replace(world.ports.states["light.kitchen"], state="on")
        signal = habit_signal(
            world.ports.states["light.kitchen"], (candidate,), now=world.ports.clock,
            local_now=datetime(2026, 9, 21, 7, 5, tzinfo=timezone(timedelta(hours=2))),
            band="morning", home_user_ids=frozenset(step.get("home_users", ["philipp"])),
            entities=world.ports.states,
        )
        state["habit_signal"] = signal
        if signal is not None:
            flags = step.get("model", "valid")
            world.ports.habits = {signal.dedupe_key: HabitEvidence(
                "habit:m1", "philipp", flags != "low", flags != "low",
                flags == "dismissed", flags == "stale", 0.8,
            )}
            await world.engine.async_process_signals((signal,), now=world.ports.clock)
    elif op == "goal_failure":
        await world.engine.async_report_situation(DetectionSignal(
            SituationKind.PENDING_GOAL_REQUIRES_ATTENTION, "pending_goal_requires_attention:r1",
            (), None, True, world.ports.clock, (), step.get("label", "Heizplan"),
            owner_user_id=step.get("owner", "philipp"),
        ))
    elif op == "timer_finished":
        world.engine.record_external_communication(SituationKind.TIMER_FINISHED, step["name"], owner="native_timer")
    elif op == "storm":
        for index in range(step["count"]):
            noise = entity(f"sensor.noise_{index}", f"N{index}", str(index))
            world.ports.states[noise.entity_id] = noise
            await world.engine.async_observe_state(noise, None, (noise,), nobody_home=False)
    elif op == "revoke_all":
        world.engine.permissions.revoke_all(step.get("owner"))
    elif op == "explain":
        state["text"] = world.engine.explain_latest(tuple(step.get("words", ())), user_id=step.get("user", "philipp"))
    elif op == "history":
        state["text"] = world.engine.history_summary(since=NOW - timedelta(days=1), user_id=step.get("user", "philipp"))
    else:  # pragma: no cover - corpus typo
        raise AssertionError(f"unknown op {op}")


def _check(world, state: dict, expected: dict) -> None:
    device_calls = world.sink.device_calls
    assert len(device_calls) == expected.get("device_calls", 0), device_calls
    if "calls" in expected:
        assert [f"{domain}.{service}:{data.get('entity_id')}" for domain, service, data in device_calls] == expected["calls"]
    if "deliveries" in expected:
        assert len(world.ports.delivered) == expected["deliveries"], [m.text for m in world.ports.delivered]
    last = world.ports.delivered[-1] if world.ports.delivered else None
    if "channel" in expected:
        assert last is not None and last.decision.channel.value == expected["channel"], last and last.decision
    if "text" in expected:
        assert last is not None and last.text == expected["text"]
    if "text_contains" in expected:
        assert last is not None and expected["text_contains"] in last.text
    if "priority" in expected:
        assert last is not None and last.priority.name == expected["priority"]
    if "spoken" in expected:
        assert len(world.spoken()) == expected["spoken"]
    if "satellite" in expected:
        assert last is not None and last.decision.satellite_entity_id == expected["satellite"]
    if "reply" in expected:
        reply = state.get("reply")
        if expected["reply"] is None:
            assert reply is None or not reply.handled
        else:
            assert reply is not None
            assert expected["reply"] in reply.speech, reply.speech
    if "situation" in expected:
        for key, value in expected["situation"].items():
            situation = world.engine.situations.get(key)
            assert situation is not None and situation.state.value == value, situation
    if "proposal" in expected:
        proposals = world.engine.proposals.all()
        assert proposals and proposals[-1].state.value == expected["proposal"], proposals
    if "no_situation" in expected:
        for key in expected["no_situation"]:
            assert world.engine.situations.get(key) is None
    if "situations" in expected:
        assert len(world.engine.situations) == expected["situations"]
    if "history_result" in expected:
        assert world.engine.history.records()[-1].result == expected["history_result"]
    if "history_reason" in expected:
        assert any(expected["history_reason"] in record.reasons for record in world.engine.history.records())
    if "permissions_active" in expected:
        assert len(world.engine.permissions.active(world.ports.clock)) == expected["permissions_active"]
    if "state_text" in expected:
        assert expected["state_text"] in state.get("text", "")


@pytest.mark.parametrize("case", [c for c in CASES if c["kind"] == "scenario"], ids=lambda c: c["id"])
def test_scenario_case(case, tmp_path):
    setup = case.get("setup", {})
    world, config = _build(tmp_path, setup)
    state: dict = {"world": world, "setup": setup}

    async def run() -> None:
        for step in case["steps"]:
            await _step(state["world"], step, state, tmp_path, config)

    asyncio.run(run())
    _check(state["world"], state, case["expected"])


# ---------------------------------------------------------------------------
# conversation-level dialog cases


@pytest.mark.parametrize("case", [c for c in CASES if c["kind"] == "dialog"], ids=lambda c: c["id"])
def test_dialog_case(case, tmp_path, monkeypatch):
    from test_v12_conversation import NUDELN, PIZZA, Harness

    timers = {"nudeln": NUDELN, "pizza": PIZZA}
    setup = case.get("setup", {})
    config = ProactiveConfig(enabled=True, standing_permissions_enabled=setup.get("standing", False))
    harness = Harness(tmp_path, monkeypatch, timers=tuple(timers[name] for name in setup.get("timers", ())), config=config)
    proposal_id = harness.open_garage_proposal() if setup.get("garage_proposal", True) else None
    responses = []
    for turn in case["turns"]:
        result = harness.say(turn["text"], user=turn.get("user", "philipp"), device_id=turn.get("device"))
        responses.append(result.response.speech)
    expected = case["expected"]
    assert len(harness.world.sink.device_calls) == expected.get("v12_device_calls", 0)
    agent_calls = harness.agent_device_calls()
    assert [f"{d}.{s}" for d, s in agent_calls] == expected.get("agent_device_calls", [])
    if "last_speech" in expected:
        assert responses[-1] == expected["last_speech"]
    if "last_contains" in expected:
        assert expected["last_contains"] in responses[-1], responses[-1]
    if "first_contains" in expected:
        assert expected["first_contains"] in responses[0], responses[0]
    if "proposal" in expected and proposal_id is not None:
        assert harness.proposal_state(proposal_id).value == expected["proposal"]
    if "permissions" in expected:
        assert len(harness.world.engine.permissions.all()) == expected["permissions"]
    if "timer_cancel_all" in expected:
        assert harness.timers.async_cancel_all.await_count == expected["timer_cancel_all"]
