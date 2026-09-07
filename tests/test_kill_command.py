import os
from types import SimpleNamespace

import pytest

from dat.cli.args import parse_args
from dat.commands.kill_cmd import KillCommand
from dat.utils import process_scan
from dat.utils.exit_codes import ExitCode
from dat.utils.process_scan import (
    KIND_CLI,
    KIND_GUI,
    KIND_MCP,
    KIND_PREVIEW,
    classify_command,
)


@pytest.mark.parametrize(
    "cmdline,expected",
    [
        ("dat gui", KIND_GUI),
        ("/usr/local/bin/dat gui", KIND_GUI),
        ("dat generate-doc -s", KIND_PREVIEW),
        ("dat generate-doc", KIND_PREVIEW),
        ("dat generate-doc --headless -o out.docx", KIND_CLI),
        ("dat mcp --log-level INFO", KIND_MCP),
        ("dat doctor", KIND_CLI),
        ("python3 -m dat.main gui", KIND_GUI),
        ("python3 -m dat.main generate-doc -s --seed-file /tmp/dat-preview-seed-x.json", KIND_PREVIEW),
        ("/usr/bin/python3.11 -m dat.main mcp", KIND_MCP),
        ("python -m dat gui", KIND_GUI),
        ("pythonw.exe -m dat.main gui", KIND_GUI),
        ("/home/u/venv/bin/python /home/u/venv/bin/dat gui", KIND_GUI),
        ("python /home/u/DAT_CLI/dat/main.py gui", KIND_GUI),
    ],
)
def test_dat_command_lines_are_recognised(cmdline, expected):
    assert classify_command(cmdline) == expected


@pytest.mark.parametrize(
    "cmdline,expected",
    [
        # pip --user on macOS puts the launcher under ~/Library/Python/3.x.
        ("/Users/me/Library/Python/3.11/bin/dat gui", KIND_GUI),
        (
            "/opt/homebrew/opt/python@3.11/bin/python3.11 /Users/me/Library/Python/3.11/bin/dat generate-doc -s",
            KIND_PREVIEW,
        ),
        ("/Users/me/DAT_CLI/venv/bin/python /Users/me/DAT_CLI/venv/bin/dat mcp", KIND_MCP),
        # A Tk app on a python.org framework build runs through Python.app,
        # whose executable is capitalised - hence the case-folded match.
        (
            "/Library/Frameworks/Python.framework/Versions/3.11/Resources/Python.app/Contents/MacOS/Python "
            "-m dat.main gui",
            KIND_GUI,
        ),
        ("/usr/bin/python3 /Users/me/DAT_CLI/dat/main.py gui", KIND_GUI),
    ],
)
def test_macos_command_lines_are_recognised(cmdline, expected):
    assert classify_command(cmdline) == expected


@pytest.mark.parametrize(
    "cmdline",
    [
        "/opt/homebrew/bin/python3.11 /Users/me/scripts/update_data.py",
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 /Users/me/dataloader.py --gui",
        "/Applications/Xcode.app/Contents/Developer/usr/bin/python3 /Users/me/data/main.py",
    ],
)
def test_macos_unrelated_processes_are_not_matched(cmdline):
    assert classify_command(cmdline) is None


@pytest.mark.parametrize(
    "cmdline",
    [
        # The whole point of the command: unrelated programs must never match,
        # including ones whose paths merely contain the letters "dat".
        "python3 update_data.py",
        "python3 /opt/data/dataloader.py --gui",
        "python3 -m datadog_agent",
        "/usr/bin/python3 manage.py runserver",
        "node dat/main.js",
        "vim dat/main.py",
        "grep -r dat.main .",
        "/bin/bash -c 'dat gui'",  # the shell wrapper, not DAT itself
        "",
        "   ",
    ],
)
def test_unrelated_processes_are_not_matched(cmdline):
    assert classify_command(cmdline) is None


def test_find_skips_self_and_ancestors(monkeypatch):
    me = os.getpid()
    parent = me + 1000
    grandparent = me + 2000
    monkeypatch.setattr(
        process_scan,
        "scan_processes",
        lambda: [
            (me, parent, "python3 -m dat.main kill"),
            (parent, grandparent, "python3 -m dat.main mcp"),
            (grandparent, 1, "/bin/bash"),
            (4242, 1, "python3 -m dat.main gui"),
        ],
    )

    found = process_scan.find_dat_processes()
    assert [p.pid for p in found] == [4242]


