import json
import os

import pytest

from dat.cli.args import parse_args
from dat.commands import mcp_setup_cmd
from dat.commands.mcp_setup_cmd import (
    CLIENTS,
    SHAPE_MCP_SERVERS,
    SHAPE_VSCODE,
    McpSetupCommand,
    resolve_client,
)
from dat.utils.exit_codes import ExitCode


@pytest.fixture
def launcher(monkeypatch):
    """Pin the launcher so the printed JSON is predictable."""
    monkeypatch.setattr(
        mcp_setup_cmd, "launcher_command", lambda: ("/opt/bin/dat", ["mcp"], None)
    )
    return "/opt/bin/dat"


@pytest.fixture(autouse=True)
def no_machine_probing(monkeypatch):
    """Keep the tests off the developer's real config directories."""
    monkeypatch.setattr(mcp_setup_cmd, "_existing_configs", lambda client: [])
    monkeypatch.setattr(mcp_setup_cmd, "_suggested_configs", lambda client: [])
    monkeypatch.setattr(mcp_setup_cmd, "_looks_installed", lambda client: False)


@pytest.mark.parametrize(
    "typed,expected_key",
    [
        ("vscode", "vscode"),
        ("vs code", "vscode"),
        ("VS-Code", "vscode"),
        ("copilot", "vscode"),
        ("android-studio", "android-studio"),
        ("android studio", "android-studio"),
        ("gemini", "android-studio"),
        ("claude", "claude-code"),
        ("claude-desktop", "claude-desktop"),
        ("kiro", "kiro"),
        ("intellij", "intellij"),
        ("jetbrains", "intellij"),
        ("antigravity", "antigravity"),
        ("cursor", "cursor"),
        ("other", "other"),
        ("1", "claude-code"),
    ],
)
def test_client_names_resolve_forgivingly(typed, expected_key):
    client = resolve_client(typed)
    assert client is not None and client.key == expected_key


@pytest.mark.parametrize("typed", ["", "emacs", "0", "99", "notepad"])
def test_unknown_client_names_resolve_to_nothing(typed):
    assert resolve_client(typed) is None


def _guide_for(key, capsys):
    code = McpSetupCommand().execute(vars(parse_args(["mcp-setup", key])))
    return code, capsys.readouterr().out


def _json_block(output):
    """The JSON snippet out of a printed guide."""
    start = output.index("{")
    depth = 0
    for offset, char in enumerate(output[start:], start=start):
        depth += (char == "{") - (char == "}")
        if depth == 0:
            return json.loads(output[start : offset + 1])
    raise AssertionError("no complete JSON object in the guide")


def test_every_client_prints_a_usable_snippet(launcher, capsys):
    for client in CLIENTS:
        code, output = _guide_for(client.key, capsys)
        assert code == ExitCode.SUCCESS
        assert client.name in output
        assert launcher in output

        config = _json_block(output)
        entry = config[client.shape]["dat"]
        assert entry["command"] == launcher
        assert entry["args"] == ["mcp"]
        # The single most common misconfiguration this guide exists to
        # prevent: the bare word `dat`, which a GUI-launched client cannot
        # resolve.
        assert entry["command"] != "dat"


def test_vscode_uses_its_own_config_shape(launcher, capsys):
    _, output = _guide_for("vscode", capsys)
    config = _json_block(output)

    assert SHAPE_VSCODE in config and SHAPE_MCP_SERVERS not in config
    assert config[SHAPE_VSCODE]["dat"]["type"] == "stdio"


def test_other_clients_use_the_mcp_servers_shape(launcher, capsys):
    _, output = _guide_for("android-studio", capsys)
    config = _json_block(output)

    assert SHAPE_MCP_SERVERS in config
    assert "type" not in config[SHAPE_MCP_SERVERS]["dat"]


def test_claude_code_gets_the_cli_shortcut_with_the_real_path(launcher, capsys):
    _, output = _guide_for("claude-code", capsys)
    assert f"claude mcp add dat -- {launcher} mcp" in output


def test_args_array_is_not_exploded_across_lines(launcher, capsys):
    _, output = _guide_for("kiro", capsys)
    assert '"args": ["mcp"]' in output


def test_guide_reports_an_existing_config_path(launcher, monkeypatch, capsys):
    monkeypatch.setattr(
        mcp_setup_cmd, "_existing_configs", lambda client: ["/home/me/.config/Google/AndroidStudio9/mcp.json"]
    )
    _, output = _guide_for("android-studio", capsys)
    assert "/home/me/.config/Google/AndroidStudio9/mcp.json" in output


