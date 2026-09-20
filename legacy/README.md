# Legacy `ha_nlu` compatibility shim

This directory is **not** installed by HACS. It is the source of the
`ha_nlu` domain compatibility shim, kept here for reference and for the
manual-restore case described below.

## Why it moved here (5.0.1)

Before 5.0.1, this shim lived at `custom_components/ha_nlu` alongside the
canonical integration at `custom_components/homeintent`. HACS's integration
repository handler resolves a "single integration per repository" by
picking the first directory it finds under `custom_components/` (see
`hacs/integration`'s `get_first_directory_in_directory`, iterating the
GitHub tree in the git-native, byte-lexicographic order of directory
names). `"ha_nlu"` sorts before `"homeintent"`, so HACS installed the
`ha_nlu` shim (`domain = ha_nlu`, `config_flow = false`) for every fresh
install and for every existing repository tracking record, instead of the
real `homeintent` integration. That is why a fresh install offered no
config flow and why some existing `ha_nlu` config entries never actually
had `custom_components/homeintent` on disk to forward into (see the "Why
`ha_nlu` alone was already broken before 5.0.1" note in
`docs/homeintent-rename-migration.md`).

5.0.1 fixes this by making `custom_components/` contain exactly one
directory HACS can select: `custom_components/homeintent`. The shim's
*source* stays in the repository (here) instead of being deleted outright,
because:

- Users who already have `custom_components/ha_nlu` installed on disk (from
  before 5.0.1) keep it - this repository restructuring does not touch
  files already present in anyone's `config/custom_components/`.
- The next HACS update on the same repository entry now resolves to
  `custom_components/homeintent` (the only remaining directory) and
  installs it. Once that lands next to the pre-existing `ha_nlu` directory,
  the shim's `from custom_components.homeintent import ...` forwarding
  works again (or works for the first time, for installs that never had
  `homeintent` on disk at all because of the bug above).

## Manual restore (only if you deleted `ha_nlu` yourself)

HACS will **not** reinstall `custom_components/ha_nlu` anymore - it is no
longer part of the HACS-managed tree. If you still have a Home Assistant
config entry with domain `ha_nlu` and you removed the `ha_nlu` directory
from `config/custom_components/` (e.g. during an uninstall/reinstall), copy
this directory back manually:

```
cp -r legacy/ha_nlu <config>/custom_components/ha_nlu
```

then restart Home Assistant. This is only ever needed if you deliberately
want to keep an old `ha_nlu` config entry alive without recreating it under
the `homeintent` domain. New installations never need this directory.