def test_find_filters_by_kind(monkeypatch):
    monkeypatch.setattr(
        process_scan,
        "scan_processes",
        lambda: [
            (11, 1, "dat gui"),
            (12, 1, "dat generate-doc -s"),
            (13, 1, "dat mcp"),
            (14, 1, "python3 something_else.py"),
        ],
    )

    windows = process_scan.find_dat_processes(process_scan.WINDOW_KINDS)
    assert [p.pid for p in windows] == [11, 12]

    everything = process_scan.find_dat_processes()
    assert [p.pid for p in everything] == [11, 12, 13]


def test_ancestor_walk_survives_a_cyclic_parent_map():
    assert process_scan._ancestors(5, {5: 6, 6: 5}) == {5, 6}


class _FakeOS:
    """Records stop requests and reports processes dead once asked."""

    def __init__(self, ignore_sigterm=()):
        self.ignore_sigterm = set(ignore_sigterm)
        self.dead = set()
        self.calls = []

    def request_stop(self, pid, force=False):
        self.calls.append((pid, force))
        if force or pid not in self.ignore_sigterm:
            self.dead.add(pid)
        return None

    def is_alive(self, pid):
        return pid not in self.dead


@pytest.fixture
def fake_processes(monkeypatch):
    monkeypatch.setattr(
        process_scan,
        "scan_processes",
        lambda: [
            (11, 1, "dat gui"),
            (12, 1, "dat generate-doc -s"),
            (13, 1, "dat mcp"),
            (14, 1, "python3 unrelated.py"),
        ],
    )


def test_kill_stops_only_gui_processes(fake_processes, monkeypatch, capsys):
    fake = _FakeOS()
    monkeypatch.setattr(process_scan, "request_stop", fake.request_stop)
    monkeypatch.setattr(process_scan, "is_alive", fake.is_alive)

    code = KillCommand().execute(vars(parse_args(["kill"])))

    assert code == ExitCode.SUCCESS
    assert [pid for pid, _ in fake.calls] == [11, 12]
    out = capsys.readouterr().out
    assert "Stopped 2 DAT processes." in out
    assert "1 MCP server still running" not in out  # only printed when nothing matched


def test_kill_all_includes_mcp(fake_processes, monkeypatch):
    fake = _FakeOS()
    monkeypatch.setattr(process_scan, "request_stop", fake.request_stop)
    monkeypatch.setattr(process_scan, "is_alive", fake.is_alive)

    code = KillCommand().execute(vars(parse_args(["kill", "--all"])))

    assert code == ExitCode.SUCCESS
    assert sorted(pid for pid, _ in fake.calls) == [11, 12, 13]


def test_kill_escalates_to_force_when_a_window_ignores_the_request(fake_processes, monkeypatch, capsys):
    fake = _FakeOS(ignore_sigterm={12})
    monkeypatch.setattr(process_scan, "request_stop", fake.request_stop)
    monkeypatch.setattr(process_scan, "is_alive", fake.is_alive)

    code = KillCommand().execute(vars(parse_args(["kill", "--timeout", "0.1"])))

    assert code == ExitCode.SUCCESS
    assert (12, True) in fake.calls
    assert "Stopped 2 DAT processes." in capsys.readouterr().out


def test_kill_list_only_stops_nothing(fake_processes, monkeypatch, capsys):
    fake = _FakeOS()
    monkeypatch.setattr(process_scan, "request_stop", fake.request_stop)
    monkeypatch.setattr(process_scan, "is_alive", fake.is_alive)

    code = KillCommand().execute(vars(parse_args(["kill", "--list"])))

    assert code == ExitCode.SUCCESS
    assert fake.calls == []
    assert "Nothing was stopped" in capsys.readouterr().out


def test_kill_reports_a_process_it_cannot_signal(fake_processes, monkeypatch, capsys):
    monkeypatch.setattr(process_scan, "request_stop", lambda pid, force=False: "permission denied")
    monkeypatch.setattr(process_scan, "is_alive", lambda pid: True)

    code = KillCommand().execute(vars(parse_args(["kill"])))

    assert code == ExitCode.EXTERNAL_TOOL_ERROR
    assert "permission denied" in capsys.readouterr().out


