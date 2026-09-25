"""V12 units: RoomPresenceResolver, SatelliteRegistry, CommunicationRouter, attention."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import _ha_stub

_ha_stub.install()

from homeintent.attention_policy import (  # noqa: E402
    MAX_GROUP_ITEMS,
    MAX_TRACKED_KEYS,
    AttentionConfig,
    AttentionPolicy,
    AttentionStateStore,
    GroupedItem,
)
from homeintent.communication_router import CommunicationRouter, RouterConfig  # noqa: E402
from homeintent.entities import EntitySnapshot  # noqa: E402
from homeintent.proactive_model import (  # noqa: E402
    AttentionDecision,
    AttentionOutcome,
    CommunicationChannel,
    PriorityLevel,
    PrivacyLevel,
    RecipientContext,
    RoomEvidenceClass,
    RoomPresenceResult,
    SatelliteRecord,
    SituationKind,
)
from homeintent.room_presence import (  # noqa: E402
    RoomPresenceConfig,
    RoomPresenceResolver,
    SatelliteRegistry,
    build_area_lookup,
    parse_mapping_lines,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _snap(entity_id: str, state: str, *, area: str | None = None, area_name: str | None = None,
          device_class: str | None = None) -> EntitySnapshot:
    return EntitySnapshot(entity_id, entity_id, entity_id.partition(".")[0], state,
                          area_id=area, area_name=area_name, device_class=device_class,
                          last_changed=NOW - timedelta(minutes=1))


AREAS = [
    _snap("light.a", "off", area="living_room", area_name="Wohnzimmer"),
    _snap("light.b", "off", area="kitchen", area_name="Küche"),
    _snap("light.c", "off", area="office", area_name="Büro"),
]


def _resolver(**sensors: tuple[str, ...]) -> RoomPresenceResolver:
    return RoomPresenceResolver(RoomPresenceConfig(person_room_sensors=dict(sensors)))


def _resolve(resolver, entities, *, home=True, others=()):
    by_id = {item.entity_id: item for item in (*AREAS, *entities)}
    return resolver.resolve(
        "person.philipp", person_home=home, entities=by_id,
        area_lookup=build_area_lookup(by_id.values()),
        home_person_ids=("person.philipp", *others), now=NOW,
    )


def test_home_presence_alone_never_yields_a_room():
    result = _resolve(_resolver(), [])
    assert result.evidence_class is RoomEvidenceClass.UNKNOWN and result.area_id is None


def test_not_home_is_unknown_room():
    resolver = _resolver(**{"person.philipp": ("sensor.philipp_area",)})
    result = _resolve(resolver, [_snap("sensor.philipp_area", "Wohnzimmer")], home=False)
    assert result.evidence_class is RoomEvidenceClass.UNKNOWN


def test_person_room_sensor_is_exact_and_maps_names_not_guesses():
    resolver = _resolver(**{"person.philipp": ("sensor.philipp_area",)})
    exact = _resolve(resolver, [_snap("sensor.philipp_area", "Wohnzimmer")])
    assert exact.evidence_class is RoomEvidenceClass.EXACT and exact.area_id == "living_room"
    by_id = _resolve(resolver, [_snap("sensor.philipp_area", "kitchen")])
    assert by_id.area_id == "kitchen"
    unmapped = _resolve(resolver, [_snap("sensor.philipp_area", "Dachterrasse")])
    assert unmapped.evidence_class is RoomEvidenceClass.AMBIGUOUS and unmapped.area_id is None
    unknown = _resolve(resolver, [_snap("sensor.philipp_area", "unknown")])
    assert unknown.evidence_class is RoomEvidenceClass.UNKNOWN


def test_conflicting_exact_sensors_are_ambiguous():
    resolver = _resolver(**{"person.philipp": ("sensor.ble", "sensor.mmwave")})
    result = _resolve(resolver, [_snap("sensor.ble", "Wohnzimmer"), _snap("sensor.mmwave", "Küche")])
    assert result.evidence_class is RoomEvidenceClass.AMBIGUOUS


def test_occupancy_is_strong_only_for_a_sole_person_and_single_area():
    occupied = [_snap("binary_sensor.occ_living", "on", area="living_room", device_class="occupancy")]
    alone = _resolve(_resolver(), occupied)
    assert alone.evidence_class is RoomEvidenceClass.STRONG and alone.area_id == "living_room"
    shared = _resolve(_resolver(), occupied, others=("person.anna",))
    assert shared.evidence_class is RoomEvidenceClass.UNKNOWN
    two = occupied + [_snap("binary_sensor.occ_kitchen", "on", area="kitchen", device_class="presence")]
    assert _resolve(_resolver(), two).evidence_class is RoomEvidenceClass.AMBIGUOUS


def test_recent_authenticated_turn_is_strong_and_expires():
    resolver = _resolver()
    resolver.record_interaction("person.philipp", "office", NOW - timedelta(minutes=2))
    assert _resolve(resolver, []).evidence_class is RoomEvidenceClass.STRONG
    resolver.record_interaction("person.philipp", "office", NOW - timedelta(minutes=20))
    assert _resolve(resolver, []).evidence_class is RoomEvidenceClass.UNKNOWN


def test_exact_conflicting_with_recent_turn_is_ambiguous():
    resolver = _resolver(**{"person.philipp": ("sensor.philipp_area",)})
    resolver.record_interaction("person.philipp", "office", NOW)
    result = _resolve(resolver, [_snap("sensor.philipp_area", "Wohnzimmer")])
    assert result.evidence_class is RoomEvidenceClass.AMBIGUOUS


def test_area_lookup_drops_conflicting_names():
    lookup = build_area_lookup([
        _snap("light.x", "off", area="a1", area_name="Bad"),
        _snap("light.y", "off", area="a2", area_name="Bad"),
    ])
    assert "Bad" not in lookup and "bad" not in lookup
    assert lookup["a1"] == "a1"


def test_satellite_registry_uniqueness_and_configuration():
    registry = SatelliteRegistry(
        [SatelliteRecord("assist_satellite.wz", "living_room", "d1"),
         SatelliteRecord("assist_satellite.k1", "kitchen", "d2"),
         SatelliteRecord("assist_satellite.k2", "kitchen", "d3")],
        {"assist_satellite.office": "office"},
    )
    assert registry.for_area("living_room").satellite.entity_id == "assist_satellite.wz"
    assert registry.for_area("kitchen").reason == "multiple_satellites_in_area"
    assert registry.for_area("bath").reason == "no_satellite_in_area"
    assert registry.for_area(None).reason == "no_area"
    assert registry.for_area("office").satellite.source == "homeintent_configuration"
    assert registry.by_device("d1").entity_id == "assist_satellite.wz"
    assert registry.by_device("unknown") is None
    # Explicit configuration overrides a registry area.
    moved = SatelliteRegistry([SatelliteRecord("assist_satellite.wz", "living_room", "d1")],
                              {"assist_satellite.wz": "office"})
    assert moved.for_area("living_room").satellite is None
    assert moved.for_area("office").satellite.device_id == "d1"


def test_mapping_lines_fail_closed():
    parsed = parse_mapping_lines(
        "person.philipp=sensor.a, sensor.b\nbroken line\nlight.x=sensor.c\nperson.anna=",
        key_prefix="person.",
    )
    assert parsed == {"person.philipp": ("sensor.a", "sensor.b")}
    assert parse_mapping_lines(None, key_prefix="") == {}


# -- router -------------------------------------------------------------------

PHILIPP = RecipientContext("philipp", "person.philipp", True, ("notify.p",))
SATS = SatelliteRegistry([SatelliteRecord("assist_satellite.wz", "living_room", "d1")])
DELIVER = AttentionDecision(AttentionOutcome.DELIVER, ())


def _room(cls: RoomEvidenceClass, area: str | None = "living_room") -> RoomPresenceResult:
    return RoomPresenceResult(
        "person.philipp",
        area if cls in {RoomEvidenceClass.EXACT, RoomEvidenceClass.STRONG} else None,
        cls, NOW, NOW + timedelta(minutes=10),
    )


def _route(recipient=PHILIPP, *, priority=PriorityLevel.IMPORTANT, privacy=PrivacyLevel.HOUSEHOLD,
           room=None, attention=DELIVER, quiet=False, response=True, others=False, config=None,
           now=NOW):
    return CommunicationRouter(config).route(
        recipient, priority=priority, privacy=privacy, room=room, satellites=SATS,
        attention=attention, quiet=quiet, requires_response=response, others_home=others,
        now=now,
    )


def test_router_exact_room_voice():
    decision = _route(room=_room(RoomEvidenceClass.EXACT))
    assert decision.channel is CommunicationChannel.VOICE
    assert decision.satellite_entity_id == "assist_satellite.wz"
    assert decision.continue_conversation is True
    assert decision.push_target_ids == ()


def test_router_away_and_ambiguous_fall_back_to_push():
    away = _route(RecipientContext("philipp", "person.philipp", False, ("notify.p",)),
                  room=_room(RoomEvidenceClass.EXACT))
    assert away.channel is CommunicationChannel.INTERACTIVE_PUSH
    assert "no_voice:recipient_not_home" in away.reasons
    ambiguous = _route(room=_room(RoomEvidenceClass.AMBIGUOUS))
    assert ambiguous.channel is CommunicationChannel.INTERACTIVE_PUSH
    assert ambiguous.satellite_entity_id is None
    unknown = _route(room=None, response=False)
    assert unknown.channel is CommunicationChannel.PUSH


def test_router_personal_content_in_shared_home_goes_private():
    shared = _route(privacy=PrivacyLevel.PERSONAL, room=_room(RoomEvidenceClass.EXACT), others=True)
    assert shared.channel is CommunicationChannel.INTERACTIVE_PUSH
    assert "no_voice:personal_audience_may_be_shared" in shared.reasons
    strong = _route(privacy=PrivacyLevel.PERSONAL, room=_room(RoomEvidenceClass.STRONG))
    assert strong.channel is CommunicationChannel.INTERACTIVE_PUSH
    alone = _route(privacy=PrivacyLevel.PERSONAL, room=_room(RoomEvidenceClass.EXACT))
    assert alone.channel is CommunicationChannel.VOICE
    sensitive = _route(privacy=PrivacyLevel.SENSITIVE, room=_room(RoomEvidenceClass.EXACT))
    assert sensitive.channel is CommunicationChannel.INTERACTIVE_PUSH


def test_router_no_private_channel_means_history():
    nobody = RecipientContext("philipp", "person.philipp", True, ())
    assert _route(nobody, room=None).channel is CommunicationChannel.HISTORY_ONLY
    ambiguous_push = RecipientContext("philipp", "person.philipp", True, ("notify.a", "notify.b"), True)
    decision = _route(ambiguous_push, room=None)
    assert decision.channel is CommunicationChannel.HISTORY_ONLY
    assert "push_target_ambiguous" in decision.reasons


def test_router_critical_multichannel_and_quiet():
    critical = _route(priority=PriorityLevel.CRITICAL, privacy=PrivacyLevel.PUBLIC,
                      room=_room(RoomEvidenceClass.EXACT), response=False, quiet=True)
    assert critical.channel is CommunicationChannel.MULTI_CHANNEL
    assert set(critical.channels) == {CommunicationChannel.PUSH, CommunicationChannel.VOICE}
    quiet_important = _route(room=_room(RoomEvidenceClass.EXACT), quiet=True)
    assert quiet_important.channel is CommunicationChannel.INTERACTIVE_PUSH
    assert "no_voice:quiet_hours" in quiet_important.reasons
    house = _route(priority=PriorityLevel.CRITICAL, privacy=PrivacyLevel.PUBLIC, room=None,
                   response=False, config=RouterConfig(house_speakers_configured=True))
    assert CommunicationChannel.VOICE in house.channels
    assert house.satellite_entity_id is None
    assert "critical_configured_house_speakers" in house.reasons


def test_router_honors_attention_and_voice_switches():
    suppressed = _route(attention=AttentionDecision(AttentionOutcome.SUPPRESS, ("recently_dismissed",)))
    assert suppressed.channel is CommunicationChannel.SUPPRESS
    deferred = _route(attention=AttentionDecision(AttentionOutcome.DEFER, ()))
    assert deferred.channel is CommunicationChannel.HISTORY_ONLY
    no_voice = _route(room=_room(RoomEvidenceClass.EXACT), config=RouterConfig(voice_enabled=False))
    assert no_voice.channel is CommunicationChannel.INTERACTIVE_PUSH
    no_room_voice = _route(room=_room(RoomEvidenceClass.EXACT), config=RouterConfig(room_aware_voice_enabled=False))
    assert no_room_voice.channel is CommunicationChannel.INTERACTIVE_PUSH


# -- attention ------------------------------------------------------------------

def test_attention_dedupe_budget_grouping_and_critical_bypass():
    store = AttentionStateStore()
    policy = AttentionPolicy(AttentionConfig(budget=3))
    decide = lambda key, priority, response=False, at=NOW: policy.decide(  # noqa: E731
        store, recipient="philipp", dedupe_key=key, priority=priority,
        requires_response=response, now=at,
    )
    assert decide("a", PriorityLevel.INFO).outcome is AttentionOutcome.DELIVER
    store.record_delivery("philipp", "a", NOW)
    assert decide("a", PriorityLevel.INFO).outcome is AttentionOutcome.SUPPRESS
    grouped = decide("b", PriorityLevel.INFO, at=NOW + timedelta(seconds=30))
    assert grouped.outcome is AttentionOutcome.GROUP and grouped.group_key == "philipp"
    assert decide("c", PriorityLevel.IMPORTANT, response=True, at=NOW + timedelta(seconds=30)).outcome is AttentionOutcome.DELIVER
    store.record_delivery("philipp", "x", NOW + timedelta(minutes=5))
    store.record_delivery("philipp", "y", NOW + timedelta(minutes=6))
    later = NOW + timedelta(minutes=20)
    assert decide("d", PriorityLevel.SUGGESTION, at=later).outcome is AttentionOutcome.DEFER
    assert decide("e", PriorityLevel.IMPORTANT, at=later).outcome is AttentionOutcome.DELIVER
    assert decide("f", PriorityLevel.CRITICAL, at=later).outcome is AttentionOutcome.BYPASS
    assert decide("g", PriorityLevel.URGENT, at=later).outcome is AttentionOutcome.BYPASS
    store.dismiss("h", later + timedelta(hours=1))
    assert decide("h", PriorityLevel.IMPORTANT, at=later).reasons == ("recently_dismissed",)
    assert decide("h", PriorityLevel.CRITICAL, at=later).outcome is AttentionOutcome.BYPASS


def test_attention_store_is_bounded_and_round_trips():
    store = AttentionStateStore()
    for index in range(MAX_TRACKED_KEYS + 50):
        store.record_delivery(f"user{index % 80}", f"key{index}", NOW + timedelta(seconds=index))
    assert len(store.to_dict()["key_last"]) == MAX_TRACKED_KEYS
    store.mute("philipp", SituationKind.APPLIANCE_FINISHED, NOW)
    restored = AttentionStateStore.from_dict(store.to_dict())
    assert restored.is_muted("philipp", SituationKind.APPLIANCE_FINISHED)
    assert not restored.is_muted("anna", SituationKind.APPLIANCE_FINISHED)
    assert AttentionStateStore.from_dict({"key_last": {"k": "not-a-date"}, "mutes": 5}).size == 0
    assert AttentionStateStore.from_dict("garbage").size == 0
    for index in range(MAX_GROUP_ITEMS + 3):
        store.add_to_group("philipp", GroupedItem(f"s{index}", "t"), NOW)
    assert store.group_size("philipp") == MAX_GROUP_ITEMS
    assert len(store.take_group("philipp")) == MAX_GROUP_ITEMS
    assert store.group_size("philipp") == 0
