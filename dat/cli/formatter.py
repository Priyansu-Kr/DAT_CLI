from rich.console import Console
from rich.panel import Panel

ACCENT = "#007bff"

COMMANDS = [
    ("dat generate-doc", "Generate DOCX/Markdown docs from git + AI"),
    ("dat generate-doc -s", "Open the interactive Preview Panel (GUI)"),
    ("dat gui", "Launch the DAT Control Center dashboard"),
    ("dat doctor", "Run environment diagnostics"),
    ("dat config", "View or initialize configuration"),
]


def print_banner():
    # Fixed width so the layout is identical whether run in a wide terminal,
    # a narrow one, or piped/redirected (non-TTY output defaults vary by
    # environment) - this is static content, it doesn't need to reflow.
    console = Console(width=80)

    header = (
        f"[bold {ACCENT}]D[/bold {ACCENT}][bold white]eveloper "
        f"[/bold white][bold {ACCENT}]A[/bold {ACCENT}][bold white]utomation "
        f"[/bold white][bold {ACCENT}]T[/bold {ACCENT}][bold white]oolkit[/bold white]\n"
        "[dim italic]CLI-First  •  IDE Independent  •  MCP Server Ready[/dim italic]"
    )

    commands = "\n".join(
        f"  [bold {ACCENT}]{cmd:<20}[/bold {ACCENT}] [white]{desc}[/white]"
        for cmd, desc in COMMANDS
    )

    console.print(
        Panel(
            f"{header}\n\n{commands}",
            border_style=ACCENT,
            padding=(1, 3),
            title="[bold white]DAT[/bold white]",
            title_align="left",
        )
    )
    console.print(f"[dim]Run[/dim] [bold {ACCENT}]dat --help[/bold {ACCENT}] [dim]for full flag reference.[/dim]\n")
