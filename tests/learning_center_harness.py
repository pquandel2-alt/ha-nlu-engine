"""Shared harness for the 7.1 Learning Center tests.

Adds the few Home Assistant modules the Learning Center glue imports
(``websocket_api``, ``http``, ``frontend``, ``panel_custom``) on top of
``_ha_stub`` and builds a runtime from the REAL V11/V12 authorities
(``ModelRegistry``, ``ExperienceStore``, ``LearningManager``,
``StandingPermissionStore``, ``AttentionStateStore``,
``ProactiveHistoryStore``, ``ProfileStore``).  Every device service call is
counted by ``hass.services.async_call`` (an ``AsyncMock``).

Test users are generic (``user_a``, ``user_b``, ``admin``).
"""

from __future__ import annotations

import asyncio
import inspect
import sys
import types
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import voluptuous as vol  # noqa: E402


def _install_learning_center_stubs() -> None:
    core = sys.modules["homeassistant.core"]
    if not hasattr(core, "callback"):
        core.callback = lambda func: func  # type: ignore[attr-defined]
    components = sys.modules["homeassistant.components"]
    if "homeassistant.components.websocket_api" not in sys.modules:
        websocket_api = types.ModuleType("homeassistant.components.websocket_api")

        def websocket_command(schema: dict[Any, Any]):
            def decorate(func):
                func._ws_command = schema[vol.Required("type")] if vol.Required("type") in schema else schema["type"]
                func._ws_schema = vol.Schema({vol.Required("id"): int, **schema})
                return func
            return decorate

        def async_response(func):
            return func

        def async_register_command(hass: Any, handler: Any) -> None:
            hass.data.setdefault("_ws_commands", {})[handler._ws_command] = handler

        def event_message(iden: int, event: Any) -> dict[str, Any]:
            return {"id": iden, "type": "event", "event": event}

        websocket_api.websocket_command = websocket_command
        websocket_api.async_response = async_response
        websocket_api.async_register_command = async_register_command
        websocket_api.event_message = event_message
        sys.modules["homeassistant.components.websocket_api"] = websocket_api
        components.websocket_api = websocket_api
    if "homeassistant.components.http" not in sys.modules:
        http = types.ModuleType("homeassistant.components.http")

        @dataclass(frozen=True)
        class StaticPathConfig:
            url_path: str
            path: str
            cache_headers: bool = True

        http.StaticPathConfig = StaticPathConfig
        sys.modules["homeassistant.components.http"] = http
        components.http = http
    if "homeassistant.components.panel_custom" not in sys.modules:
        panel_custom = types.ModuleType("homeassistant.components.panel_custom")

        async def async_register_panel(hass: Any, **kwargs: Any) -> None:
            panels = hass.data.setdefault("frontend_panels", {})
            if kwargs["frontend_url_path"] in panels:
                raise ValueError(f"Overwriting panel {kwargs['frontend_url_path']}")
            panels[kwargs["frontend_url_path"]] = kwargs

        panel_custom.async_register_panel = async_register_panel
        sys.modules["homeassistant.components.panel_custom"] = panel_custom
        components.panel_custom = panel_custom
    if "homeassistant.components.frontend" not in sys.modules:
        frontend = types.ModuleType("homeassistant.components.frontend")

        def async_remove_panel(hass: Any, frontend_url_path: str, *, warn_if_unknown: bool = True) -> None:
            hass.data.setdefault("frontend_panels", {}).pop(frontend_url_path, None)

        frontend.async_remove_panel = async_remove_panel
        sys.modules["homeassistant.components.frontend"] = frontend
        components.frontend = frontend


_install_learning_center_stubs()

from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant, State  # noqa: E402

from homeintent import learning_center_ws  # noqa: E402
from homeintent.attention_policy import AttentionStateStore  # noqa: E402
from homeintent.experience_store import ExperienceStore  # noqa: E402
from homeintent.goal_model import GoalKind, GoalModel  # noqa: E402
from homeintent.goal_run import (  # noqa: E402
    FailureCode,
    GoalRun,
    GoalRunStatus,
    StepExecutionRecord,
    VerificationRecord,
)
from homeintent.learning_manager import LearningManager  # noqa: E402
from homeintent.learning_policy import KnowledgeState, LearningMode, LearningPolicy  # noqa: E402
from homeintent.model_registry import (  # noqa: E402
    LearnedKind,
    LearnedModel,
    ModelHealth,
    ModelRegistry,
)
from homeintent.predictive_house_model import PredictiveHouseModel  # noqa: E402
from homeintent.proactive_engine import ProactiveConfig  # noqa: E402
from homeintent.proactive_model import (  # noqa: E402
    AutoOperator,
    PermissionCondition,
    SituationKind,
    StandingPermission,
)
from homeintent.proactive_store import ProactiveHistoryStore  # noqa: E402
from homeintent.profiles import ProfileStore  # noqa: E402
from homeintent.runtime_data import HomeIntentRuntimeData  # noqa: E402
from homeintent.standing_permission import StandingPermissionStore  # noqa: E402


