"""Deprecated HomeIntent domain shim for existing ``ha_nlu`` config entries.

All production behavior lives in :mod:`custom_components.homeintent`.  This
module exists solely because Home Assistant does not support changing the
domain of an existing config entry in place.
"""

from custom_components.homeintent import async_setup_entry, async_unload_entry

__all__ = ("async_setup_entry", "async_unload_entry")
