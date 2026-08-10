"""CLI output must not die on a terminal that can't encode it.

DAT is run from launchd agents and Xcode build phases on macOS, and from cron
and CI containers on Linux - none of which necessarily set a UTF-8 locale.
There, `sys.stdout.encoding` is ASCII and printing "✔" raised
UnicodeEncodeError *after* the document had already been written.
"""
import io
import sys
import unittest
from unittest import mock

from dat.cli import console as console_mod


def ascii_stream() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")


def utf8_stream() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="utf-8")


class TestGlyphFallback(unittest.TestCase):
    def test_ascii_terminal_gets_a_plain_marker(self):
        with mock.patch.object(sys, "stdout", ascii_stream()):
            self.assertEqual(console_mod.glyph("✔", "[OK]"), "[OK]")

    def test_utf8_terminal_keeps_the_glyph(self):
        with mock.patch.object(sys, "stdout", utf8_stream()):
            self.assertEqual(console_mod.glyph("✔", "[OK]"), "✔")

    def test_unknown_encoding_name_is_treated_as_unsupported(self):
        stream = mock.Mock(encoding="not-a-real-codec")
        self.assertFalse(console_mod.stream_supports("✔", stream))

    def test_in_memory_streams_take_anything(self):
        """StringIO and test capture have no encoding; they hold str."""
        self.assertTrue(console_mod.stream_supports("✔", io.StringIO()))

    def test_module_symbols_are_defined(self):
        for symbol in (console_mod.OK, console_mod.FAIL, console_mod.WARN):
            self.assertTrue(symbol)


class TestHardenStdio(unittest.TestCase):
    def test_unencodable_output_is_replaced_instead_of_raising(self):
        stream = ascii_stream()
        with mock.patch.object(sys, "stdout", stream), \
             mock.patch.object(sys, "stderr", ascii_stream()):
            console_mod.harden_stdio()
            # A branch name or path DAT didn't choose - it must not abort.
            stream.write("branch-fé\n")
            stream.flush()

        self.assertIn(b"branch-f", stream.buffer.getvalue())

    def test_streams_without_reconfigure_are_left_alone(self):
        with mock.patch.object(sys, "stdout", io.StringIO()), \
             mock.patch.object(sys, "stderr", io.StringIO()):
            console_mod.harden_stdio()  # must not raise

    def test_is_idempotent(self):
        with mock.patch.object(sys, "stdout", ascii_stream()), \
             mock.patch.object(sys, "stderr", ascii_stream()):
            console_mod.harden_stdio()
            console_mod.harden_stdio()


class TestCommandsUseTheSafeSymbols(unittest.TestCase):
    """A literal glyph in a print is the bug this module exists to prevent."""

    def test_no_raw_status_glyphs_in_cli_sources(self):
        import pathlib

        offenders = []
        for path in pathlib.Path("dat").rglob("*.py"):
            if path.name == "console.py" or "gui" in path.parts:
                continue  # Tk draws its own text; the console module defines them
            text = path.read_text(encoding="utf-8")
            for glyph in ("✔", "✘", "⚠"):
                if glyph in text:
                    offenders.append(f"{path}: {glyph}")
        self.assertEqual(offenders, [], "use OK/FAIL/WARN from dat.cli.console")


if __name__ == "__main__":
    unittest.main()