def test_unknown_client_is_an_error_that_lists_the_options(launcher, capsys):
    code, output = _guide_for("emacs", capsys)
    assert code == ExitCode.VALIDATION_ERROR
    assert "Unknown client: emacs" in output
    assert "Android Studio" in output


def test_list_only_lists_without_a_guide(launcher, capsys):
    code = McpSetupCommand().execute(vars(parse_args(["mcp-setup", "--list"])))
    output = capsys.readouterr().out

    assert code == ExitCode.SUCCESS
    assert "Antigravity" in output
    assert '"mcpServers"' not in output


def test_non_interactive_run_does_not_block_on_input(launcher, monkeypatch, capsys):
    monkeypatch.setattr(mcp_setup_cmd.sys.stdin, "isatty", lambda: False)

    def fail_input(_prompt=""):
        raise AssertionError("input() must not be called without a terminal")

    monkeypatch.setattr("builtins.input", fail_input)

    code = McpSetupCommand().execute(vars(parse_args(["mcp-setup"])))

    assert code == ExitCode.SUCCESS
    assert "dat mcp-setup <name>" in capsys.readouterr().out


def test_interactive_selection_prints_that_clients_guide(launcher, monkeypatch, capsys):
    monkeypatch.setattr(mcp_setup_cmd.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "antigravity")

    code = McpSetupCommand().execute(vars(parse_args(["mcp-setup"])))

    assert code == ExitCode.SUCCESS
    assert "Connect DAT to Antigravity" in capsys.readouterr().out


def test_quitting_the_prompt_is_not_an_error(launcher, monkeypatch, capsys):
    monkeypatch.setattr(mcp_setup_cmd.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "q")

    assert McpSetupCommand().execute(vars(parse_args(["mcp-setup"]))) == ExitCode.SUCCESS


def test_ctrl_c_at_the_prompt_is_not_an_error(launcher, monkeypatch):
    monkeypatch.setattr(mcp_setup_cmd.sys.stdin, "isatty", lambda: True)

    def interrupt(_prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)

    assert McpSetupCommand().execute(vars(parse_args(["mcp-setup"]))) == ExitCode.SUCCESS


def test_list_marks_a_client_that_already_has_dat(monkeypatch, capsys):
    monkeypatch.setattr(
        mcp_setup_cmd,
        "_existing_configs",
        lambda client: ["/fake/mcp.json"] if client.key == "kiro" else [],
    )
    monkeypatch.setattr(
        mcp_setup_cmd, "_already_configured", lambda paths: paths[0] if paths else None
    )

    mcp_setup_cmd.print_client_list()
    output = capsys.readouterr().out

    kiro_line = next(line for line in output.splitlines() if "Kiro" in line)
    assert "already configured" in kiro_line


class TestDatServerDetection:
    """Recognising an existing DAT entry, in either config shape."""

    def test_launcher_entry_is_detected(self):
        assert mcp_setup_cmd._has_dat_server(
            {"mcpServers": {"dat-toolkit": {"command": "/home/me/.local/bin/dat", "args": ["mcp"]}}}
        )

    def test_module_entry_is_detected(self):
        assert mcp_setup_cmd._has_dat_server(
            {"servers": {"whatever": {"command": "/usr/bin/python3", "args": ["-m", "dat.main", "mcp"]}}}
        )

    def test_nested_project_config_is_detected(self):
        # Claude Code keeps a server map per project inside ~/.claude.json.
        assert mcp_setup_cmd._has_dat_server(
            {"projects": {"/home/me/app": {"mcpServers": {"dat": {"command": "/bin/dat", "args": ["mcp"]}}}}}
        )

    def test_an_unrelated_server_is_not_mistaken_for_dat(self):
        assert not mcp_setup_cmd._has_dat_server(
            {"mcpServers": {"github": {"command": "/usr/bin/npx", "args": ["-y", "@modelcontextprotocol/server-github"]}}}
        )

    def test_a_dat_command_without_the_mcp_arg_is_not_a_server(self):
        assert not mcp_setup_cmd._has_dat_server(
            {"mcpServers": {"dat": {"command": "/home/me/.local/bin/dat", "args": ["gui"]}}}
        )

    def test_empty_and_malformed_configs_are_safe(self):
        for payload in ({}, {"mcpServers": {}}, {"mcpServers": None}, [], "nonsense", None):
            assert not mcp_setup_cmd._has_dat_server(payload)


