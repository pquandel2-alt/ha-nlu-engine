# HomeIntent rename and domain migration

## Canonical identity

Beginning with V10 / 5.0.0, the only official project and integration name is
**HomeIntent**. The canonical Home Assistant integration domain and service
namespace are `homeintent`; the canonical source directory is
`custom_components/homeintent`.

## 5.0.1: HACS packaging hotfix

5.0.0 shipped both `custom_components/homeintent` (the real integration,
`domain = homeintent`, `config_flow = true`) and `custom_components/ha_nlu`
(the compatibility shim, `domain = ha_nlu`, `config_flow = false`) directly
under `custom_components/` in this repository.

HACS's integration handler treats a repository as containing exactly one
installable integration. To find it, it walks the repository's GitHub tree
and takes the *first* directory under `custom_components/`
(`get_first_directory_in_directory` in `hacs/integration`,
`custom_components/hacs/repositories/integration.py`). The tree is returned
in git's native, byte-lexicographic order, and `"ha_nlu"` sorts before
`"homeintent"` (`a` < `o`). HACS therefore always picked `ha_nlu`: it read
`domain = ha_nlu` and `config_flow = false` from that manifest, so

- a fresh install showed no config flow (`config_flow` was `false`), and
- HACS's tracked local path for the repository was
  `config/custom_components/ha_nlu`, never `.../homeintent`.

This also means the compatibility shim described below was already broken
for **every** installation that went through HACS after 5.0.0 shipped: the
shim's `custom_components/ha_nlu/__init__.py` does
`from custom_components.homeintent import ...`, but HACS never actually
installed `custom_components/homeintent` for anyone, since it only ever
manages the one directory it selects. Existing `ha_nlu` config entries kept
their registry state, but the integration behind them could fail to import.

5.0.1 fixes the selection ambiguity at the source: the repository's
`custom_components/` now contains exactly one directory,
`custom_components/homeintent`. The `ha_nlu` shim's source moved to
`legacy/ha_nlu` (see `legacy/README.md`) - preserved for reference and
manual restore, but no longer a candidate HACS can select. This was chosen
over deleting the shim outright (files already installed in a user's
`config/custom_components/ha_nlu` are untouched by this repository change)
and over a second HACS repository (this fix does not depend on one; see
`legacy/README.md` if that route is taken later).

With only one directory left, the next HACS update against this same
repository entry - for anyone, regardless of which domain HACS previously
tracked for them - resolves to `custom_components/homeintent` and installs
it. That is what actually repairs the shim for existing `ha_nlu` installs
too: once `custom_components/homeintent` lands on disk next to their
pre-existing `custom_components/ha_nlu`, the forwarding import in the shim
succeeds.

## Why a compatibility shim remains

Home Assistant config-entry domains are identity keys. An integration cannot
safely rewrite an already loaded entry from one domain to another in place.
HACS also installs repository content but does not rewrite existing config
entries, automations, scripts, or service calls. Removing the old directory
would therefore strand existing installations.

`legacy/ha_nlu` (formerly `custom_components/ha_nlu`, see "5.0.1: HACS
packaging hotfix" above) consequently remains as a minimal compatibility
shim, kept as source in the repository even though HACS no longer installs
it directly. It contains no NLU, planner, runtime, world model, executor, or
delivery logic. It forwards setup and the conversation platform to the
canonical HomeIntent implementation. Its displayed name is “HomeIntent
Legacy Migration”; it is not a second integration architecture. The shim
also carries copies of the HomeIntent icons because HACS validates brand
assets for every compatibility manifest; these are static compatibility
assets, not product logic or a second brand.

**Limitation:** because `legacy/ha_nlu` is no longer part of the
HACS-managed tree, an already-installed `custom_components/ha_nlu`
directory will not receive further updates through HACS. It should rarely
need changes given how minimal it is; if it ever does, users need the
manual copy step in `legacy/README.md`.

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

## Upgrading to 5.0.1 by starting situation

**Fresh install, no prior HomeIntent/`ha_nlu` config entry.** Add or already
have the repository as a HACS custom repository, install/update to 5.0.1,
restart Home Assistant, then add the integration via
**Settings → Devices & services → Add integration → HomeIntent**. This now
starts the real config flow (`domain = homeintent`, `config_flow = true`).
No manual repository re-add and no SSH access are needed.

**Existing `homeintent` config entry (HACS did select the right directory
for you before 5.0.1, e.g. by luck of a stale tracked path).** Update to
5.0.1 through HACS as normal and restart. Nothing else changes; options,
automations, and stores are read unchanged.

**Existing `ha_nlu` config entry (the common case given the bug above).**
Update the *same* repository entry to 5.0.1 through HACS (no need to remove
and re-add the custom repository) and restart Home Assistant. HACS now
resolves the repository to `custom_components/homeintent` and installs it
alongside the pre-existing `custom_components/ha_nlu` on disk. The old
config entry keeps working through the shim; its options, generated
automations, and stores are untouched. Recreating the entry under
`homeintent` afterwards is optional and manual - see "Config entries and
options" above; nothing does this automatically.

## Removal path

1. Stop generating old service references (done in 5.0.0).
2. Keep shim and forwarded services for a documented deprecation window.
3. Provide a Home Assistant-supported entry migration if the platform gains a
   safe API, otherwise guide users through recreating the entry.
4. Measure remaining legacy service/config-entry use via local warnings only.
5. Remove the shim in a later major release, never silently in a patch update.
