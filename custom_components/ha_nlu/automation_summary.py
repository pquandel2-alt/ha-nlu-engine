"""Automation summary: a read-only, hass-free view of one entry in
``automations.yaml`` plus its sidecar metadata (HomeIntent V5 Teil 9/10,
V5.29 "Automation Query").

Mirrors ``devices.DeviceSnapshot``: a plain, frozen dataclass populated once
per conversation turn from live HA data (see ``automation_executor.py``'s
``async_list_automations()``), never a persisted second database. Deliberately
flat and hass/YAML-shape-free - the ``nlu/`` query pipeline (``QueryExecutor``/
``ResponseGenerator``) never needs to know that ``automations.yaml``/the
metadata sidecar even exist, same layering precedent ``EntitySnapshot``/
``DeviceSnapshot`` already set for the entity/device registries.

``referenced_entity_ids`` is deliberately shallow: every ``entity_id`` string
found anywhere in the automation's raw config (trigger, condition, and action
alike), not a re-derivation of *how* that entity is used (no attempt to tell
"triggers on" apart from "turns on" - the plan's own scope note: full
trigger/condition/action semantics re-derivation from raw YAML is out of
scope, see ``automation_executor.py``'s ``async_list_automations()``
docstring). This is enough to answer "was schaltet/steuert X?" and "warum
geht X an?" honestly as "automations that mention X somewhere", without
overclaiming actual causation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AutomationSummary:
    """Hass-free view of one ``automations.yaml`` entry.

    ``alias`` is always present (Home Assistant assigns automations created
    through its own UI editor a default alias too, and ``AutomationExecutor``
    always writes one - see ``ha_automation_generator.py``). ``source_text``/
    ``created_by`` are ``None`` for automations this integration didn't
    create (no sidecar metadata entry exists for them) - the plan's own
    "created_by tells HomeIntent-made apart from hand-made" distinction
    (see ``automation_metadata_store.py``'s ``CREATED_BY_HOMEINTENT`` docstring).
    """

    automation_id: str
    alias: str
    source_text: str | None = None
    created_by: str | None = None
    referenced_entity_ids: frozenset[str] = frozenset()
    # HomeIntent V5 Teil 8/10 (Wave 11, "Automation Disable/Enable"): mirrors
    # the automation's own ``initial_state`` YAML key (defaults to enabled
    # when the key is absent, same default Home Assistant's own automation
    # config schema uses - see ``AutomationExecutor``'s ``async_disable_automation()``
    # docstring for why this key, not ``automation.turn_on``/``turn_off``,
    # is this integration's actual enable/disable mechanism).
    enabled: bool = True
