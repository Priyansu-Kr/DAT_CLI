"""`dat mcp-setup` - a per-client walkthrough for connecting DAT's MCP server.

Connecting an MCP client is a small task with a lot of ways to get it subtly
wrong: the wrong config file for your IDE, `"servers"` where the client wants
`"mcpServers"`, or - by far the most common - the bare word `dat` as the
command, which fails because a GUI-launched client never sources the shell rc
file that defines it (see "MCP Integration.md" §3).

So rather than a document the user has to translate to their machine, this
prints the config with *their* launcher path already substituted, pointing at
the config file that actually exists on *this* machine, and says whether DAT
is already wired up there.
"""
import glob
import json
import os
import re
import shutil
import site
import sys
import sysconfig
import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from dat.commands.base import BaseCommand
from dat.utils.exit_codes import ExitCode

# The two config shapes in the wild. Most clients took Claude Desktop's
# "mcpServers"; VS Code went its own way with "servers" plus an explicit
# transport type.
SHAPE_MCP_SERVERS = "mcpServers"
SHAPE_VSCODE = "servers"


@dataclass
class Client:
    key: str
    name: str
    # Globs (relative to the OS config root, or absolute with ~) that locate
    # a real config file. Globbed rather than fixed because JetBrains-family
    # IDEs version their config directory: AndroidStudio2026.1.1, and so on.
    config_globs: List[str] = field(default_factory=list)
    # Shown when no config file exists yet - the path the user should create.
    config_hint: str = ""
    # Directories/binaries that mean "this client is installed here", for
    # clients whose config file only appears after the first server is added.
    presence_globs: List[str] = field(default_factory=list)
    presence_binaries: List[str] = field(default_factory=list)
    shape: str = SHAPE_MCP_SERVERS
    ui_route: str = ""
    cli_shortcut: str = ""
    # Some clients keep a machine-wide config that is discoverable (good for
    # "is DAT already set up?") but is not the file a user should hand-edit -
    # Claude Code's ~/.claude.json being the case in point, where the
    # documented route is a per-project .mcp.json.
    prefer_hint: bool = False
    include_cwd: bool = True
    steps_tail: List[str] = field(default_factory=list)
    verify: str = ""
    caveat: str = ""


def _config_root() -> str:
    """Where this OS keeps per-application config."""
    if os.name == "nt":
        return os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support")
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def _expand(pattern: str) -> str:
    if pattern.startswith("~") or os.path.isabs(pattern):
        return os.path.expanduser(pattern)
    return os.path.join(_config_root(), pattern)


