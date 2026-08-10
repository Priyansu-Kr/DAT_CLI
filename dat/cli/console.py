"""Terminal output that survives a non-UTF-8 environment.

DAT is run from places that don't set a UTF-8 locale - macOS launchd agents and
Xcode build phases, cron, CI containers - where `sys.stdout.encoding` comes out
as ASCII. Writing a "✔" to such a stream raises UnicodeEncodeError and takes the
whole command down, after the work was already done.

Two defences, because they cover different things:

* `harden_stdio()` makes the streams replace unencodable characters instead of
  raising. That covers text DAT doesn't choose - branch names, paths, commit
  messages - which can hold anything.
* `OK` / `FAIL` / `WARN` degrade to ASCII markers when the terminal can't take
  the glyph, so DAT's own status lines stay readable rather than turning into
  a row of question marks.
"""
import sys

from rich.console import Console


def harden_stdio() -> None:
    """Stop unencodable output from raising. Safe to call more than once."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # a replaced stream (test capture, a pipe wrapper)
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


def stream_supports(text: str, stream=None) -> bool:
    """Whether `text` can be written to `stream` as-is."""
    stream = stream if stream is not None else sys.stdout
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        # In-memory streams (StringIO, test capture) take any str.
        return True
    try:
        text.encode(encoding)
        return True
    except (LookupError, UnicodeEncodeError):
        return False


def glyph(preferred: str, fallback: str) -> str:
    return preferred if stream_supports(preferred) else fallback


# Resolved once at import: the stream's encoding does not change under us
# (harden_stdio only touches its error handler).
OK = glyph("✔", "[OK]")
FAIL = glyph("✘", "[X]")
WARN = glyph("⚠", "[!]")


def get_console() -> Console:
    """A Console for user-facing CLI output."""
    return Console()
