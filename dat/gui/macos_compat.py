"""macOS-only Tk compatibility shims.

CustomTkinter windows can open behind other applications and fail to grab
keyboard focus on macOS (an AppKit/Tk interaction, not present on Linux or
Windows). ``apply()`` gates the fix behind a platform check so Linux/VM
environments - which never hit this issue - get a no-op.
"""
import platform


def apply() -> None:
    if platform.system() != "Darwin":
        return

    _fix_darkdetect_empty_mac_ver()
    _fix_window_focus()


def _fix_darkdetect_empty_mac_ver() -> None:
    """On some Macs/VMs (e.g. betas, minimal VM images without a populated
    SystemVersion.plist) ``platform.mac_ver()`` returns ``('', ('', '', ''),
    '')``. ``customtkinter`` pulls in ``darkdetect``, which does
    ``int(platform.mac_ver()[0].split('.')[0])`` at import time with no
    guard, raising ``ValueError: invalid literal for int() with base 10: ''``
    and taking the whole GUI down with it. Patch mac_ver() to fall back to a
    real version string before anything imports darkdetect/customtkinter.
    """
    if getattr(platform.mac_ver, "_dat_macos_patched", False):
        return

    _original_mac_ver = platform.mac_ver

    def _safe_mac_ver(release="", versioninfo=("", "", ""), machine=""):
        result_release, result_versioninfo, result_machine = _original_mac_ver(
            release, versioninfo, machine
        )
        if not result_release:
            result_release = "10.16"
        return result_release, result_versioninfo, result_machine

    _safe_mac_ver._dat_macos_patched = True
    platform.mac_ver = _safe_mac_ver


def _fix_window_focus() -> None:
    import tkinter as tk

    if getattr(tk.Misc.lift, "_dat_macos_patched", False):
        return

    _original_lift = tk.Misc.lift

    def _drop_topmost(window) -> None:
        # Runs a tick later, by which point the window may already be gone
        # (a builder opened and closed quickly). Unguarded, that surfaces as
        # an "Exception in Tkinter callback" traceback on macOS only.
        try:
            window.attributes("-topmost", False)
        except tk.TclError:
            pass

    def _lift_and_focus(self, aboveThis=None):
        _original_lift(self, aboveThis)
        # lift() is called on ordinary widgets too, not just windows -
        # only windows (Tk/Toplevel, via the Wm mixin) have attributes()/
        # focus_force(), so skip anything else.
        if not isinstance(self, tk.Wm):
            return
        try:
            self.attributes("-topmost", True)
            self.after(0, lambda: _drop_topmost(self))
            self.focus_force()
        except tk.TclError:
            pass

    _lift_and_focus._dat_macos_patched = True
    tk.Misc.lift = _lift_and_focus
