import argparse
from typing import List, Optional

def parse_args(args_list: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dat",
        description="Developer Automation Toolkit (DAT_CLI) - Cross-platform CLI & MCP Server"
    )

    # `metavar` is spelled out rather than left to argparse so the choices
    # line lists only the commands a person types. `mcp` is deliberately
    # absent: it's a stdio JSON-RPC server an MCP client starts on your
    # behalf (see "MCP Integration.md"), and typing it at a prompt just
    # produces a process that appears to hang while it waits for a client
    # that will never speak. It stays fully supported - `dat mcp` and
    # `dat mcp --help` work exactly as before - it's only unadvertised.
    subparsers = parser.add_subparsers(
        dest="command",
        metavar="{generate-doc,save-api-key,gui,kill,mcp-setup,doctor,config}",
        help="Available DAT commands",
    )

    # dat generate-doc
    doc_parser = subparsers.add_parser("generate-doc", help="Generate DOCX or Markdown documentation from git branch/diff and screenshots")
    doc_parser.add_argument("-o", "--output", help="Output file path (optional, defaults to title name)")
    doc_parser.add_argument("-t", "--title", help="Override document title (defaults to parsed git branch name)")
    doc_parser.add_argument("-k", "--ticket", help="Override ticket ID (e.g., JIRA-1042)")
    doc_parser.add_argument("-a", "--author", help="Override author name")
    doc_parser.add_argument("--approved-by", help="Name of the approver for the 'Approved By' field")
    doc_parser.add_argument("-i", "--images", nargs="*", help="Explicit image file paths to include")
    doc_parser.add_argument(
        "-s", "--select-images", action="store_true",
        help="Open the interactive Preview Panel (GUI). This is the default; kept for compatibility",
    )
    doc_parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Write the document straight to disk without opening the Preview Panel. Use only for "
            "automation/CI - by default the panel opens so the document can be reviewed and "
            "screenshots attached before export"
        ),
    )
    doc_parser.add_argument(
        "--seed-file",
        dest="seed_file",
        help=(
            "Path to a JSON file with pre-filled content (title/ticket/author/approved_by/images/summary) "
            "to seed the Preview Panel with - implies --select-images. The file is deleted after being "
            "read. Intended for programmatic callers (e.g. the DAT MCP server's 'open_preview' tool); not "
            "normally passed by hand."
        ),
    )
    doc_parser.add_argument("-f", "--format", choices=["docx", "md"], default="docx", help="Output document format")

    # dat save-api-key
    key_parser = subparsers.add_parser(
        "save-api-key",
        help="Save (or clear) your Gemini API key to enable AI-written summaries and test cases",
    )
    key_parser.add_argument(
        "api_key",
        nargs="?",
        help="The key itself. Omit it to be prompted (safer - it stays out of your shell history)",
    )
    key_parser.add_argument(
        "--clear",
        action="store_true",
        help="Remove the stored key and build documents from the Git diff instead",
    )

    # dat gui
    subparsers.add_parser("gui", help="Launch the DAT Control Center GUI dashboard")

    # dat kill
    kill_parser = subparsers.add_parser(
        "kill",
        help="Close stuck DAT GUI windows (only DAT processes - other Python programs are left alone)",
        description=(
            "Close DAT GUI windows that can no longer be closed normally - typically a Preview "
            "Panel an MCP client launched detached, which belongs to no terminal. Only real DAT "
            "processes are touched (the 'dat' launcher, 'python -m dat.main', 'dat/main.py'); "
            "your other Python programs, and this command's own process, are never targeted. "
            "Each window is asked to close first and force-terminated only if it ignores that."
        ),
    )
    kill_parser.add_argument(
        "-a", "--all",
        action="store_true",
        help="Also stop DAT MCP servers and other DAT CLI processes, not just GUI windows",
    )
    kill_parser.add_argument(
        "-l", "--list",
        dest="list_only",
        action="store_true",
        help="Show what would be stopped without stopping anything",
    )
    kill_parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Kill immediately instead of first asking each window to close",
    )
    kill_parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Seconds to wait for a graceful exit before forcing (default: 5)",
    )

    # dat mcp-setup
    setup_parser = subparsers.add_parser(
        "mcp-setup",
        help="Connect DAT's MCP server to your IDE or AI agent (step-by-step, with the JSON)",
        description=(
            "Print step-by-step instructions for connecting DAT's MCP server to an IDE or AI "
            "agent, with your own launcher path already filled into the JSON and the config "
            "file located on this machine. Run without arguments to pick your client from a "
            "list."
        ),
    )
    setup_parser.add_argument(
        "client",
        nargs="?",
        help=(
            "Which client to set up: claude-code, claude-desktop, kiro, intellij, vscode, "
            "cursor, android-studio, antigravity, or other. Omit to choose from a list"
        ),
    )
    setup_parser.add_argument(
        "-l", "--list",
        dest="list_only",
        action="store_true",
        help="Just list the supported clients and which ones are on this machine",
    )

    # dat doctor
    subparsers.add_parser("doctor", help="Run system diagnostics & verify tool dependencies")

    # dat config
    cfg_parser = subparsers.add_parser(
        "config",
        help="View or change DAT configuration (author name/email, output dir, git path)",
        description=(
            "Show DAT's configuration, or change one value with 'set'. The author name you set "
            "here is what appears as 'Created By' on documents DAT generates.\n\n"
            "  dat config                                 show everything\n"
            '  dat config set author-name "Your Name"     set the document author\n'
            "  dat config set author-email you@work.com   set the author email\n"
            "  dat config set author-name                 prompt for the value\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cfg_parser.add_argument(
        "action", nargs="?", choices=["show", "init", "set"], default="show", help="Action to perform"
    )
    cfg_parser.add_argument(
        "key",
        nargs="?",
        help="With 'set': which setting - author-name, author-email, output-dir, git-path",
    )
    cfg_parser.add_argument(
        "value",
        nargs="?",
        help="With 'set': the new value. Omit it to be prompted (useful for names with spaces)",
    )

    # dat mcp - intentionally without `help=`, which is what keeps it out of
    # the command list on `dat --help`. `description` still shows on
    # `dat mcp --help`, so anyone writing an MCP client config can read it.
    mcp_parser = subparsers.add_parser(
        "mcp",
        description=(
            "Start the DAT MCP (Model Context Protocol) stdio server. This is launched for "
            "you by an MCP client (Android Studio, VS Code, Claude Code) via its config file, "
            "not run by hand - on a terminal it will simply wait for JSON-RPC on stdin. "
            'Configure it with "command": "<path to dat>", "args": ["mcp"]. '
            'See "MCP Integration.md".'
        ),
    )
    mcp_parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Server log verbosity, written to stderr only (default: WARNING, or $DAT_MCP_LOG_LEVEL)",
    )

    return parser.parse_args(args_list)
