import argparse
from typing import List, Optional

def parse_args(args_list: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dat",
        description="Developer Automation Toolkit (DAT_CLI) - Cross-platform CLI & MCP Server"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available DAT commands")

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

    # dat doctor
    subparsers.add_parser("doctor", help="Run system diagnostics & verify tool dependencies")

    # dat config
    cfg_parser = subparsers.add_parser("config", help="View or initialize DAT configuration")
    cfg_parser.add_argument("action", nargs="?", choices=["show", "init"], default="show", help="Action to perform")

    # dat mcp
    mcp_parser = subparsers.add_parser(
        "mcp", help="Start the DAT MCP (Model Context Protocol) stdio server for AI agent/IDE integration"
    )
    mcp_parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Server log verbosity, written to stderr only (default: WARNING, or $DAT_MCP_LOG_LEVEL)",
    )

    return parser.parse_args(args_list)