NOW = datetime.now(timezone.utc).replace(microsecond=0)
USER_A = "user_a"
USER_B = "user_b"
ADMIN = "admin"


def policy() -> LearningPolicy:
    return replace(LearningPolicy(
        learning_mode=LearningMode.ASK,
        predictive_models_enabled=True,
        habit_discovery_enabled=True,
    ), minimum_model_samples=2, usable_model_samples=5)


class FakeProactiveEngine:
    """The REAL V12 stores behind a minimal engine surface."""

    def __init__(self) -> None:
        self.permissions = StandingPermissionStore()
        self.attention_state = AttentionStateStore()
        self.history = ProactiveHistoryStore()
        self.config = ProactiveConfig(enabled=True, standing_permissions_enabled=True)
        self.persist_listeners: list[Any] = []
        self.persist_count = 0

    async def async_persist(self) -> None:
        self.persist_count += 1
        for listener in tuple(self.persist_listeners):
            listener()


@dataclass
class User:
    id: str
    name: str
    is_admin: bool = False


class FakeConnection:
    def __init__(self, user: User | None) -> None:
        self.user = user
        self.results: dict[int, Any] = {}
        self.errors: dict[int, tuple[str, str]] = {}
        self.events: list[dict[str, Any]] = []
        self.subscriptions: dict[Any, Any] = {}

    def send_result(self, msg_id: int, result: Any = None) -> None:
        self.results[msg_id] = result

    def send_error(self, msg_id: int, code: str, message: str) -> None:
        self.errors[msg_id] = (code, message)

    def send_message(self, message: dict[str, Any]) -> None:
        self.events.append(message)


class FakeConfigEntries:
    def __init__(self) -> None:
        self.entries: list[Any] = []
        self.updates: list[dict[str, Any]] = []

    def async_loaded_entries(self, domain: str) -> list[Any]:
        return list(self.entries)

    def async_entries(self, domain: str) -> list[Any]:
        return list(self.entries)

    def async_update_entry(self, entry: Any, *, options: dict[str, Any]) -> None:
        entry.options = options
        self.updates.append(options)


class FakeHttp:
    def __init__(self) -> None:
        self.static: list[Any] = []

    async def async_register_static_paths(self, configs: list[Any]) -> None:
        for config in configs:
            if any(item.url_path == config.url_path for item in self.static):
                raise RuntimeError("route already registered")
            self.static.append(config)


USERS = {
    USER_A: User(USER_A, "Anna"),
    USER_B: User(USER_B, "Ben"),
    ADMIN: User(ADMIN, "Admin", True),
}


@dataclass
class Env:
    hass: Any
    entry: Any
    registry: ModelRegistry
    experiences: ExperienceStore
    manager: LearningManager
    house: PredictiveHouseModel
    engine: FakeProactiveEngine
    profiles: ProfileStore
    runtime: HomeIntentRuntimeData
    next_id: int = 1
    connections: dict[str, FakeConnection] = field(default_factory=dict)

    def conn(self, user_id: str | None) -> FakeConnection:
        key = user_id or "<anon>"
        if key not in self.connections:
            self.connections[key] = FakeConnection(USERS.get(user_id) if user_id else None)
        return self.connections[key]

    async def call(self, caller: str | None, command: str, /, **payload: Any) -> tuple[Any, tuple[str, str] | None]:
        """Dispatch like HA: schema validation, then the registered handler."""
        msg_id = self.next_id
        self.next_id += 1
        connection = self.conn(caller)
        message = {"id": msg_id, "type": f"homeintent/learning_center/{command}", **payload}
        handler = self.hass.data["_ws_commands"].get(message["type"])
        if handler is None:
            return None, ("unknown_command", "unknown_command")
        try:
            validated = handler._ws_schema(message)
        except vol.Invalid as err:
            return None, ("invalid_format", str(err))
        outcome = handler(self.hass, connection, validated)
        if inspect.isawaitable(outcome):
            await outcome
        return connection.results.get(msg_id), connection.errors.get(msg_id)

    def service_calls(self) -> int:
        return self.hass.services.async_call.await_count + self.hass.services.async_call.call_count


