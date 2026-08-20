"""Minimal fake ``homeassistant.*`` module surface so ``ha_nlu.conversation``
(the real Assist entry point, ``NluConversationEntity._async_handle_message``)
can be imported and driven directly in tests, without the real
``homeassistant`` package installed (it isn't - see ``tests/conftest.py``'s
own module docstring: every existing test only imports hass-free
``ha_nlu.*`` modules).

HomeIntent v4.2.1 plan, Section 3/23-26: existing tests only ever call
``engine.match()`` directly - this stub exists so at least one test can
instead exercise the real ``conversation.py`` orchestration layer (pending
clarification -> follow-up -> reference -> query-followup -> fresh match
try-chain, ``ConversationContextStore`` set/clear, the ``QUERY_ANSWER`` vs
``ACTION_DONE`` response-type gate, and the actual ``hass.services.async_call``
call site) end-to-end - not a second reimplementation of that logic.

Deliberately narrow: only the exact names ``conversation.py`` imports at
module level. ``build_entity_snapshots`` (the one real HA-registry-heavy
function ``conversation.py`` calls) is monkeypatched per-test instead of
faithfully stubbed here - it's registry glue (``hass_entities.py``, area/
device/floor registries), not NLU logic, so re-testing it isn't this
integration test's job (it's untouched by this plan - see the v4.2.1 audit).

Import this module (for its side effects) *before* importing
``ha_nlu.conversation`` anywhere in the process - ``sys.modules`` injection
only helps imports that happen after it runs.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from unittest.mock import AsyncMock


def install() -> None:
    if "homeassistant" in sys.modules:
        return  # already installed (or the real package is present)

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    components_conversation = types.ModuleType("homeassistant.components.conversation")
    components_homeassistant = types.ModuleType("homeassistant.components.homeassistant")
    components_homeassistant_exposed_entities = types.ModuleType(
        "homeassistant.components.homeassistant.exposed_entities"
    )
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    util = types.ModuleType("homeassistant.util")
    util_yaml = types.ModuleType("homeassistant.util.yaml")
    util_file = types.ModuleType("homeassistant.util.file")
    util_dt = types.ModuleType("homeassistant.util.dt")
    helpers = types.ModuleType("homeassistant.helpers")
    helpers_area_registry = types.ModuleType("homeassistant.helpers.area_registry")
    helpers_device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    helpers_entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    helpers_floor_registry = types.ModuleType("homeassistant.helpers.floor_registry")
    helpers_entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    helpers_intent = types.ModuleType("homeassistant.helpers.intent")

    # --- homeassistant.components.conversation --------------------------

    class ConversationEntity:
        pass

    class AbstractConversationAgent:
        pass

    class ConversationEntityFeature:
        CONTROL = 1

    @dataclass
    class ConversationInput:
        text: str
        conversation_id: str
        language: str = "de"
        context: Any = None
        device_id: str | None = None

    @dataclass
    class ConversationResult:
        response: Any
        conversation_id: str | None = None

    def async_set_agent(hass: Any, entry: Any, agent: Any) -> None:
        return None

    def async_unset_agent(hass: Any, entry: Any) -> None:
        return None

    components_conversation.ConversationEntity = ConversationEntity
    components_conversation.AbstractConversationAgent = AbstractConversationAgent
    components_conversation.ConversationEntityFeature = ConversationEntityFeature
    components_conversation.ConversationInput = ConversationInput
    components_conversation.ConversationResult = ConversationResult
    components_conversation.async_set_agent = async_set_agent
    components_conversation.async_unset_agent = async_unset_agent
    components_conversation.DOMAIN = "conversation"

    # --- homeassistant.config_entries ------------------------------------

    class ConfigEntry:
        def __init__(self, entry_id: str = "test-entry", title: str = "HA NLU Engine",
                     options: dict | None = None, data: dict | None = None) -> None:
            self.entry_id = entry_id
            self.title = title
            self.options = options or {}
            self.data = data or {}
            self._on_unload: list[Callable[[], Any]] = []

        def add_update_listener(self, listener: Callable[..., Any]) -> Callable[[], None]:
            return lambda: None

        def async_on_unload(self, func: Callable[[], Any]) -> None:
            self._on_unload.append(func)

    config_entries.ConfigEntry = ConfigEntry

    # --- homeassistant.core ----------------------------------------------

    class _States:
        def __init__(self) -> None:
            self._states: dict[str, Any] = {}

        def get(self, entity_id: str) -> Any:
            return self._states.get(entity_id)

        def async_all(self) -> list[Any]:
            return list(self._states.values())

    class ServiceCall:
        """Minimal stand-in for ``homeassistant.core.ServiceCall`` - only
        ``data`` is ever read by this integration's own service handler
        (see ``__init__.py``'s ``_async_delete_automation``)."""

        def __init__(self, data: dict | None = None) -> None:
            self.data = data or {}

    class _Services:
        """Fake ``hass.services``: keeps the pre-existing ``async_call``
        ``AsyncMock`` every existing test already asserts against
        unchanged, and additionally supports ``async_register``/
        ``async_remove``/``has_service`` (new feature, Wave 12) so
        ``__init__.py``'s ``ha_nlu.delete_automation`` service registration
        can be exercised directly - tests invoke the stored handler
        themselves (``hass.services._handlers[(domain, service)](call)``),
        the same way HA itself would dispatch a real service call."""

        def __init__(self) -> None:
            self.async_call = AsyncMock()
            self._handlers: dict[tuple[str, str], Callable[..., Any]] = {}

        def async_register(self, domain: str, service: str, handler: Callable[..., Any], schema: Any = None) -> None:
            self._handlers[(domain, service)] = handler

        def async_remove(self, domain: str, service: str) -> None:
            self._handlers.pop((domain, service), None)

        def has_service(self, domain: str, service: str) -> bool:
            return (domain, service) in self._handlers

    class HomeAssistant:
        def __init__(self) -> None:
            self.states = _States()
            self.services = _Services()
            # V5.26 (AutomationExecutor): real HA's ``hass.config.path()``
            # joins onto the config dir; ``/tmp`` here since tests never
            # care about the real HA config directory, only that a real
            # temp file gets read/written round-trip.
            self.config = types.SimpleNamespace(path=lambda *parts: str(Path("/tmp", *parts)))

        async def async_add_executor_job(self, func: Callable[..., Any], *args: Any) -> Any:
            return func(*args)

    class State:
        def __init__(self, entity_id: str, state: str, attributes: dict | None = None) -> None:
            self.entity_id = entity_id
            self.state = state
            self.attributes = attributes or {}

    core.HomeAssistant = HomeAssistant
    core.State = State
    core.ServiceCall = ServiceCall

    # --- homeassistant.util.yaml / homeassistant.util.file -----------------
    # V5.26 (AutomationExecutor): real HA's ``load_yaml``/``dump`` wrap
    # PyYAML with HA-specific tag support (``!secret`` etc.) this project's
    # automations.yaml never uses - plain PyYAML round-trips the exact same
    # plain dicts/lists this integration ever writes, so it's a faithful
    # enough stand-in for tests without the real ``homeassistant`` package.
    import yaml as _pyyaml

    def _load_yaml(path: str) -> Any:
        with open(path, encoding="utf-8") as handle:
            return _pyyaml.safe_load(handle)

    def _dump_yaml(data: Any) -> str:
        return _pyyaml.safe_dump(data, allow_unicode=True, sort_keys=False)

    def _write_utf8_file_atomic(path: str, content: str, private: bool = False) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    util_yaml.load_yaml = _load_yaml
    util_yaml.dump = _dump_yaml
    util_file.write_utf8_file_atomic = _write_utf8_file_atomic

    # --- homeassistant.util.dt ---------------------------------------------
    # V5 Teil 8/10 (automation_metadata_store.py): only ``utcnow()`` is used
    # (for the metadata sidecar's ``created_at`` field) - real HA's own
    # ``dt_util.utcnow()`` returns a timezone-aware UTC datetime, faithfully
    # mirrored here rather than a naive ``datetime.utcnow()``.

    from datetime import datetime, timezone

    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    util_dt.utcnow = _utcnow

    # --- homeassistant.helpers.device_registry ----------------------------

    class DeviceEntryType:
        SERVICE = "service"

    @dataclass
    class DeviceInfo:
        identifiers: set = field(default_factory=set)
        name: str | None = None
        manufacturer: str | None = None
        model: str | None = None
        entry_type: Any = None

        def __init__(self, **kwargs: Any) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    helpers_device_registry.DeviceEntryType = DeviceEntryType
    helpers_device_registry.DeviceInfo = DeviceInfo

    # --- homeassistant.helpers.area_registry / entity_registry /
    #     floor_registry --------------------------------------------------
    # ``hass_entities.py`` (pure HA-registry glue, out of scope for this
    # plan - see this module's docstring) is monkeypatched away wholesale in
    # every test, so these only need to exist for the module-level `import`
    # to succeed - their bodies are never actually exercised.

    class RegistryEntry:
        area_id: str | None = None
        device_id: str | None = None
        aliases: set = set()

    class _AreaRegistry:
        def async_get_area(self, area_id: str) -> Any:
            return None

    class _EntityRegistry:
        def async_get(self, entity_id: str) -> Any:
            return None

    class _DeviceRegistry:
        def async_get(self, device_id: str) -> Any:
            return None

    class _FloorRegistry:
        def async_get_floor(self, floor_id: str) -> Any:
            return None

    def ar_async_get(hass: Any) -> Any:
        return _AreaRegistry()

    def er_async_get(hass: Any) -> Any:
        return _EntityRegistry()

    def er_async_get_entity_aliases(hass: Any, registry_entry: Any) -> list[str]:
        return []

    def fr_async_get(hass: Any) -> Any:
        return _FloorRegistry()

    helpers_area_registry.RegistryEntry = RegistryEntry  # unused but harmless
    helpers_area_registry.async_get = ar_async_get
    helpers_entity_registry.RegistryEntry = RegistryEntry
    helpers_entity_registry.async_get = er_async_get
    helpers_entity_registry.async_get_entity_aliases = er_async_get_entity_aliases
    helpers_floor_registry.async_get = fr_async_get

    # device_registry also needs an ``async_get`` for hass_entities.py's
    # entity -> device -> area fallback chain.
    def dr_async_get(hass: Any) -> Any:
        return _DeviceRegistry()

    helpers_device_registry.async_get = dr_async_get

    # --- homeassistant.components.homeassistant.exposed_entities -----------

    def async_should_expose(hass: Any, domain: str, entity_id: str) -> bool:
        return True

    components_homeassistant_exposed_entities.async_should_expose = async_should_expose

    # --- homeassistant.helpers.entity_platform -----------------------------

    AddEntitiesCallback = Callable[[list], None]
    helpers_entity_platform.AddEntitiesCallback = AddEntitiesCallback

    # --- homeassistant.helpers.intent --------------------------------------

    class IntentResponseType:
        ACTION_DONE = "action_done"
        QUERY_ANSWER = "query_answer"

    class IntentResponseErrorCode(Enum):
        NO_INTENT_MATCH = "no_intent_match"
        FAILED_TO_HANDLE = "failed_to_handle"

    class IntentResponse:
        def __init__(self, language: str) -> None:
            self.language = language
            self.response_type = IntentResponseType.ACTION_DONE
            self.speech: str | None = None
            self.error_code: IntentResponseErrorCode | None = None

        def async_set_speech(self, speech: str) -> None:
            self.speech = speech

        def async_set_error(self, code: IntentResponseErrorCode, message: str) -> None:
            self.error_code = code
            self.speech = message

    helpers_intent.IntentResponse = IntentResponse
    helpers_intent.IntentResponseType = IntentResponseType
    helpers_intent.IntentResponseErrorCode = IntentResponseErrorCode

    # --- wire up the package tree ------------------------------------------

    homeassistant.components = components
    components.conversation = components_conversation
    components.homeassistant = components_homeassistant
    components_homeassistant.exposed_entities = components_homeassistant_exposed_entities
    homeassistant.config_entries = config_entries
    homeassistant.core = core
    homeassistant.util = util
    util.yaml = util_yaml
    util.file = util_file
    util.dt = util_dt
    homeassistant.helpers = helpers
    helpers.area_registry = helpers_area_registry
    helpers.device_registry = helpers_device_registry
    helpers.entity_registry = helpers_entity_registry
    helpers.floor_registry = helpers_floor_registry
    helpers.entity_platform = helpers_entity_platform
    helpers.intent = helpers_intent

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.conversation"] = components_conversation
    sys.modules["homeassistant.components.homeassistant"] = components_homeassistant
    sys.modules["homeassistant.components.homeassistant.exposed_entities"] = (
        components_homeassistant_exposed_entities
    )
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.yaml"] = util_yaml
    sys.modules["homeassistant.util.file"] = util_file
    sys.modules["homeassistant.util.dt"] = util_dt
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.area_registry"] = helpers_area_registry
    sys.modules["homeassistant.helpers.device_registry"] = helpers_device_registry
    sys.modules["homeassistant.helpers.entity_registry"] = helpers_entity_registry
    sys.modules["homeassistant.helpers.floor_registry"] = helpers_floor_registry
    sys.modules["homeassistant.helpers.entity_platform"] = helpers_entity_platform
    sys.modules["homeassistant.helpers.intent"] = helpers_intent
