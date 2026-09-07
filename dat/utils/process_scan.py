"""Finding (and stopping) the DAT processes running on this machine.

`dat kill` exists because a GUI window can outlive every normal way of
closing it - a Tk window that lost its event loop, or a Preview Panel the
MCP server spawned detached (see `dat.mcp.server._spawn_detached`), keeps a
process alive that the taskbar can no longer reach.

The hard requirement is precision: the user's machine is also running
unrelated Python programs, and killing one of those would be far worse than
leaving a stuck window open. So a process is only ever a target when its
command line is recognisably a DAT entry point - the `dat` console script,
`python -m dat.main`, or `python .../dat/main.py` - never on a substring
match against "dat", which appears in innocent paths like `update_data.py`.

Enumeration goes through the OS tools (`ps`, PowerShell/CIM) rather than
psutil so this stays dependency-free; DAT ships to machines where adding a
compiled dependency is a support request of its own.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# What a DAT process *is*, from the user's point of view. `kind` drives what
# `dat kill` targets by default: the two windowed kinds, and nothing else.
KIND_GUI = "gui"
KIND_PREVIEW = "preview"
KIND_MCP = "mcp"
KIND_CLI = "cli"

WINDOW_KINDS = (KIND_GUI, KIND_PREVIEW)

KIND_LABELS = {
    KIND_GUI: "Control Center GUI",
    KIND_PREVIEW: "Preview Panel (generate-doc)",
    KIND_MCP: "MCP server",
    KIND_CLI: "CLI command",
}

_PYTHON_EXE = re.compile(r"^(python|pythonw|py)[0-9._]*$")

# `ps -o args=` output can be long; a Preview Panel launched with a seed file
# carries a full temp path. Truncate for display only.
_DISPLAY_WIDTH = 70


@dataclass
class DatProcess:
    pid: int
    ppid: int
    kind: str
    command: str

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def short_command(self) -> str:
        if len(self.command) <= _DISPLAY_WIDTH:
            return self.command
        return self.command[: _DISPLAY_WIDTH - 3] + "..."


class ProcessScanError(RuntimeError):
    """The OS process list could not be read at all."""


def _stem(path: str) -> str:
    """Basename of an executable, without a Windows extension."""
    base = os.path.basename(path.replace("\\", "/")).lower()
    for ext in (".exe", ".com", ".bat", ".cmd"):
        if base.endswith(ext):
            return base[: -len(ext)]
    return base


def _split_command(cmdline: str) -> List[str]:
    """Best-effort argv from a command-line string.

    Windows command lines keep backslashes as path separators, so they must
    not be parsed with POSIX escaping rules; a malformed line (unbalanced
    quote) falls back to whitespace splitting rather than raising - a
    process we can't parse should be skipped, not crash the scan.
    """
    posix = os.name != "nt"
    try:
        tokens = shlex.split(cmdline, posix=posix)
    except ValueError:
        tokens = cmdline.split()
    if not posix:
        tokens = [t.strip('"') for t in tokens]
    return tokens


def _dat_entry_index(rest: Sequence[str]) -> Optional[int]:
    """Index in `rest` of the token that makes this a DAT invocation.

    Recognises `-m dat.main` / `-m dat` (and the joined `-mdat.main`), a
    direct path to `dat/main.py`, and a path to the installed `dat` console
    script being run through an interpreter.
    """
    for i, token in enumerate(rest):
        if token in ("-m", "--module"):
            if i + 1 < len(rest) and rest[i + 1] in ("dat.main", "dat"):
                return i + 1
            continue
        if token.startswith("-m") and len(token) > 2:
            if token[2:] in ("dat.main", "dat"):
                return i
            continue
        if token.startswith("-"):
            continue

        normalized = token.replace("\\", "/")
        if normalized.endswith("/dat/main.py") or normalized == "dat/main.py":
            return i
        # The console script itself (e.g. /usr/local/bin/dat) run under an
        # explicit interpreter. Requires a path separator so a bare word
        # "dat" - which could be any argument - is never a match.
        if "/" in normalized and _stem(normalized) == "dat":
            return i
        # First positional token isn't a DAT entry point: some other script.
        return None
    return None


def _kind_from_subcommand(rest: Sequence[str]) -> str:
    subcommand = next((t for t in rest if not t.startswith("-")), None)
    if subcommand == "gui":
        return KIND_GUI
    if subcommand == "generate-doc":
        # --headless writes the file and exits without ever opening a
        # window, so it isn't something `dat kill` should reach for by
        # default - it may be mid-export in a CI job.
        return KIND_CLI if "--headless" in rest else KIND_PREVIEW
    if subcommand == "mcp":
        return KIND_MCP
    return KIND_CLI


def classify_command(cmdline: str) -> Optional[str]:
    """The DAT process kind for a command line, or None if it isn't DAT."""
    argv = _split_command(cmdline)
    if not argv:
        return None

    exe = _stem(argv[0])
    if exe == "dat":
        return _kind_from_subcommand(argv[1:])

    if _PYTHON_EXE.match(exe):
        entry = _dat_entry_index(argv[1:])
        if entry is None:
            return None
        return _kind_from_subcommand(argv[1 + entry + 1 :])

    return None