def make_hass(entities: dict[str, str] | None = None) -> Any:
    hass = HomeAssistant()
    hass.config_entries = FakeConfigEntries()
    hass.http = FakeHttp()

    async def _get_users() -> list[User]:
        return list(USERS.values())

    hass.auth = types.SimpleNamespace(async_get_users=_get_users)
    for entity_id, name in (entities or {}).items():
        hass.states._states[entity_id] = State(entity_id, "off", {"friendly_name": name})
        hass.states._states[entity_id].name = name
    return hass


DEFAULT_ENTITIES = {
    "light.kitchen": "Küchenlicht",
    "light.living": "Wohnzimmerlicht",
    "light.floor_lamp": "Stehlampe",
    "cover.kitchen": "Rollladen Küche",
    "switch.coffee": "Kaffeemaschine",
    "climate.living": "Heizung Wohnzimmer",
}


async def make_env(tmp_path: Path, *, entities: dict[str, str] | None = None,
                   hass: Any = None, entry_id: str = "entry-1") -> Env:
    hass = hass or make_hass(DEFAULT_ENTITIES if entities is None else entities)
    learning_policy = policy()
    registry = ModelRegistry(tmp_path / f"{entry_id}-models.json", learning_policy)
    experiences = ExperienceStore(tmp_path / f"{entry_id}-experiences.json", learning_policy)
    house = PredictiveHouseModel(learning_policy)
    manager = LearningManager(experiences, registry, house, learning_policy)
    profiles = ProfileStore(tmp_path / f"{entry_id}-profiles.json")
    engine = FakeProactiveEngine()
    runtime = HomeIntentRuntimeData(
        learning_policy=learning_policy, experiences=experiences,
        learned_models=registry, predictive_house=house, learning_manager=manager,
        profiles=profiles,
    )
    runtime.proactive_context = types.SimpleNamespace(engine=engine)
    entry = ConfigEntry(entry_id=entry_id)
    entry.runtime_data = runtime
    hass.config_entries.entries.append(entry)
    await learning_center_ws.async_setup_learning_center(hass, entry)
    return Env(hass, entry, registry, experiences, manager, house, engine, profiles, runtime)


# -- model / evidence builders -------------------------------------------------------

def goal_run(run_id: str, *, entity_id: str = "light.kitchen", operator: str = "LIGHT_TURN_ON",
             accepted: bool | None = True, observed: str | None = "on", expected: str = "on",
             user_id: str | None = USER_A, at: datetime | None = None,
             latency: float = 2.0) -> GoalRun:
    """A GoalRun as conversation.py records it (V11 evidence semantics)."""
    when = at or NOW - timedelta(hours=1)
    accepted_at = when - timedelta(seconds=latency)
    verification: tuple[VerificationRecord, ...] = ()
    if accepted is not False and observed is not None:
        verification = (VerificationRecord(
            entity_id, expected, observed, observed == expected,
            None if observed == expected else FailureCode.WRONG_STATE, when.isoformat(),
        ),)
    status = GoalRunStatus.SUCCESS if (accepted is not False and observed in {None, expected}) else GoalRunStatus.FAILURE
    return GoalRun(
        run_id, f"goal-{run_id}", when.isoformat(), when.isoformat(), "", user_id, None,
        GoalModel(GoalKind.ACHIEVE_STATE, goal_id=f"goal-{run_id}"), "plan",
        (entity_id,), (), True,
        (StepExecutionRecord(
            "step", operator, (entity_id,), (), accepted, verification,
            FailureCode.SERVICE_ERROR if accepted is False else None, "",
            when.isoformat() if accepted else None, accepted_at.isoformat() if accepted else None,
            accepted_at.isoformat() if accepted else None,
        ),), (), status,
    )


async def learn_reliability(env: Env, *, successes: int, failures: int,
                            noops: int = 0, unverified: int = 0,
                            entity_id: str = "light.kitchen") -> None:
    """Drive the real LearningManager with mixed evidence."""
    index = 0
    base = NOW - timedelta(days=2)
    for kind, count in (("ok", successes), ("fail", failures), ("noop", noops), ("unverified", unverified)):
        for _ in range(count):
            index += 1
            at = base + timedelta(minutes=index)
            if kind == "ok":
                run = goal_run(f"r{index}", entity_id=entity_id, at=at, user_id=None)
            elif kind == "fail":
                run = goal_run(f"r{index}", entity_id=entity_id, observed="off", at=at, user_id=None)
            elif kind == "noop":
                run = goal_run(f"r{index}", entity_id=entity_id, accepted=None, observed="on", at=at, user_id=None)
            else:
                run = goal_run(f"r{index}", entity_id=entity_id, observed=None, at=at, user_id=None)
            await env.manager.async_observe_goal_run(run)


