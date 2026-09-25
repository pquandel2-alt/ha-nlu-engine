"""V12 communication routing: which channel, which target, never which device.

The router only *decides*.  Transport stays with the existing
``AgentDelivery`` (push/TTS) and Home Assistant's own ``assist_satellite``
services.  Safe fallback beats always speaking:

* exact room + unique satellite + suitable privacy  -> VOICE
* ambiguous/unknown room, no/multiple satellites     -> (interactive) PUSH
* personal content with a possibly shared audience   -> PUSH
* no private channel either                          -> HISTORY_ONLY
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .proactive_model import (
    AttentionDecision,
    AttentionOutcome,
    CommunicationChannel,
    CommunicationDecision,
    PriorityLevel,
    PrivacyLevel,
    RecipientContext,
    RoomEvidenceClass,
    RoomPresenceResult,
)
from .room_presence import SatelliteRegistry


@dataclass(frozen=True)
class RouterConfig:
    voice_enabled: bool = True
    push_enabled: bool = True
    room_aware_voice_enabled: bool = True
    critical_multi_channel_enabled: bool = True
    house_speakers_configured: bool = False


class CommunicationRouter:
    def __init__(self, config: RouterConfig | None = None) -> None:
        self.config = config or RouterConfig()

    def route(
        self,
        recipient: RecipientContext,
        *,
        priority: PriorityLevel,
        privacy: PrivacyLevel,
        room: RoomPresenceResult | None,
        satellites: SatelliteRegistry,
        attention: AttentionDecision,
        quiet: bool,
        requires_response: bool,
        others_home: bool,
        now: datetime,
    ) -> CommunicationDecision:
        reasons: list[str] = []
        if attention.outcome is AttentionOutcome.SUPPRESS:
            return self._decision(CommunicationChannel.SUPPRESS, (), recipient, None, (),
                                  requires_response, (*attention.reasons,))
        if attention.outcome in {AttentionOutcome.DEFER, AttentionOutcome.GROUP}:
            return self._decision(CommunicationChannel.HISTORY_ONLY, (), recipient, None, (),
                                  requires_response, (*attention.reasons,))
        critical = priority >= PriorityLevel.URGENT
        push_targets = (
            recipient.push_target_ids
            if self.config.push_enabled and not recipient.push_ambiguous
            else ()
        )
        if recipient.push_ambiguous:
            reasons.append("push_target_ambiguous")
        satellite_id: str | None = None
        voice_reason = self._voice_block_reason(
            recipient, privacy=privacy, room=room, quiet=quiet and not critical,
            others_home=others_home, now=now,
        )
        if voice_reason is None and room is not None:
            resolution = satellites.for_area(room.area_id)
            if resolution.satellite is None:
                voice_reason = resolution.reason
            else:
                satellite_id = resolution.satellite.entity_id
        if voice_reason is not None:
            reasons.append(f"no_voice:{voice_reason}")
        if critical:
            channels: list[CommunicationChannel] = []
            if push_targets:
                channels.append(CommunicationChannel.PUSH)
            if satellite_id is not None:
                channels.append(CommunicationChannel.VOICE)
            elif (
                self.config.critical_multi_channel_enabled
                and self.config.house_speakers_configured
                and privacy is PrivacyLevel.PUBLIC
            ):
                channels.append(CommunicationChannel.VOICE)
                reasons.append("critical_configured_house_speakers")
            if not channels:
                return self._decision(CommunicationChannel.HISTORY_ONLY, (), recipient, None, (),
                                      requires_response, (*reasons, "no_channel_available"))
            channel = (
                CommunicationChannel.MULTI_CHANNEL if len(channels) > 1 else channels[0]
            )
            return self._decision(channel, tuple(channels), recipient, satellite_id,
                                  push_targets, requires_response,
                                  (*reasons, "critical_route"))
        if satellite_id is not None:
            return self._decision(CommunicationChannel.VOICE, (CommunicationChannel.VOICE,),
                                  recipient, satellite_id, push_targets, requires_response,
                                  (*reasons, "exact_room_unique_satellite"))
        if push_targets:
            channel = (
                CommunicationChannel.INTERACTIVE_PUSH if requires_response
                else CommunicationChannel.PUSH
            )
            return self._decision(channel, (channel,), recipient, None, push_targets,
                                  requires_response, (*reasons, "private_push_fallback"))
        return self._decision(CommunicationChannel.HISTORY_ONLY, (), recipient, None, (),
                              requires_response, (*reasons, "no_private_channel"))

    def _voice_block_reason(
        self,
        recipient: RecipientContext,
        *,
        privacy: PrivacyLevel,
        room: RoomPresenceResult | None,
        quiet: bool,
        others_home: bool,
        now: datetime,
    ) -> str | None:
        if not (self.config.voice_enabled and self.config.room_aware_voice_enabled):
            return "voice_disabled"
        if recipient.home is not True:
            return "recipient_not_home"
        if quiet:
            return "quiet_hours"
        if room is not None and room.evidence_class is RoomEvidenceClass.AMBIGUOUS:
            return "room_ambiguous"
        if room is None or room.area_id is None or room.evidence_class is RoomEvidenceClass.UNKNOWN:
            return "room_unknown"
        # Defense in depth: even a caller-supplied result must still be valid.
        if room.valid_until is None:
            return "room_evidence_unbounded"
        if now > room.valid_until:
            return "room_evidence_expired"
        if privacy is PrivacyLevel.SENSITIVE:
            return "sensitive_content"
        if privacy is PrivacyLevel.PERSONAL:
            if room.evidence_class is not RoomEvidenceClass.EXACT:
                return "personal_requires_exact_room"
            if others_home:
                return "personal_audience_may_be_shared"
        return None

    @staticmethod
    def _decision(
        channel: CommunicationChannel,
        channels: tuple[CommunicationChannel, ...],
        recipient: RecipientContext,
        satellite_id: str | None,
        push_targets: tuple[str, ...],
        requires_response: bool,
        reasons: tuple[str, ...],
    ) -> CommunicationDecision:
        voice = CommunicationChannel.VOICE in channels
        return CommunicationDecision(
            channel,
            channels,
            recipient.user_id,
            satellite_id if voice else None,
            push_targets if any(
                item in {CommunicationChannel.PUSH, CommunicationChannel.INTERACTIVE_PUSH}
                for item in channels
            ) else (),
            requires_response,
            voice and requires_response and satellite_id is not None,
            reasons,
        )


__all__ = ("CommunicationRouter", "RouterConfig")
