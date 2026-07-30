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
    doc_parser.add_argument("-s", "--select-images", action="store_true", help="Open the interactive Preview Panel (GUI) to configure, attach screenshots via drag-and-drop, and export")
    doc_parser.add_argument("--adb", action="store_true", help="Automatically capture screenshot from connected Android device via ADB")
    doc_parser.add_argument("-f", "--format", choices=["docx", "md"], default="docx", help="Output document format")

    # dat screenshot
    ss_parser = subparsers.add_parser("screenshot", help="Capture screenshot from connected Android device via ADB")
    ss_parser.add_argument("-o", "--output", default="screenshot.png", help="Output screenshot path")
    ss_parser.add_argument("-d", "--device", help="Specific ADB device serial number")

    # dat gui
    subparsers.add_parser("gui", help="Launch the DAT Control Center GUI dashboard")

    # dat doctor
    subparsers.add_parser("doctor", help="Run system diagnostics & verify tool dependencies")

    # dat config
    cfg_parser = subparsers.add_parser("config", help="View or initialize DAT configuration")
    cfg_parser.add_argument("action", nargs="?", choices=["show", "init"], default="show", help="Action to perform")

    return parser.parse_args(args_list)
