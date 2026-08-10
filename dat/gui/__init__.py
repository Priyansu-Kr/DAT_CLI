"""DAT's Tk/CustomTkinter user interface.

The macOS shims are applied here, at package import, because one of them
(``platform.mac_ver`` returning an empty version) must be in place *before*
``customtkinter`` is imported anywhere - and every module that imports
customtkinter lives in this package, so Python runs this first no matter
which one is imported. Relying on the entry point to call apply() left the
crash reachable by importing e.g. ``dat.gui.panels.preview_panel`` directly.

apply() is a no-op off macOS and idempotent, so this is free elsewhere.
"""
from dat.gui import macos_compat

macos_compat.apply()

__all__ = ["macos_compat"]
