"""Structural verification that ``custom_components/homeintent/config_flow.py``
implements a real Home Assistant config flow for ``domain=homeintent``.

The real ``homeassistant`` and ``voluptuous`` packages are not part of this
project's dev dependencies (see ``requirements-dev.txt``), and the rest of
this test suite deliberately avoids depending on them (``tests/conftest.py``,
``tests/_ha_stub.py``). Fully importing ``config_flow.py`` would require
stubbing ``homeassistant.helpers.selector`` and ``voluptuous`` in addition to
the narrower surface ``tests/_ha_stub.py`` already provides for
``conversation.py``. This test instead parses the module with ``ast`` and
checks the concrete structure Home Assistant requires to offer a UI config
flow, without executing or importing it.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = REPO_ROOT / "custom_components" / "homeintent"
CONFIG_FLOW_PATH = INTEGRATION_DIR / "config_flow.py"


def _parse_config_flow() -> ast.Module:
    return ast.parse(CONFIG_FLOW_PATH.read_text(), filename=str(CONFIG_FLOW_PATH))


def _domain_from_const() -> str:
    const_source = (INTEGRATION_DIR / "const.py").read_text()
    tree = ast.parse(const_source, filename="const.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DOMAIN" for target in node.targets
        ):
            assert isinstance(node.value, ast.Constant)
            return node.value.value
    raise AssertionError("DOMAIN not found in const.py")


def test_manifest_declares_config_flow_true():
    manifest = json.loads((INTEGRATION_DIR / "manifest.json").read_text())
    assert manifest["config_flow"] is True
    assert manifest["domain"] == "homeintent"


def test_config_flow_module_exists_and_parses():
    assert CONFIG_FLOW_PATH.is_file()
    _parse_config_flow()  # raises SyntaxError if not valid Python


def test_config_flow_defines_a_config_flow_subclass_for_the_canonical_domain():
    tree = _parse_config_flow()
    domain = _domain_from_const()
    assert domain == "homeintent"

    flow_classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    matching = []
    for cls in flow_classes:
        base_names = {
            base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
            for base in cls.bases
        }
        if "ConfigFlow" not in base_names and not any(
            b and "ConfigFlow" in b for b in base_names if b
        ):
            continue
        domain_kwarg = next(
            (kw for kw in cls.keywords if kw.arg == "domain"),
            None,
        )
        if domain_kwarg is None:
            continue
        # domain=DOMAIN (a Name reference) is the expected, non-hardcoded form.
        if isinstance(domain_kwarg.value, ast.Name) and domain_kwarg.value.id == "DOMAIN":
            matching.append(cls)

    assert matching, (
        "expected a class in config_flow.py extending ConfigFlow with "
        "domain=DOMAIN (DOMAIN == 'homeintent')"
    )


def test_config_flow_class_implements_async_step_user_and_creates_an_entry():
    tree = _parse_config_flow()

    step_user_found = False
    creates_entry = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_step_user":
            step_user_found = True
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "async_create_entry"
                ):
                    creates_entry = True

    assert step_user_found, "config_flow.py must implement async_step_user"
    assert creates_entry, "async_step_user must call self.async_create_entry(...)"


def test_config_flow_has_no_yaml_import_config_hint():
    source = CONFIG_FLOW_PATH.read_text()
    # A UI-first integration should not steer users toward configuration.yaml.
    assert "configuration.yaml" not in source
