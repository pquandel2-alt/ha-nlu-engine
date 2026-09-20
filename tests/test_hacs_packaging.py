"""Packaging regression test for the 5.0.1 HACS directory-selection hotfix.

Before 5.0.1, ``custom_components/`` held two directories: ``homeintent``
(the real integration) and ``ha_nlu`` (a compatibility shim, ``config_flow
= false``). HACS's integration repository handler picks exactly one
directory per repository - the first one in the GitHub tree, which is
returned in git's native byte-lexicographic order
(``get_first_directory_in_directory`` in ``hacs/integration``,
``custom_components/hacs/repositories/integration.py``). ``"ha_nlu"`` sorts
before ``"homeintent"`` (``a`` < ``o``), so HACS always installed the shim
instead of the real integration - see
``docs/homeintent-rename-migration.md`` for the full account.

This test reproduces that selection rule directly against the repository
tree (not just checking that ``custom_components/homeintent`` exists) so a
second competing directory under ``custom_components/`` fails the suite
again, the same way it broke fresh installs before 5.0.1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CUSTOM_COMPONENTS = REPO_ROOT / "custom_components"


def _select_first_integration_directory(custom_components: Path) -> str | None:
    """Mirror HACS's ``get_first_directory_in_directory``.

    HACS walks the GitHub git tree for the ``custom_components`` path and
    returns the first entry that is a directory. The GitHub tree API lists
    entries in git's own tree order, which sorts by raw byte value of the
    name (this is what ``git ls-tree`` and ``git cat-file -p <tree>`` show,
    independent of OS/filesystem listing order) - so directory names sorted
    lexicographically reproduce that order.
    """
    directories = sorted(p.name for p in custom_components.iterdir() if p.is_dir())
    return directories[0] if directories else None


def test_custom_components_has_exactly_one_integration_directory():
    directories = sorted(p.name for p in CUSTOM_COMPONENTS.iterdir() if p.is_dir())
    assert directories == ["homeintent"], (
        "custom_components/ must contain exactly one integration directory "
        f"so HACS cannot select the wrong one; found {directories}. A second "
        "directory belongs under legacy/ or another location outside "
        "custom_components/, not here (see docs/homeintent-rename-migration.md)."
    )


def test_hacs_selects_homeintent_directory():
    selected = _select_first_integration_directory(CUSTOM_COMPONENTS)
    assert selected == "homeintent"


def test_selected_manifest_declares_homeintent_domain_and_config_flow():
    selected = _select_first_integration_directory(CUSTOM_COMPONENTS)
    manifest_path = CUSTOM_COMPONENTS / selected / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    assert manifest["domain"] == "homeintent"
    assert manifest["config_flow"] is True


def test_config_flow_py_is_installed_with_the_selected_integration():
    selected = _select_first_integration_directory(CUSTOM_COMPONENTS)
    assert (CUSTOM_COMPONENTS / selected / "config_flow.py").is_file()


def test_no_other_manifest_under_custom_components_can_be_selected():
    """No manifest.json anywhere under custom_components/ other than the
    canonical integration's own - i.e. no second, competing, installable
    integration manifest path in the HACS-managed tree.
    """
    manifests = sorted(CUSTOM_COMPONENTS.glob("*/manifest.json"))
    assert manifests == [CUSTOM_COMPONENTS / "homeintent" / "manifest.json"]


def test_hacs_json_does_not_redirect_content_to_root():
    hacs_config = json.loads((REPO_ROOT / "hacs.json").read_text())
    # content_in_root=True would make HACS treat the whole repo as the
    # integration payload instead of selecting a custom_components/*
    # subdirectory - never the fix for a directory-selection ambiguity.
    assert hacs_config.get("content_in_root", False) is False


def test_legacy_shim_source_is_preserved_outside_custom_components():
    legacy_manifest = REPO_ROOT / "legacy" / "ha_nlu" / "manifest.json"
    assert legacy_manifest.is_file(), (
        "the ha_nlu compatibility shim source must be preserved (not "
        "deleted) for manual restore - see legacy/README.md"
    )
    manifest = json.loads(legacy_manifest.read_text())
    assert manifest["domain"] == "ha_nlu"


@pytest.mark.parametrize("stray_name", ["ha_nlu", "ha-nlu", "homeintent_legacy"])
def test_no_stray_competing_directory_regresses_selection(stray_name):
    """Guards the underlying rule itself: if a second directory sorting
    before "homeintent" ever reappears under custom_components/, the first
    two tests above must fail rather than silently keep passing.
    """
    assert stray_name not in {p.name for p in CUSTOM_COMPONENTS.iterdir() if p.is_dir()}