CLIENTS: List[Client] = [
    Client(
        key="claude-code",
        name="Claude Code (CLI)",
        config_globs=["~/.claude.json"],
        config_hint="<your project>/.mcp.json",
        presence_binaries=["claude"],
        prefer_hint=True,
        include_cwd=False,
        cli_shortcut="claude mcp add dat -- {launcher} mcp",
        steps_tail=[
            "Add `-s user` to the `claude mcp add` command above to get DAT in every project "
            "instead of only this one.",
            "The `.mcp.json` form is committable, so checking it in gives your whole team DAT "
            "without each person running the command.",
        ],
        verify="`claude mcp list`, or type `/mcp` inside Claude Code - 'dat' should be connected.",
    ),
    Client(
        key="claude-desktop",
        name="Claude Desktop",
        config_globs=["Claude/claude_desktop_config.json"],
        config_hint=os.path.join(_config_root(), "Claude", "claude_desktop_config.json"),
        presence_globs=["Claude"],
        ui_route="Claude menu -> Settings -> Developer -> Edit Config",
        steps_tail=["Restart Claude Desktop completely (quit, don't just close the window)."],
        verify="DAT's tools appear under the tool icon in the chat composer.",
    ),
    Client(
        key="kiro",
        name="Kiro",
        config_globs=["~/.kiro/settings/mcp.json"],
        config_hint="<your project>/.kiro/settings/mcp.json  (or ~/.kiro/settings/mcp.json for all projects)",
        presence_globs=["~/.kiro"],
        presence_binaries=["kiro"],
        prefer_hint=True,
        ui_route="Kiro panel -> MCP Servers -> edit config",
        steps_tail=[
            'Kiro also accepts `"disabled": false` and `"autoApprove": []` per server; both are optional.',
            "Reconnect the server from the MCP Servers panel - Kiro picks the file up without a restart.",
        ],
        verify="The MCP Servers panel lists 'dat' as connected, with its tools underneath.",
    ),
    Client(
        key="intellij",
        name="IntelliJ IDEA / other JetBrains IDEs",
        config_globs=["JetBrains/*/mcp.json", "~/.config/JetBrains/*/mcp.json"],
        config_hint=os.path.join(_config_root(), "JetBrains", "<IDE><version>", "mcp.json"),
        presence_globs=["JetBrains/*"],
        ui_route="Settings -> Tools -> AI Assistant -> Model Context Protocol (MCP) -> + -> paste as JSON",
        steps_tail=[
            "The UI route is the reliable one: it writes the file itself, so you don't have to "
            "guess your IDE's config directory name.",
        ],
        verify="The MCP list shows 'dat' with a green/connected state; ask AI Assistant to run dat doctor.",
    ),
    Client(
        key="vscode",
        name="VS Code (GitHub Copilot agent mode)",
        config_globs=["Code/User/mcp.json", "Code - Insiders/User/mcp.json"],
        config_hint=(
            "<your project>/.vscode/mcp.json"
            '   (or the machine-wide one via "MCP: Open User Configuration")'
        ),
        presence_globs=["Code", "Code - Insiders"],
        presence_binaries=["code"],
        prefer_hint=True,
        shape=SHAPE_VSCODE,
        ui_route='Command Palette -> "MCP: Add Server" (or "MCP: Open User Configuration")',
        steps_tail=[
            'VS Code is the odd one out: the top key is `"servers"`, not `"mcpServers"`, and each '
            'entry needs `"type": "stdio"`. Copying another client\'s snippet here silently does nothing.',
            'Click "Start" on the server in mcp.json, then pick DAT\'s tools in Copilot Chat\'s '
            "agent-mode tool picker.",
        ],
        verify='Copilot Chat -> agent mode -> tools picker lists the "dat" tools.',
    ),
    Client(
        key="cursor",
        name="Cursor",
        config_globs=["~/.cursor/mcp.json"],
        config_hint="<your project>/.cursor/mcp.json   (or ~/.cursor/mcp.json for every project)",
        presence_globs=["~/.cursor", "Cursor"],
        presence_binaries=["cursor"],
        prefer_hint=True,
        ui_route="Settings -> MCP -> Add new MCP server",
        steps_tail=["Toggle the server on in Settings -> MCP; Cursor reloads it without a restart."],
        verify="Settings -> MCP shows 'dat' with a green dot and its tool list.",
    ),
    Client(
        key="android-studio",
        name="Android Studio (Gemini)",
        config_globs=["Google/AndroidStudio*/mcp.json", "~/.config/Google/AndroidStudio*/mcp.json"],
        config_hint=os.path.join(_config_root(), "Google", "AndroidStudio<version>", "mcp.json"),
        presence_globs=["Google/AndroidStudio*"],
        steps_tail=["Restart Android Studio, then open the Gemini panel."],
        verify='Ask Gemini "check my environment with dat" - it should call DAT\'s run_doctor tool.',
    ),
    Client(
        key="antigravity",
        name="Antigravity",
        config_globs=["~/.gemini/config/mcp_config.json"],
        config_hint=os.path.expanduser("~/.gemini/config/mcp_config.json"),
        presence_globs=["Antigravity", "~/.antigravity-ide"],
        ui_route="Settings -> MCP servers -> View raw config",
        steps_tail=["Hit Refresh/Reload in the MCP servers panel after saving."],
        verify="The MCP servers panel shows 'dat' with its tool count.",
    ),
    Client(
        key="other",
        name="Any other MCP client",
        config_hint="whichever file your client documents (look for 'mcpServers')",
        steps_tail=[
            "Every stdio MCP client needs the same two things: a command and its arguments. "
            "That is all DAT needs from you - there is no port, URL, or token.",
            'If your client cannot set a per-server `"cwd"`, leave it out and pass `repo_path` '
            "in each tool call instead.",
        ],
        verify="Your client lists 'dat' among its connected servers.",
    ),
]