def test_kill_with_nothing_running_mentions_the_mcp_server(monkeypatch, capsys):
    monkeypatch.setattr(process_scan, "scan_processes", lambda: [(13, 1, "dat mcp")])

    code = KillCommand().execute(vars(parse_args(["kill"])))

    assert code == ExitCode.SUCCESS
    out = capsys.readouterr().out
    assert "No running DAT GUI windows found." in out
    assert "1 MCP server still running" in out


def test_kill_surfaces_a_process_list_failure(monkeypatch, capsys):
    def explode():
        raise process_scan.ProcessScanError("could not run 'ps'")

    monkeypatch.setattr(process_scan, "scan_processes", explode)

    code = KillCommand().execute(vars(parse_args(["kill"])))

    assert code == ExitCode.EXTERNAL_TOOL_ERROR
    assert "Could not read the process list" in capsys.readouterr().out


def test_real_scan_returns_this_process():
    rows = process_scan.scan_processes()
    assert any(pid == os.getpid() for pid, _, _ in rows)


class TestPsPortability:
    """`ps` keyword support differs between procps (Linux) and BSD ps
    (macOS), so the scan tries several dialects and validates the result."""

    def _fake_run(self, accepted_keyword, calls):
        def run(command, **_kwargs):
            calls.append(command)
            if accepted_keyword not in command[-1]:
                return SimpleNamespace(returncode=1, stdout="", stderr="ps: illegal argument")
            row = f"{os.getpid()} 1 {os.getuid()} python3 -m dat.main gui\n"
            return SimpleNamespace(returncode=0, stdout=row, stderr="")

        return run

    def test_args_dialect_is_tried_first(self, monkeypatch):
        calls = []
        monkeypatch.setattr(process_scan.subprocess, "run", self._fake_run("args=", calls))

        rows = process_scan._scan_posix()

        assert len(calls) == 1
        assert rows and rows[0][0] == os.getpid()

    def test_it_falls_back_when_args_is_rejected(self, monkeypatch):
        calls = []
        monkeypatch.setattr(process_scan.subprocess, "run", self._fake_run("command=", calls))

        rows = process_scan._scan_posix()

        assert len(calls) > 1  # the args= form was tried and refused
        assert "command=" in calls[-1][-1]
        assert rows and rows[0][0] == os.getpid()

    def test_output_this_process_is_missing_from_is_rejected(self, monkeypatch):
        # ps accepted the flags but emitted columns in another order; acting
        # on those rows would mean signalling pids read from the wrong field.
        def run(command, **_kwargs):
            return SimpleNamespace(returncode=0, stdout="999999 1 0 something\n", stderr="")

        monkeypatch.setattr(process_scan.subprocess, "run", run)

        with pytest.raises(process_scan.ProcessScanError):
            process_scan._scan_posix()

    def test_a_missing_ps_binary_is_reported_clearly(self, monkeypatch):
        def run(_command, **_kwargs):
            raise FileNotFoundError("ps")

        monkeypatch.setattr(process_scan.subprocess, "run", run)

        with pytest.raises(process_scan.ProcessScanError, match="could not run 'ps'"):
            process_scan._scan_posix()

    def test_other_users_processes_are_filtered_out(self):
        rows = process_scan._parse_ps_output(
            f"{os.getpid()} 1 {os.getuid()} dat gui\n4242 1 {os.getuid() + 1} dat gui\n",
            os.getuid(),
        )
        assert [pid for pid, _, _ in rows] == [os.getpid()]

    def test_zombie_state_falls_back_to_the_bsd_keyword(self, monkeypatch):
        monkeypatch.setattr(process_scan.sys, "platform", "darwin")
        calls = []

        def run(command, **_kwargs):
            calls.append(command)
            if "state=" in command:
                return SimpleNamespace(returncode=1, stdout="", stderr="ps: illegal keyword")
            return SimpleNamespace(returncode=0, stdout="Z+\n", stderr="")

        monkeypatch.setattr(process_scan.subprocess, "run", run)

        assert process_scan._posix_state(4242) == "Z"
        assert any("stat=" in c for c in calls)