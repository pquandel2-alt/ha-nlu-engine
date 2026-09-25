"""7.0.1: room presence is time-bounded evidence; stale evidence never selects voice."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import timedelta

from v12_harness import NOW, build_world, garage_states, living_satellite, philipp

from homeintent.communication_router import CommunicationRouter
from homeintent.entities import EntitySnapshot
from homeintent.proactive_model import (
    AttentionDecision,
    AttentionOutcome,
    CommunicationChannel,
    PriorityLevel,
    PrivacyLevel,
    RecipientContext,
    RoomEvidenceClass,
    RoomPresenceResult,
    SatelliteRecord,
)
from homeintent.room_presence import (
    RoomPresenceConfig,
    RoomPresenceResolver,
    SatelliteRegistry,
    build_area_lookup,
)

TTL = timedelta(minutes=10)
AREAS = [
    EntitySnapshot("light.a", "a", "light", "off", area_id="living_room", area_name="Wohnzimmer"),
    EntitySnapshot("light.b", "b", "light", "off", area_id="kitchen", area_name="Küche"),
]
LOOKUP = build_area_lookup(AREAS)


def _sensor(state: str, *, changed=None, updated=None) -> EntitySnapshot:
    return EntitySnapshot("sensor.philipp_area", "Philipp Raum", "sensor", state,
                          last_changed=changed, last_updated=updated)


def _resolver() -> RoomPresenceResolver:
    return RoomPresenceResolver(RoomPresenceConfig(
        person_room_sensors={"person.philipp": ("sensor.philipp_area",)},
        evidence_validity=TTL,
    ))


def _resolve(resolver, entities, now, *, others=()):
    return resolver.resolve(
        "person.philipp", person_home=True,
        entities={item.entity_id: item for item in (*AREAS, *entities)},
        area_lookup=LOOKUP, home_person_ids=("person.philipp", *others), now=now,
    )


def test_fresh_person_room_sensor_is_exact():
    result = _resolve(_resolver(), [_sensor("Wohnzimmer", changed=NOW - timedelta(minutes=2))], NOW)
    assert result.evidence_class is RoomEvidenceClass.EXACT and result.area_id == "living_room"


def test_stale_person_room_sensor_is_not_exact():
    stale = _sensor("Wohnzimmer", changed=NOW - timedelta(hours=3), updated=NOW - timedelta(hours=3))
    result = _resolve(_resolver(), [stale], NOW)
    assert result.evidence_class is RoomEvidenceClass.UNKNOWN and result.area_id is None


def test_room_sensor_valid_until_is_based_on_observed_at():
    observed = NOW - timedelta(minutes=4)
    result = _resolve(_resolver(), [_sensor("Wohnzimmer", changed=NOW - timedelta(hours=1), updated=observed)], NOW)
    assert result.observed_at == observed
    assert result.valid_until == observed + TTL


def test_repeated_resolution_does_not_refresh_stale_evidence():
    resolver = _resolver()
    sensor = _sensor("Wohnzimmer", changed=NOW)
    assert _resolve(resolver, [sensor], NOW).evidence_class is RoomEvidenceClass.EXACT
    for minutes in (5, 9):
        assert _resolve(resolver, [sensor], NOW + timedelta(minutes=minutes)).valid_until == NOW + TTL
    for minutes in (11, 30, 180):
        assert _resolve(resolver, [sensor], NOW + timedelta(minutes=minutes)).evidence_class is RoomEvidenceClass.UNKNOWN


def test_untrustworthy_timestamps_are_not_evidence():
    assert _resolve(_resolver(), [_sensor("Wohnzimmer")], NOW).evidence_class is RoomEvidenceClass.UNKNOWN
    naive = _sensor("Wohnzimmer", changed=NOW.replace(tzinfo=None))
    assert _resolve(_resolver(), [naive], NOW).evidence_class is RoomEvidenceClass.UNKNOWN
    future = _sensor("Wohnzimmer", changed=NOW + timedelta(hours=1))
    assert _resolve(_resolver(), [future], NOW).evidence_class is RoomEvidenceClass.UNKNOWN


def test_fresh_authenticated_satellite_turn_is_strong():
    resolver = _resolver()
    resolver.record_interaction("person.philipp", "kitchen", NOW - timedelta(minutes=1))
    result = _resolve(resolver, [], NOW)
    assert result.evidence_class is RoomEvidenceClass.STRONG and result.area_id == "kitchen"
    assert result.valid_until == NOW - timedelta(minutes=1) + RoomPresenceConfig().interaction_validity


def test_expired_authenticated_satellite_turn_is_unknown():
    resolver = _resolver()
    resolver.record_interaction("person.philipp", "kitchen", NOW - timedelta(minutes=6))
    assert _resolve(resolver, [], NOW).evidence_class is RoomEvidenceClass.UNKNOWN


def test_conflicting_fresh_room_sources_are_ambiguous():
    resolver = _resolver()
    resolver.record_interaction("person.philipp", "kitchen", NOW - timedelta(seconds=20))
    sensor = _sensor("Wohnzimmer", changed=NOW - timedelta(seconds=30))
    result = _resolve(resolver, [sensor], NOW)
    assert result.evidence_class is RoomEvidenceClass.AMBIGUOUS and result.area_id is None


def test_stale_occupancy_is_not_strong():
    occupied = EntitySnapshot("binary_sensor.occ", "occ", "binary_sensor", "on", area_id="kitchen",
                              device_class="occupancy", last_changed=NOW - timedelta(hours=2))
    assert _resolve(_resolver(), [occupied], NOW).evidence_class is RoomEvidenceClass.UNKNOWN
    fresh = replace(occupied, last_updated=NOW - timedelta(minutes=1))
    assert _resolve(_resolver(), [fresh], NOW).evidence_class is RoomEvidenceClass.STRONG


# -- router defense in depth --------------------------------------------------

SATS = SatelliteRegistry([SatelliteRecord("assist_satellite.wz", "living_room", "d1")])
DELIVER = AttentionDecision(AttentionOutcome.DELIVER, ())
PHILIPP = RecipientContext("philipp", "person.philipp", True, ("notify.p",))


def _route(room, *, privacy=PrivacyLevel.HOUSEHOLD, now=NOW):
    return CommunicationRouter().route(
        PHILIPP, priority=PriorityLevel.IMPORTANT, privacy=privacy, room=room, satellites=SATS,
        attention=DELIVER, quiet=False, requires_response=True, others_home=False, now=now,
    )


def _exact(valid_until):
    return RoomPresenceResult("person.philipp", "living_room", RoomEvidenceClass.EXACT,
                              NOW - timedelta(minutes=1), valid_until)


def test_stale_exact_room_routes_to_push():
    assert _route(_exact(NOW + TTL)).channel is CommunicationChannel.VOICE
    stale = _route(_exact(NOW - timedelta(seconds=1)))
    assert stale.channel is CommunicationChannel.INTERACTIVE_PUSH
    assert "no_voice:room_evidence_expired" in stale.reasons
    later = _route(_exact(NOW + TTL), now=NOW + TTL + timedelta(seconds=1))
    assert later.channel is CommunicationChannel.INTERACTIVE_PUSH
    unbounded = _route(_exact(None))
    assert "no_voice:room_evidence_unbounded" in unbounded.reasons


def test_stale_personal_room_evidence_never_routes_voice():
    for privacy in (PrivacyLevel.PERSONAL, PrivacyLevel.SENSITIVE):
        decision = _route(_exact(NOW - timedelta(minutes=1)), privacy=privacy)
        assert decision.channel is CommunicationChannel.INTERACTIVE_PUSH
        assert decision.satellite_entity_id is None


def test_unknown_room_does_not_guess_satellite():
    for room in (None, RoomPresenceResult("person.philipp", None, RoomEvidenceClass.UNKNOWN, None, None),
                 RoomPresenceResult("person.philipp", None, RoomEvidenceClass.AMBIGUOUS, NOW, NOW + TTL)):
        decision = _route(room)
        assert decision.satellite_entity_id is None
        assert decision.channel is CommunicationChannel.INTERACTIVE_PUSH


# -- engine end to end ------------------------------------------------------------

def _world(tmp_path, room):
    world = build_world(
        tmp_path, garage_states(), recipients={"philipp": philipp()},
        rooms={"person.philipp": room}, satellite_records=[living_satellite()],
        household={"person.philipp": "home", "person.anna": "not_home"},
    )
    world.ports.frozen_rooms.add("person.philipp")
    return world


def test_stale_room_in_engine_never_speaks_and_fresh_room_does(tmp_path):
    stale = _world(tmp_path / "stale", _exact(NOW + timedelta(minutes=5)))
    fresh = _world(tmp_path / "fresh", _exact(NOW + timedelta(hours=1)))

    async def scenario(world):
        await world.change("cover.garage", "open")
        await world.ports.advance(timedelta(minutes=15))

    asyncio.run(scenario(stale))
    assert stale.spoken() == [] and stale.ports.delivered[-1].decision.channel is CommunicationChannel.INTERACTIVE_PUSH
    assert stale.sink.device_calls == []
    asyncio.run(scenario(fresh))
    assert fresh.ports.delivered[-1].decision.channel is CommunicationChannel.VOICE
    assert fresh.sink.device_calls == []


def test_room_presence_is_not_persisted_so_restart_has_no_stale_authority(tmp_path):
    world = _world(tmp_path, _exact(NOW + TTL))

    async def scenario():
        await world.change("cover.garage", "open")
        await world.engine.async_persist()

    asyncio.run(scenario())
    document = json.loads((tmp_path / "proactive.json").read_text(encoding="utf-8"))
    text = json.dumps(document)
    assert "room" not in document and "person_room" not in text and "interaction" not in text
    resolver = _resolver()  # a fresh process: no remembered satellite turns
    assert _resolve(resolver, [], NOW).evidence_class is RoomEvidenceClass.UNKNOWN