def find_launcher() -> Tuple[Optional[str], List[str]]:
    """The absolute path to the `dat` launcher, plus every candidate found.

    Deliberately not `shutil.which` alone: after `setup.sh`, `dat` is a shell
    alias that no MCP client can use and that `which` cannot see from inside
    Python, while the real launcher sits in the venv's scripts directory.
    """
    exe = "dat.exe" if os.name == "nt" else "dat"
    candidates: List[str] = []

    # argv[0] when DAT was started through its own console script - the most
    # direct evidence of which launcher the user actually invokes.
    argv0 = sys.argv[0] or ""
    if os.path.basename(argv0).lower() in ("dat", "dat.exe"):
        candidates.append(os.path.abspath(argv0))

    for directory in (
        sysconfig.get_path("scripts"),
        os.path.dirname(sys.executable),
        os.path.join(getattr(site, "USER_BASE", "") or "", "Scripts" if os.name == "nt" else "bin"),
    ):
        if directory:
            candidates.append(os.path.join(directory, exe))

    on_path = shutil.which("dat")
    if on_path:
        candidates.append(os.path.abspath(on_path))

    found: List[str] = []
    for candidate in candidates:
        if candidate not in found and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            found.append(candidate)

    return (found[0] if found else None), found


def launcher_command() -> Tuple[str, List[str], Optional[str]]:
    """(command, args, warning) for the config file.

    Falls back to `<interpreter> -m dat.main mcp`, which is a fully valid way
    to start the server, when no launcher script can be located - better than
    printing a path that doesn't exist.
    """
    launcher, _ = find_launcher()
    if launcher:
        return launcher, ["mcp"], None
    return (
        sys.executable,
        ["-m", "dat.main", "mcp"],
        "No 'dat' launcher script was found, so the config below starts the server through "
        "this Python interpreter instead. That works, but it breaks if this interpreter or "
        "virtualenv is removed.",
    )


def _existing_configs(client: Client) -> List[str]:
    paths: List[str] = []
    for pattern in client.config_globs:
        for hit in sorted(glob.glob(_expand(pattern))):
            if hit not in paths:
                paths.append(hit)
    return paths


def _suggested_configs(client: Client) -> List[str]:
    """Where the config file *would* go, for a client that has none yet.

    Globs only the directory part, so an IDE that keeps a versioned config
    directory (JetBrains/IntelliJIdea2026.1, Google/AndroidStudio2026.1.1)
    yields the real path on this machine instead of a `<version>`
    placeholder the user has to resolve by hand.
    """
    suggested: List[str] = []
    for pattern in client.config_globs:
        parent_pattern, filename = os.path.split(_expand(pattern))
        if not filename or "*" in filename:
            continue
        for directory in sorted(glob.glob(parent_pattern)):
            candidate = os.path.join(directory, filename)
            if os.path.isdir(directory) and candidate not in suggested:
                suggested.append(candidate)
    return suggested


def _looks_installed(client: Client) -> bool:
    if _existing_configs(client):
        return True
    for pattern in client.presence_globs:
        if glob.glob(_expand(pattern)):
            return True
    return any(shutil.which(binary) for binary in client.presence_binaries)


def _already_configured(paths: List[str]) -> Optional[str]:
    """The first config file that already contains a DAT server entry."""
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if _has_dat_server(data):
            return path
    return None