class TestLauncherDiscovery:
    def test_argv0_console_script_wins(self, monkeypatch, tmp_path):
        script = tmp_path / "dat"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)

        monkeypatch.setattr(mcp_setup_cmd.sys, "argv", [str(script), "mcp-setup"])
        launcher, found = mcp_setup_cmd.find_launcher()

        assert launcher == str(script)
        assert str(script) in found

    def test_macos_user_install_launcher_is_found(self, monkeypatch, tmp_path):
        # `pip install --user` on macOS writes the launcher under
        # ~/Library/Python/3.x/bin, which is site.USER_BASE + /bin and is
        # usually absent from a GUI app's PATH - so it has to be found here
        # rather than left to `which`.
        user_base = tmp_path / "Library" / "Python" / "3.11"
        (user_base / "bin").mkdir(parents=True)
        launcher = user_base / "bin" / "dat"
        launcher.write_text("#!/bin/sh\n")
        launcher.chmod(0o755)

        monkeypatch.setattr(mcp_setup_cmd.sys, "argv", ["/usr/bin/python3", "-m", "dat.main"])
        monkeypatch.setattr(mcp_setup_cmd.sysconfig, "get_path", lambda _name: "/usr/bin")
        monkeypatch.setattr(mcp_setup_cmd.sys, "executable", "/usr/bin/python3")
        monkeypatch.setattr(mcp_setup_cmd.site, "USER_BASE", str(user_base))
        monkeypatch.setattr(mcp_setup_cmd.shutil, "which", lambda _name: None)

        found, _ = mcp_setup_cmd.find_launcher()
        assert found == str(launcher)

    def test_falls_back_to_running_this_module(self, monkeypatch):
        monkeypatch.setattr(mcp_setup_cmd, "find_launcher", lambda: (None, []))
        command, args, warning = mcp_setup_cmd.launcher_command()

        assert command == mcp_setup_cmd.sys.executable
        assert args == ["-m", "dat.main", "mcp"]
        assert warning  # the user is told why the config looks different

    def test_a_non_executable_file_is_not_a_launcher(self, monkeypatch, tmp_path):
        script = tmp_path / "dat"
        script.write_text("")
        script.chmod(0o644)

        monkeypatch.setattr(mcp_setup_cmd.sys, "argv", [str(script)])
        monkeypatch.setattr(mcp_setup_cmd.shutil, "which", lambda _name: None)
        monkeypatch.setattr(mcp_setup_cmd.sysconfig, "get_path", lambda _name: str(tmp_path))
        monkeypatch.setattr(mcp_setup_cmd.sys, "executable", str(tmp_path / "python3"))
        monkeypatch.setattr(mcp_setup_cmd.site, "USER_BASE", str(tmp_path / "userbase"))

        launcher, _ = mcp_setup_cmd.find_launcher()
        assert launcher is None


def test_config_root_follows_the_platform(monkeypatch):
    monkeypatch.setattr(mcp_setup_cmd.os, "name", "posix")
    monkeypatch.setattr(mcp_setup_cmd.sys, "platform", "darwin")
    assert mcp_setup_cmd._config_root().endswith("Library/Application Support")

    monkeypatch.setattr(mcp_setup_cmd.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/cfg")
    assert mcp_setup_cmd._config_root() == "/tmp/cfg"


def test_windows_paths_are_escaped_in_the_json(monkeypatch, capsys):
    monkeypatch.setattr(
        mcp_setup_cmd,
        "launcher_command",
        lambda: ("C:\\Users\\me\\AppData\\Roaming\\Python\\Scripts\\dat.exe", ["mcp"], None),
    )
    _, output = _guide_for("claude-desktop", capsys)

    # json.dumps does the escaping; a hand-built string would emit invalid
    # JSON here and the user would paste a broken config.
    assert "C:\\\\Users\\\\me" in output
    assert _json_block(output)["mcpServers"]["dat"]["command"].startswith("C:\\Users")


def test_suggested_path_uses_a_versioned_directory_that_exists(monkeypatch, tmp_path):
    ide_dir = tmp_path / "JetBrains" / "IntelliJIdea2026.1"
    ide_dir.mkdir(parents=True)
    monkeypatch.setattr(mcp_setup_cmd, "_config_root", lambda: str(tmp_path))
    monkeypatch.undo()  # drop the autouse stub for this one check
    monkeypatch.setattr(mcp_setup_cmd, "_config_root", lambda: str(tmp_path))

    client = resolve_client("intellij")
    suggested = mcp_setup_cmd._suggested_configs(client)

    assert os.path.join(str(ide_dir), "mcp.json") in suggested