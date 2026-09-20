# HomeIntent rename and domain migration

## Canonical identity

Beginning with V10 / 5.0.0, the only official project and integration name is
**HomeIntent**. The canonical Home Assistant integration domain and service
namespace are `homeintent`; the canonical source directory is
`custom_components/homeintent`.

## Why a compatibility shim remains

Home Assistant config-entry domains are identity keys. An integration cannot
safely rewrite an already loaded entry from one domain to another in place.
HACS also installs repository content but does not rewrite existing config
entries, automations, scripts, or service calls. Removing the old directory
would therefore strand existing installations.

`custom_components/ha_nlu` consequently remains as a minimal compatibility
shim. It contains no NLU, planner, runtime, world model, executor, or delivery
logic. It forwards setup and the conversation platform to the canonical
HomeIntent implementation. Its displayed name is “HomeIntent Legacy
Migration”; it is not a second integration architecture. The shim also carries
copies of the HomeIntent icons because HACS validates brand assets for every
compatibility manifest; these are static compatibility assets, not product
logic or a second brand.

## Config entries and options

- New installations create a `homeintent` config entry.
- Existing entries with the legacy domain continue to load through the shim.
- The canonical runtime reads the existing entry's data/options unchanged;
  selected entities, aliases, policy configuration, delivery options, and
  memory settings are preserved.
- Recreating the entry under `homeintent` is the eventual supported removal
  path. Users should first export/copy their options and verify their
  automations before deleting the legacy entry.

Home Assistant currently offers no lossless generic API to mutate the domain
of an existing config entry. This document therefore does not claim an
automatic in-place domain conversion.

## Services and existing automations/scripts

New generated automations and documentation use `homeintent.*`. The canonical
integration temporarily registers deprecated forwarding services for the old
namespace. Each call logs a migration warning and enters the same canonical
handler and policy path. No new output generates an old service name.

Users can migrate YAML/UI actions mechanically:

```
ha_nlu.delete_automation       -> homeintent.delete_automation
ha_nlu.record_automation_run   -> homeintent.record_automation_run
ha_nlu.enable_automation       -> homeintent.enable_automation
ha_nlu.proactive_message       -> homeintent.proactive_message
ha_nlu.recheck_agent_event     -> homeintent.recheck_agent_event
```

The shim can be removed only after supported releases have allowed existing
entries and all stored automations/scripts to migrate.

## Storage migration

V10 stores use `homeintent_*` names. On first startup, each canonical store
atomically adopts its corresponding legacy file with `os.replace`; this also
covers memory, document index, proactive events, automation metadata,
transaction journal, and bounded automation history. If that filesystem
operation fails, HomeIntent logs the failure and continues using the legacy
path instead of silently starting with empty data. Once a canonical file
exists it is authoritative.

## Entity IDs and unique IDs

The conversation entity/device identity now uses the canonical domain for new
entries. Existing legacy entries keep their current registry identity through
the shim; V10 does not rewrite entity IDs or unique IDs behind the user's back.
No ordinary controlled household entity is renamed.

## HACS and repository rename

The repository metadata, manifest links, README, badges, and documentation
target `pquandel2-alt/homeintent`. GitHub redirects old repository URLs after a
successful rename, but users with a local Git remote should update it:

```
git remote set-url origin https://github.com/pquandel2-alt/homeintent.git
```

For HACS, remove/re-add the custom repository URL only if HACS does not follow
the GitHub redirect automatically. Do not remove the existing HA config entry
until its options and generated automations have been verified.

## Removal path

1. Stop generating old service references (done in 5.0.0).
2. Keep shim and forwarded services for a documented deprecation window.
3. Provide a Home Assistant-supported entry migration if the platform gains a
   safe API, otherwise guide users through recreating the entry.
4. Measure remaining legacy service/config-entry use via local warnings only.
5. Remove the shim in a later major release, never silently in a patch update.