def _has_dat_server(data: Any) -> bool:
    """Whether a parsed config declares a server that launches DAT.

    Searches recursively because a client may nest its server map (Claude
    Code keeps one per project inside ~/.claude.json).
    """
    if isinstance(data, dict):
        for key in (SHAPE_MCP_SERVERS, SHAPE_VSCODE):
            servers = data.get(key)
            if isinstance(servers, dict):
                for entry in servers.values():
                    if isinstance(entry, dict) and _entry_is_dat(entry):
                        return True
        return any(_has_dat_server(value) for value in data.values())
    if isinstance(data, list):
        return any(_has_dat_server(item) for item in data)
    return False


def _entry_is_dat(entry: Dict[str, Any]) -> bool:
    command = str(entry.get("command") or "")
    args = [str(a) for a in (entry.get("args") or [])]
    stem = os.path.basename(command.replace("\\", "/")).lower()
    if stem in ("dat", "dat.exe") and "mcp" in args:
        return True
    return "dat.main" in args and "mcp" in args


def _compact_arrays(rendered: str) -> str:
    """Put short string arrays back on one line.

    `json.dumps(indent=2)` explodes `["mcp"]` across three lines, which is
    valid but reads like a mistake in a snippet the user is about to copy.
    """
    return re.sub(
        r"\[\s*\n\s*((?:\"[^\"\n]*\",?\s*\n\s*)+)\]",
        lambda m: "[" + ", ".join(part.strip().rstrip(",") for part in m.group(1).strip().splitlines()) + "]",
        rendered,
    )


def _server_json(client: Client, command: str, args: List[str], include_cwd: bool) -> str:
    entry: Dict[str, Any] = {}
    if client.shape == SHAPE_VSCODE:
        entry["type"] = "stdio"
    entry["command"] = command
    entry["args"] = args
    if include_cwd:
        entry["cwd"] = os.getcwd()
    return _compact_arrays(json.dumps({client.shape: {"dat": entry}}, indent=2))


