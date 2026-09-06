"""Bridge HomeIntent timer language to Home Assistant's native Assist timers."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .agent_delivery import AgentDelivery
from .const import CONF_AGENT_MEDIA_PLAYERS, CONF_AGENT_TTS_ENTITY, DOMAIN
from .productivity import TimerOperation, TimerRequest, format_duration

_LOGGER = logging.getLogger(__name__)


class NativeTimerUnavailableError(ValueError):
    """Raised when no audible native or configured fallback target exists."""


class NativeTimerRuntime:
    """Use HA's TimerManager; HomeIntent never runs a parallel scheduler."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._fallback_device_id = f"{DOMAIN}:{entry.entry_id}"
        self._delivery = AgentDelivery(hass)
        self._unregister: Callable[[], None] | None = None

    def async_start(self) -> Callable[[], None]:
        """Register one synthetic timer device for configured TTS fallback."""
        try:
            from homeassistant.components.intent import async_register_timer_handler

            self._unregister = async_register_timer_handler(
                self._hass, self._fallback_device_id, self._handle_timer_event
            )
        except (ImportError, KeyError):
            _LOGGER.warning("Home Assistant's native Assist timer manager is unavailable")

        def stop() -> None:
            if self._unregister is not None:
                self._unregister()
                self._unregister = None

        return stop

    def _has_tts_fallback(self) -> bool:
        options: Mapping[str, object] = self._entry.options
        tts = options.get(CONF_AGENT_TTS_ENTITY)
        players = options.get(CONF_AGENT_MEDIA_PLAYERS)
        return (
            isinstance(tts, str)
            and bool(tts)
            and isinstance(players, (list, tuple))
            and any(isinstance(player, str) and player for player in players)
        )

    def _handle_timer_event(self, event_type: object, timer: object) -> None:
        if str(event_type) != "finished":
            return
        name = getattr(timer, "name", None)
        message = (
            f"{name}: Der Timer ist abgelaufen."
            if isinstance(name, str) and name.strip()
            else "Der Timer ist abgelaufen."
        )
        self._hass.async_create_task(
            self._async_announce(message),
            name="HomeIntent timer announcement",
        )

    async def _async_announce(self, message: str) -> None:
        try:
            await self._delivery.async_speak(message, self._entry.options)
        except Exception as err:  # noqa: BLE001 - HA service errors vary by provider
            _LOGGER.error("HomeIntent timer announcement failed: %s", err)

    async def _route_device(self, source_device_id: str | None) -> str:
        from homeassistant.components.intent import async_device_supports_timers

        if source_device_id and async_device_supports_timers(
            self._hass, source_device_id
        ):
            return source_device_id
        if self._unregister is not None and self._has_tts_fallback():
            return self._fallback_device_id
        raise NativeTimerUnavailableError(
            "Dieser Assist-Client kann keinen hörbaren Timer ausgeben. "
            "Konfiguriere in HomeIntent eine lokale TTS-Engine und mindestens "
            "einen Medienplayer."
        )

    @staticmethod
    def _duration_slots(seconds: int) -> dict[str, dict[str, object]]:
        hours, remainder = divmod(abs(seconds), 3600)
        minutes, remaining_seconds = divmod(remainder, 60)
        values = {"hours": hours, "minutes": minutes, "seconds": remaining_seconds}
        slots: dict[str, dict[str, object]] = {
            key: {"value": value}
            for key, value in values.items()
            if value
        }
        if not slots:
            slots["seconds"] = {"value": 0}
        return slots

    async def async_execute(self, request: TimerRequest, user_input: object) -> str:
        """Execute a parsed request through HA's registered timer intents."""
        from homeassistant.helpers import intent

        device_id = await self._route_device(getattr(user_input, "device_id", None))
        operation = request.operation
        if operation is TimerOperation.START:
            intent_type = intent.INTENT_START_TIMER
        elif operation is TimerOperation.CHANGE:
            intent_type = (
                intent.INTENT_INCREASE_TIMER
                if (request.change_seconds or 0) >= 0
                else intent.INTENT_DECREASE_TIMER
            )
        elif operation is TimerOperation.PAUSE:
            intent_type = intent.INTENT_PAUSE_TIMER
        elif operation is TimerOperation.RESUME:
            intent_type = intent.INTENT_UNPAUSE_TIMER
        elif operation in {TimerOperation.CANCEL, TimerOperation.FINISH}:
            intent_type = intent.INTENT_CANCEL_TIMER
        else:
            intent_type = intent.INTENT_TIMER_STATUS
        slots: dict[str, dict[str, object]] = {}
        seconds = int(
            (request.duration_seconds or 0)
            if operation is TimerOperation.START
            else abs(request.change_seconds or 0)
        )
        if operation in {TimerOperation.START, TimerOperation.CHANGE}:
            if not seconds:
                raise ValueError("Für den Timer fehlt eine gültige Dauer.")
            slots.update(self._duration_slots(seconds))
        if request.name:
            slots["name"] = {"value": request.name}
        native_response = await intent.async_handle(
            self._hass,
            DOMAIN,
            intent_type,
            slots,
            getattr(user_input, "text", None),
            getattr(user_input, "context", None),
            language=getattr(user_input, "language", "de"),
            assistant="conversation",
            device_id=device_id,
            satellite_id=getattr(user_input, "satellite_id", None),
            conversation_agent_id=getattr(user_input, "agent_id", None),
        )
        label = f" „{request.name}“" if request.name else ""
        if operation is TimerOperation.START:
            return f"Timer{label} für {format_duration(seconds)} gestartet."
        if operation is TimerOperation.CHANGE:
            verb = "verlängert" if (request.change_seconds or 0) > 0 else "verkürzt"
            return f"Timer{label} um {format_duration(seconds)} {verb}."
        return {
            TimerOperation.PAUSE: f"Timer{label} pausiert.",
            TimerOperation.RESUME: f"Timer{label} fortgesetzt.",
            TimerOperation.CANCEL: f"Timer{label} abgebrochen.",
            TimerOperation.FINISH: f"Timer{label} beendet.",
            TimerOperation.STATUS: self._status_speech(native_response),
        }[operation]

    @staticmethod
    def _status_speech(native_response: object) -> str:
        speech_slots = getattr(native_response, "speech_slots", {})
        timers = speech_slots.get("timers") if isinstance(speech_slots, dict) else None
        if not isinstance(timers, list) or not timers:
            return "Es läuft kein passender Timer."
        rendered: list[str] = []
        for item in timers[:3]:
            if not isinstance(item, dict):
                continue
            seconds = item.get("total_seconds_left")
            if not isinstance(seconds, int):
                continue
            name = item.get("name")
            prefix = f"{name}: " if isinstance(name, str) and name else ""
            state = "verbleiben" if item.get("is_active", True) else "pausiert, verbleibend"
            rendered.append(f"{prefix}{state} {format_duration(seconds)}")
        if not rendered:
            return "Der Timerstatus ist derzeit nicht verfügbar."
        suffix = " Weitere Timer nenne ich auf Nachfrage." if len(timers) > 3 else ""
        return "; ".join(rendered) + "." + suffix
