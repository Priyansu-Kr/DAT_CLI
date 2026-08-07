"""macOS-only code paths, exercised on any platform.

These matter because CI and day-to-day development happen on Linux, where
Darwin-gated code never runs - so a break there is invisible until someone
opens the app on a Mac.
"""
import importlib
import platform
import sys
import tkinter as tk
import unittest
from unittest import mock

from dat.commands.doctor import tkinter_install_hint
from dat.gui import macos_compat


def fake_mac_ver(release=""):
    """A stand-in for platform.mac_ver().

    Deliberately a plain function, not a Mock: a MagicMock auto-creates the
    `_dat_macos_patched` attribute the shim uses as its idempotency guard,
    so the shim would think it had already run and skip patching.
    """
    def mac_ver(*_args, **_kwargs):
        return (release, ("", "", ""), "")
    return mac_ver


class MacOSShimTestCase(unittest.TestCase):
    """Restores the process-wide patches these shims install."""

    def setUp(self):
        self._mac_ver = platform.mac_ver
        self._lift = tk.Misc.lift

    def tearDown(self):
        platform.mac_ver = self._mac_ver
        tk.Misc.lift = self._lift


class TestDarkdetectGuard(MacOSShimTestCase):
    def test_empty_mac_version_is_replaced(self):
        """darkdetect does int(mac_ver()[0].split('.')[0]) with no guard, so an
        empty version takes the whole GUI down at import time."""
        with mock.patch.object(platform, "system", return_value="Darwin"), \
                mock.patch.object(platform, "mac_ver", fake_mac_ver("")):
            macos_compat.apply()
            release = platform.mac_ver()[0]

        self.assertTrue(release)
        int(release.split(".")[0])  # must not raise, which is the whole point

    def test_real_version_is_left_alone(self):
        with mock.patch.object(platform, "system", return_value="Darwin"), \
                mock.patch.object(platform, "mac_ver", fake_mac_ver("14.5")):
            macos_compat.apply()
            self.assertEqual(platform.mac_ver()[0], "14.5")

    def test_no_op_off_macos(self):
        with mock.patch.object(platform, "system", return_value="Linux"):
            macos_compat.apply()
        self.assertFalse(getattr(platform.mac_ver, "_dat_macos_patched", False))
        self.assertFalse(getattr(tk.Misc.lift, "_dat_macos_patched", False))

    def test_apply_is_idempotent(self):
        with mock.patch.object(platform, "system", return_value="Darwin"):
            macos_compat.apply()
            first = tk.Misc.lift
            macos_compat.apply()
        self.assertIs(tk.Misc.lift, first, "double-patching would nest the wrapper")


class FakeWindow(tk.Wm):
    """Enough of a Toplevel for the lift() patch, without a display."""

    def __init__(self, destroyed_after_first_call=False):
        self.tk = mock.Mock()
        self._w = "."
        self.attribute_calls = []
        self.deferred = None
        self.focused = False
        self._destroyed_after_first_call = destroyed_after_first_call

    def attributes(self, *args):
        self.attribute_calls.append(args)
        if self._destroyed_after_first_call and len(self.attribute_calls) > 1:
            raise tk.TclError('can\'t invoke "wm" command: application has been destroyed')

    def after(self, _ms, func):
        self.deferred = func

    def focus_force(self):
        self.focused = True


class TestWindowFocusPatch(MacOSShimTestCase):
    def _patched_lift(self):
        with mock.patch.object(platform, "system", return_value="Darwin"):
            macos_compat.apply()
        return tk.Misc.lift

    def test_window_is_raised_and_focused(self):
        lift = self._patched_lift()
        window = FakeWindow()

        lift(window)

        self.assertEqual(window.attribute_calls[0], ("-topmost", True))
        self.assertTrue(window.focused)
        self.assertIsNotNone(window.deferred, "the topmost flag must be dropped again")

    def test_topmost_is_dropped_on_the_next_tick(self):
        lift = self._patched_lift()
        window = FakeWindow()
        lift(window)

        window.deferred()

        self.assertEqual(window.attribute_calls[-1], ("-topmost", False))

    def test_closing_the_window_before_that_tick_does_not_raise(self):
        """A builder opened and closed quickly used to surface an
        'Exception in Tkinter callback' traceback on macOS."""
        lift = self._patched_lift()
        window = FakeWindow(destroyed_after_first_call=True)
        lift(window)

        window.deferred()  # must swallow the TclError

    def test_ordinary_widgets_are_untouched(self):
        lift = self._patched_lift()
        widget = mock.Mock(spec=["tk", "_w"])  # not a tk.Wm
        widget.tk = mock.Mock()
        widget._w = ".frame"

        lift(widget)  # must not try to focus/raise a non-window

        self.assertFalse(hasattr(widget, "attribute_calls"))


class TestShimAppliedAtPackageImport(MacOSShimTestCase):
    def test_importing_the_gui_package_applies_the_shim(self):
        """Every module that imports customtkinter lives under dat.gui, so the
        package __init__ is the only place that can guarantee the darkdetect
        fix runs first - importing dat.gui.panels.preview_panel directly used
        to skip it."""
        for name in [n for n in list(sys.modules) if n == "dat.gui" or n.startswith("dat.gui.macos")]:
            del sys.modules[name]

        with mock.patch.object(platform, "system", return_value="Darwin"), \
                mock.patch.object(platform, "mac_ver", fake_mac_ver("")):
            importlib.import_module("dat.gui")
            self.assertTrue(
                getattr(platform.mac_ver, "_dat_macos_patched", False),
                "dat.gui must apply the macOS shims on import",
            )

        # Leave the real package imported for the rest of the suite.
        for name in [n for n in list(sys.modules) if n == "dat.gui" or n.startswith("dat.gui.macos")]:
            del sys.modules[name]
        importlib.import_module("dat.gui")


class TestPlatformSpecificHints(unittest.TestCase):
    def test_macos_hint_does_not_mention_apt(self):
        with mock.patch.object(sys, "platform", "darwin"):
            hint = tkinter_install_hint()
        self.assertIn("brew", hint)
        self.assertNotIn("apt", hint)

    def test_windows_hint(self):
        with mock.patch.object(sys, "platform", "win32"):
            self.assertIn("python.org", tkinter_install_hint())

    def test_linux_hint(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertIn("apt", tkinter_install_hint())


if __name__ == "__main__":
    unittest.main()