def _indent(text: str, prefix: str = "     ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def _wrap(text: str, width: int = 76, prefix: str = "     ") -> str:
    return "\n".join(textwrap.wrap(text, width=width, initial_indent=prefix, subsequent_indent=prefix))


def _numbered(step: int, text: str, width: int = 76) -> str:
    return "\n".join(
        textwrap.wrap(text, width=width, initial_indent=f"  {step}. ", subsequent_indent="     ")
    )


def print_client_list(highlight_detected: bool = True) -> None:
    print("\nWhich IDE or AI agent are you connecting DAT to?\n")
    for index, client in enumerate(CLIENTS, start=1):
        marker = ""
        if highlight_detected and client.key != "other":
            configs = _existing_configs(client)
            if _already_configured(configs):
                marker = "  <- DAT already configured"
            elif _looks_installed(client):
                marker = "  <- found on this machine"
        print(f"  {index}) {client.name}{marker}")
    print()


def resolve_client(name: str) -> Optional[Client]:
    """A client by number, key, or a forgiving name match."""
    name = name.strip().lower()
    if not name:
        return None
    if name.isdigit():
        index = int(name)
        if 1 <= index <= len(CLIENTS):
            return CLIENTS[index - 1]
        return None

    squashed = name.replace(" ", "").replace("_", "").replace("-", "")
    for client in CLIENTS:
        key_squashed = client.key.replace("-", "")
        if squashed in (key_squashed, client.key) or key_squashed.startswith(squashed):
            return client
    for client in CLIENTS:
        if squashed and squashed in client.name.lower().replace(" ", ""):
            return client
    return None


def print_guide(client: Client) -> None:
    command, args, warning = launcher_command()
    configs = _existing_configs(client)
    configured_in = _already_configured(configs)

    print()
    print(f"=== Connect DAT to {client.name} ===")
    print()
    print(f"  Launcher : {command}")
    if args[:1] != ["mcp"]:
        print(f"  Args     : {json.dumps(args)}")
    print(f"  Check it : {command} doctor        (should print the environment report)")
    if warning:
        print()
        print(_wrap("NOTE: " + warning, prefix="  "))

    step = 1
    print()

    if client.cli_shortcut:
        print(f"  {step}. Fastest route - run this from your project directory:")
        print()
        print(_indent(client.cli_shortcut.format(launcher=command)))
        print()
        step += 1

    if client.ui_route:
        print(f"  {step}. Open the config through the UI:")
        print()
        print(_indent(client.ui_route))
        print()
        step += 1

    print(f"  {step}. Open (or create) the config file:")
    print()
    suggested = [] if client.prefer_hint else (configs or _suggested_configs(client))
    if suggested:
        for path in suggested:
            print(_indent(path))
        if not configs:
            print(_wrap("(It does not exist yet - creating it is fine.)"))
        elif len(suggested) > 1:
            print()
            print(_wrap("(More than one exists - edit the one belonging to the version you run.)"))
    else:
        print(_indent(client.config_hint or "see your client's documentation"))
        if not client.prefer_hint:
            print(_wrap("(It does not exist yet - creating it is fine.)"))
    print()
    step += 1

    print(f'  {step}. Add the "dat" server, merging it into any servers already in the file:')
    print()
    print(_indent(_server_json(client, command, args, include_cwd=client.include_cwd and client.key != "other")))
    print()
    step += 1

    if client.include_cwd and client.key != "other":
        print(f"  {step}. `cwd` above is this directory. Point it at the project you want")
        print("     documented, or delete the line and pass `repo_path` per tool call.")
        print()
        step += 1

    for tail in client.steps_tail:
        print(_numbered(step, tail))
        print()
        step += 1

    if client.verify:
        print("  Verify:")
        print(_wrap(client.verify))
        print()

    if configured_in:
        print(_wrap(f"Good news: {configured_in} already declares a DAT server, so this may "
                    f"just need a restart of {client.name}.", prefix="  "))
        print()

    print(_wrap("Never use the bare word 'dat' as the command: a client launched from a dock "
                "or menu never reads your shell rc file, so it cannot resolve it (and after "
                "setup.sh, 'dat' is only a shell alias). Always the absolute path above.",
                prefix="  "))
    print()
    print("  Full reference, including the tools DAT exposes: \"MCP Integration.md\"")
    print()


class McpSetupCommand(BaseCommand):
    def execute(self, args: Dict[str, Any]) -> ExitCode:
        requested = args.get("client")

        if args.get("list_only"):
            print_client_list()
            print("Run 'dat mcp-setup <name>' for step-by-step setup, e.g. 'dat mcp-setup vscode'.\n")
            return ExitCode.SUCCESS

        if requested:
            client = resolve_client(requested)
            if client is None:
                print(f"\nUnknown client: {requested}")
                print_client_list(highlight_detected=False)
                return ExitCode.VALIDATION_ERROR
            print_guide(client)
            return ExitCode.SUCCESS

        print_client_list()

        if not sys.stdin.isatty():
            # Piped or redirected: there is nobody to answer the prompt, so
            # say how to ask for a guide directly instead of hanging.
            print("Run 'dat mcp-setup <name>' for step-by-step setup, e.g. 'dat mcp-setup android-studio'.\n")
            return ExitCode.SUCCESS

        try:
            answer = input(f"Select 1-{len(CLIENTS)} (or q to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return ExitCode.SUCCESS

        if not answer or answer.lower() in ("q", "quit", "exit"):
            print()
            return ExitCode.SUCCESS

        client = resolve_client(answer)
        if client is None:
            print(f"\n'{answer}' isn't one of the options - run 'dat mcp-setup' again.\n")
            return ExitCode.VALIDATION_ERROR

        print_guide(client)
        return ExitCode.SUCCESS