# The same request in the dialects of the two `ps` implementations DAT runs
# on. procps (Linux) accepts all of these; BSD `ps` (macOS) is the reason for
# more than one: `command` is its documented keyword for the full command
# line, and only some versions alias `args` to it. `-ww` defeats the width
# truncation that would otherwise cut a long Preview Panel command line
# before the part that identifies it, and uid is requested rather than user
# because the user column is truncated for long names on Linux.
_PS_COMMANDS = (
    ["ps", "-A", "-ww", "-o", "pid=,ppid=,uid=,args="],
    ["ps", "-A", "-ww", "-o", "pid=,ppid=,uid=,command="],
    ["ps", "-axww", "-o", "pid=,ppid=,uid=,command="],
)


def _parse_ps_output(text: str, my_uid: int) -> List[Tuple[int, int, str]]:
    rows: List[Tuple[int, int, str]] = []
    for line in text.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid, ppid, uid, args = parts
        try:
            if int(uid) != my_uid:
                # Another user's process: we could not signal it anyway, and
                # offering to is worse than not listing it.
                continue
            rows.append((int(pid), int(ppid), args.strip()))
        except ValueError:
            continue
    return rows


def _scan_posix() -> List[Tuple[int, int, str]]:
    my_uid = os.getuid()
    my_pid = os.getpid()
    last_error = "no usable 'ps' invocation"

    for command in _PS_COMMANDS:
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProcessScanError(f"could not run 'ps': {exc}") from exc

        if result.returncode != 0:
            last_error = (result.stderr or "ps failed").strip()
            continue

        rows = _parse_ps_output(result.stdout, my_uid)
        # This process must appear in its own process list. If it doesn't,
        # `ps` accepted the flags but produced columns in some other order,
        # and acting on those rows would mean signalling pids read out of the
        # wrong field - so reject the output rather than trust it.
        if any(pid == my_pid for pid, _, _ in rows):
            return rows
        last_error = f"'{' '.join(command)}' returned output this process is not in"

    raise ProcessScanError(last_error)


def _scan_windows() -> List[Tuple[int, int, str]]:
    command = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    last_error = "no PowerShell interpreter found"
    for shell in ("powershell", "pwsh"):
        try:
            result = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            last_error = str(exc)
            continue

        if result.returncode != 0:
            last_error = (result.stderr or f"{shell} failed").strip()
            continue

        try:
            payload = json.loads(result.stdout or "[]")
        except ValueError as exc:
            last_error = f"unreadable process list: {exc}"
            continue

        if isinstance(payload, dict):  # a single process serialises as an object
            payload = [payload]

        rows: List[Tuple[int, int, str]] = []
        for entry in payload:
            cmdline = entry.get("CommandLine")
            if not cmdline:
                continue  # system processes expose no command line
            try:
                rows.append((int(entry["ProcessId"]), int(entry.get("ParentProcessId") or 0), cmdline.strip()))
            except (KeyError, TypeError, ValueError):
                continue
        return rows

    raise ProcessScanError(f"could not read the Windows process list ({last_error})")