def preference_model(owner: str, *, concept: str = "lampe", area: str | None = "living",
                     state: KnowledgeState = KnowledgeState.INFERRED,
                     entity_id: str = "light.floor_lamp", counts: dict[str, int] | None = None,
                     health: ModelHealth = ModelHealth.VALID) -> LearnedModel:
    selections = counts or {entity_id: 8, "light.living": 2}
    return LearnedModel(
        f"preference:{owner}:{concept}:{area}", LearnedKind.PREFERENCE, concept,
        {"user_id": owner, **({"area_id": area} if area else {})},
        {**{f"count:{key}": value for key, value in selections.items()},
         "entity_id": entity_id, "support_count": selections[entity_id], "suggestion_status": "new"},
        state, selections[entity_id] / sum(selections.values()), sum(selections.values()),
        NOW - timedelta(days=10), NOW - timedelta(hours=2), ("clarification_selection",),
        health=health,
    )


def habit_model(owner: str, *, suffix: str = "1", samples: int = 12, opportunities: int = 15,
                health: ModelHealth = ModelHealth.VALID, sequence: str | None = None,
                with_opportunities: bool = True) -> LearnedModel:
    parameters: dict[str, Any] = {
        "sequence": sequence if sequence is not None else
        "LIGHT_TURN_ON@light.kitchen=on|COVER_OPEN_COVER@cover.kitchen=open|SWITCH_TURN_ON@switch.coffee=on",
        "support": samples / opportunities,
        "suggestion_status": "new",
        "creates_automation": False,
    }
    if with_opportunities:
        parameters["opportunity_count"] = opportunities
    if sequence == "":
        del parameters["sequence"]
    return LearnedModel(
        f"habit:{owner}:{suffix}", LearnedKind.HABIT, owner,
        {"time_band": "morning", "weekday": 1, "sequence_family": "fam"},
        parameters, KnowledgeState.INFERRED, min(1.0, samples / opportunities), samples,
        NOW - timedelta(days=20), NOW - timedelta(days=1),
        tuple(f"goal_run:h{index}" for index in range(samples)), health=health,
    )


def thermal_model(*, health: ModelHealth = ModelHealth.VALID, holdout: bool = True,
                  invalidation: str | None = None, expires_at: datetime | None = None) -> LearnedModel:
    parameters: dict[str, Any] = {
        "temperature_entity_id": "sensor.living_temperature",
        "climate_entity_id": "climate.living",
        "binding_confirmed": True,
        "intercept_seconds": 600.0, "delta_coefficient": 900.0, "mae_seconds": 180.0,
        "residual_median_seconds": 10.0, "residual_mad_seconds": 60.0, "residual_p90_seconds": 200.0,
        "drift_detected": health is ModelHealth.DRIFT_DETECTED,
        "updated_at": NOW.isoformat(), "validation_sample_count": 10 if holdout else 0,
        "min_start_temperature": 19.0, "max_start_temperature": 22.5,
    }
    metrics = {"training_mae_seconds": 180.0, "residual_mad_seconds": 60.0}
    if holdout:
        metrics.update({
            "holdout_mae_seconds": 192.0,
            "holdout_median_absolute_error_seconds": 150.0,
            "holdout_p90_absolute_error_seconds": 300.0,
        })
    return LearnedModel(
        "thermal:living", LearnedKind.THERMAL_MODEL, "living", {"area_id": "living"},
        parameters, KnowledgeState.OBSERVED, 0.9, 43,
        NOW - timedelta(days=50), NOW - timedelta(days=1), (), 3, metrics,
        health=health, expires_at=expires_at, invalidation_reason=invalidation,
    )


def standing_permission(owner: str, *, permission_id: str | None = None,
                        expires_in: timedelta = timedelta(days=180)) -> StandingPermission:
    return StandingPermission(
        permission_id or f"perm_{owner}", owner, SituationKind.DEVICE_LEFT_ON_WHEN_LEAVING,
        AutoOperator.LIGHT_TURN_OFF, ("light.living",), "living",
        (PermissionCondition.NOBODY_HOME,), NOW - timedelta(days=1), NOW + expires_in, True,
        description="Licht im Bereich Wohnzimmer ausschalten, wenn niemand zu Hause ist",
    )


def run(coro: Any) -> Any:
    return asyncio.run(coro)
