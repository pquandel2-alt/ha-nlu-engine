#!/usr/bin/env python3
"""Deterministic V12 decision-path microbenchmarks with per-stage budgets.

Budgets (p95, milliseconds): situation evaluation 100, opportunity 50,
priority 20, communication routing 20, room presence 50, active-session
lookup 20.  A 1000-event storm of unrelated entities must stay bounded.
The benchmark drives the real engine with a registry of ``--registry-size``
entities; device execution is not part of any timed decision path.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from homeintent.attention_policy import AttentionPolicy, AttentionStateStore  # noqa: E402
from homeintent.communication_router import CommunicationRouter  # noqa: E402
from homeintent.context_forecast import HabitEvidence  # noqa: E402
from homeintent.entities import EntitySnapshot  # noqa: E402
from homeintent.execution_coordinator import ExecutionCoordinator  # noqa: E402
from homeintent.proactive_engine import (  # noqa: E402
    DeliveryReceipt,
    OutgoingMessage,
    ProactiveConfig,
    ProactiveContextEngine,
)
from homeintent.proactive_execution import V10ProposalRunner  # noqa: E402
from homeintent.proactive_model import (  # noqa: E402
    AttentionDecision,
    AttentionOutcome,
    CommunicationChannel,
    PriorityLevel,
    PrivacyLevel,
    ProactiveSituation,
    ProposedGoal,
    RecipientContext,
    RoomEvidenceClass,
    RoomPresenceResult,
    SatelliteRecord,
    SituationKind,
    SituationState,
    TargetState,
)
from homeintent.proactive_policy import OpportunityContext, OpportunityPolicy, PriorityPolicy  # noqa: E402
from homeintent.proactive_session import ProposalStore  # noqa: E402
from homeintent.room_presence import (  # noqa: E402
    RoomPresenceConfig,
    RoomPresenceResolver,
    SatelliteRegistry,
    build_area_lookup,
)
from homeintent.proactive_store import GenerationalJsonFile  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, int(round(0.95 * (len(ordered) - 1))))]


def _registry(size: int) -> dict[str, EntitySnapshot]:
    entities: dict[str, EntitySnapshot] = {}
    for index in range(size):
        area = f"area_{index % 60}"
        domain = ("light", "sensor", "switch", "binary_sensor")[index % 4]
        entity_id = f"{domain}.item_{index}"
        entities[entity_id] = EntitySnapshot(
            entity_id, f"Item {index}", domain, "off", area_id=area, area_name=f"Raum {index % 60}",
            device_class="occupancy" if domain == "binary_sensor" and index % 8 == 3 else None,
        )
    entities["cover.garage"] = EntitySnapshot(
        "cover.garage", "Garage", "cover", "closed", area_id="garage", area_name="Garage",
        device_class="garage", last_changed=NOW,
    )
    entities["sensor.philipp_area"] = EntitySnapshot(
        "sensor.philipp_area", "Philipp Raum", "sensor", "Raum 1", area_id=None,
    )
    return entities


class Ports:
    def __init__(self, entities: dict[str, EntitySnapshot]) -> None:
        self.entities = entities
        self.clock = NOW
        self.sat = SatelliteRegistry([SatelliteRecord("assist_satellite.a1", "area_1", "d1")])
        self.resolver = RoomPresenceResolver(RoomPresenceConfig(
            person_room_sensors={"person.philipp": ("sensor.philipp_area",)},
        ))
        self.lookup = build_area_lookup(entities.values())
        self.sent = 0

    def now(self) -> datetime:
        return self.clock

    def local_now(self) -> datetime:
        return self.clock.astimezone(timezone(timedelta(hours=2)))

    def fresh_entities(self) -> Mapping[str, EntitySnapshot]:
        return self.entities

    def nobody_home(self) -> bool | None:
        return False

    def recipients_for(self, situation: ProactiveSituation) -> tuple[RecipientContext, ...]:
        return (RecipientContext("philipp", "person.philipp", True, ("notify.p",)),)

    def room_for(self, person_id: str | None) -> RoomPresenceResult | None:
        return self.resolver.resolve(
            person_id or "", person_home=True, entities=self.entities, area_lookup=self.lookup,
            home_person_ids=("person.philipp",), now=self.clock,
        )

    def others_home(self, person_id: str | None) -> bool:
        return False

    def satellites(self) -> SatelliteRegistry:
        return self.sat

    def owner_known(self, user_id: str) -> bool:
        return True

    def person_for(self, user_id: str | None) -> str | None:
        return "person.philipp"

    def active_goal_subjects(self) -> frozenset[str]:
        return frozenset()

    def habit_evidence(self, situation: ProactiveSituation) -> HabitEvidence | None:
        return None

    async def async_is_admin(self, user_id: str | None) -> bool:
        return True

    async def async_deliver(self, message: OutgoingMessage) -> DeliveryReceipt:
        self.sent += 1
        return DeliveryReceipt((message.decision.channel,), "d1")

    def schedule(self, key: str, at: datetime, callback: Callable[[], Awaitable[None]]) -> None:
        return None

    def cancel(self, key: str) -> None:
        return None


def _situation(index: int) -> ProactiveSituation:
    return ProactiveSituation(
        f"sit_{index}", SituationKind.ENTRY_LEFT_OPEN, ("cover.garage",), "garage",
        NOW - timedelta(minutes=20), NOW, SituationState.ACTIVE, (), (), (),
        PriorityLevel.IMPORTANT, PrivacyLevel.HOUSEHOLD, f"entry_left_open:cover.garage:{index}",
        subject_name="Garage",
    )


async def _run(args: argparse.Namespace) -> dict[str, list[float]]:
    entities = _registry(args.registry_size)
    ports = Ports(entities)

    async def refresh() -> list[EntitySnapshot]:
        return list(entities.values())

    async def never(*_args: object) -> object:  # pragma: no cover - never timed
        raise AssertionError("benchmark must not execute devices")

    async def verify(_entity_id: str, _expected: str) -> bool:
        return True

    tmp = Path(tempfile.mkdtemp())
    runner = V10ProposalRunner(
        refresh=refresh, execute_service=never, verify=verify,  # type: ignore[arg-type]
        coordinator=ExecutionCoordinator(), goal_runs=None, options={},
    )
    engine = ProactiveContextEngine(
        ports, runner, config=ProactiveConfig(enabled=True),
        storage=GenerationalJsonFile(tmp / "bench.json"),
    )
    timings: dict[str, list[float]] = {
        "situation_evaluation": [], "opportunity": [], "priority": [],
        "communication_routing": [], "room_presence": [], "session_lookup": [],
    }
    opportunity = OpportunityPolicy()
    priority = PriorityPolicy()
    router = CommunicationRouter()
    attention = AttentionPolicy()
    attention_store = AttentionStateStore()
    proposals = ProposalStore()
    for index in range(60):
        proposals.create(
            situation_id=f"s{index}", recipient_user_ids=("philipp",), recipient_person_id=None,
            proposed_goal=ProposedGoal((TargetState("light.item_0", "off"),), ""),
            channel=CommunicationChannel.PUSH, privacy_level=PrivacyLevel.HOUSEHOLD,
            subject_label="x", question="?", now=NOW,
        )
    recipient = RecipientContext("philipp", "person.philipp", True, ("notify.p",))
    deliver = AttentionDecision(AttentionOutcome.DELIVER, ())
    garage = entities["cover.garage"]
    for iteration in range(args.warmup + args.iterations):
        record = iteration >= args.warmup
        situation = _situation(iteration)
        started = time.perf_counter()
        # Full event -> detection -> lifecycle -> forecast -> policies ->
        # attention -> routing -> proposal -> delivery (no device action).
        ports.clock = NOW + timedelta(minutes=20 + iteration)
        opened = replace(garage, entity_id="cover.garage", state="open" if iteration % 2 == 0 else "closed",
                         last_changed=NOW)
        entities["cover.garage"] = opened
        await engine.async_observe_state(opened, "closed", (opened,), nobody_home=False)
        elapsed_situation = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        opportunity.decide(situation, PriorityLevel.IMPORTANT, OpportunityContext(NOW))
        elapsed_opportunity = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        priority.decide(situation)
        elapsed_priority = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        decision = attention.decide(attention_store, recipient="philipp", dedupe_key=situation.dedupe_key,
                                    priority=PriorityLevel.IMPORTANT, requires_response=True, now=NOW)
        router.route(recipient, priority=PriorityLevel.IMPORTANT, privacy=PrivacyLevel.HOUSEHOLD,
                     room=RoomPresenceResult("person.philipp", "area_1", RoomEvidenceClass.EXACT, NOW, None),
                     satellites=ports.sat, attention=decision if decision.outcome else deliver,
                     quiet=False, requires_response=True, others_home=False)
        elapsed_routing = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        ports.room_for("person.philipp")
        elapsed_room = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        proposals.resolve_target(user_id="philipp", device_id="d1", now=NOW)
        elapsed_session = (time.perf_counter() - started) * 1000
        if record:
            timings["situation_evaluation"].append(elapsed_situation)
            timings["opportunity"].append(elapsed_opportunity)
            timings["priority"].append(elapsed_priority)
            timings["communication_routing"].append(elapsed_routing)
            timings["room_presence"].append(elapsed_room)
            timings["session_lookup"].append(elapsed_session)
    # Event storm: 1000 unrelated state changes.
    storm_start = time.perf_counter()
    before = len(engine.situations)
    for index in range(1000):
        noise = EntitySnapshot(f"sensor.noise_{index}", "n", "sensor", str(index))
        await engine.async_observe_state(noise, None, (noise,), nobody_home=False)
    storm_ms = (time.perf_counter() - storm_start) * 1000
    timings["event_storm_1000"] = [storm_ms]
    assert len(engine.situations) == before, "event storm created situations"
    return timings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--registry-size", type=int, default=5000)
    parser.add_argument("--max-event-storm-ms", type=float, default=1000.0)
    args = parser.parse_args()
    budgets = {
        "situation_evaluation": 100.0, "opportunity": 50.0, "priority": 20.0,
        "communication_routing": 20.0, "room_presence": 50.0, "session_lookup": 20.0,
        "event_storm_1000": args.max_event_storm_ms,
    }
    timings = asyncio.run(_run(args))
    failed = False
    for name, values in timings.items():
        p95 = _p95(values)
        print(f"{name}: median={statistics.median(values):.3f} ms p95={p95:.3f} ms budget={budgets[name]:.0f} ms")
        failed = failed or p95 > budgets[name]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