def scan_processes() -> List[Tuple[int, int, str]]:
    """Every process this user can see, as (pid, ppid, command line)."""
    if os.name == "nt":
        return _scan_windows()
    return _scan_posix()


def _ancestors(pid: int, parents: Dict[int, int]) -> set:
    """`pid` plus its ancestor chain, guarded against a cyclic ppid map."""
    chain = set()
    current = pid
    while current and current not in chain:
        chain.add(current)
        current = parents.get(current, 0)
    return chain


def find_dat_processes(kinds: Optional[Sequence[str]] = None) -> List[DatProcess]:
    """DAT processes of the given kinds, excluding this process and the
    processes that launched it - `dat kill` must never take itself, or the
    IDE/MCP server that invoked it, down as collateral."""
    rows = scan_processes()
    parents = {pid: ppid for pid, ppid, _ in rows}
    protected = _ancestors(os.getpid(), parents)

    found: List[DatProcess] = []
    for pid, ppid, cmdline in rows:
        if pid in protected:
            continue
        kind = classify_command(cmdline)
        if kind is None:
            continue
        if kinds is not None and kind not in kinds:
            continue
        found.append(DatProcess(pid=pid, ppid=ppid, kind=kind, command=cmdline))

    found.sort(key=lambda p: p.pid)
    return found


def _posix_state(pid: int) -> Optional[str]:
    """Scheduler state letter, where the OS makes it cheap to read."""
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as f:
                # The comm field can contain spaces and parentheses, so the
                # state always follows the *last* ')'.
                stat = f.read()
            return stat[stat.rindex(")") + 1 :].split()[0]
        except (OSError, ValueError, IndexError):
            return None
    # macOS: `state` is the POSIX keyword and `stat` the BSD one; which is
    # accepted varies, so try both before giving up. Returning None means
    # "unknown", which `is_alive` reads as still running - the safe way to be
    # wrong, since it leads to a force-kill rather than a false "closed".
    for keyword in ("state=", "stat="):
        try:
            result = subprocess.run(
                ["ps", "-o", keyword, "-p", str(pid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:1]
    return None


def is_alive(pid: int) -> bool:
    """Whether `pid` is still a running process.

    A zombie counts as dead: the window is gone and the entry only persists
    until whichever shell started it reaps the child, which `dat kill` can't
    do and shouldn't wait for.
    """
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True

    return _posix_state(pid) != "Z"


def request_stop(pid: int, force: bool = False) -> Optional[str]:
    """Ask `pid` to exit. Returns None on success, or a reason it failed.

    The graceful path is deliberately the default: a Preview Panel holding
    an unsaved document gets a chance to run its shutdown handlers before
    anything escalates to an unblockable kill.
    """
    if os.name == "nt":
        # /T also takes the process's children - a Tk app can leave helper
        # processes behind. Without /F this delivers a close request that a
        # windowed app can act on; /F is the unconditional termination.
        cmd = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            cmd.append("/F")
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return str(exc)
        if result.returncode != 0 and is_alive(pid):
            return (result.stdout or f"taskkill exited {result.returncode}").strip()
        return None

    import signal

    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        return None  # already gone, which is the outcome we wanted
    except PermissionError:
        return "permission denied"
    except OSError as exc:
        return str(exc)
    return None


def wait_for_exit(pids: Sequence[int], timeout: float) -> List[int]:
    """Poll until every pid is gone or `timeout` elapses; returns survivors."""
    deadline = time.monotonic() + timeout
    remaining = list(pids)
    while remaining:
        remaining = [pid for pid in remaining if is_alive(pid)]
        if not remaining or time.monotonic() >= deadline:
            break
        time.sleep(0.15)
    return remaining
