import json
import os
import sys
import time
from typing import Any, Dict, Optional, Tuple
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.console import Console
from dat.cli.api_key import ensure_ai_mode_chosen
from dat.cli.console import FAIL, OK, WARN
from dat.commands.base import BaseCommand
from dat.commands.doctor import tkinter_install_hint
from dat.models.doc_request import ChangeSummary
from dat.utils.exit_codes import ExitCode

class GenerateDocCommand(BaseCommand):
    def execute(self, args: Dict[str, Any]) -> ExitCode:
        console = Console()

        seed_file = args.get("seed_file")
        summary_override: Optional[ChangeSummary] = None
        seed_data: Dict[str, Any] = {}
        if seed_file:
            # Seed files are written by a programmatic caller (the MCP
            # server's 'open_preview' tool) handing off AI-authored content -
            # the summary is already final, so skip the content-pillar
            # question below entirely (this process is typically launched
            # detached, with no attached terminal to prompt on).
            summary_override, seed_data = self._load_seed_file(seed_file, console)
        else:
            # 1. Settle where the content comes from - a Gemini key if the
            # user has one, otherwise the Git diff. Optional by design: no
            # answer here can stop a document from being generated.
            ensure_ai_mode_chosen(self.container, console)

        output_path = args.get("output")
        title_override = args.get("title") or seed_data.get("title")
        ticket_override = args.get("ticket") or seed_data.get("ticket")
        author = args.get("author") or seed_data.get("author") or self.container.config.author_name
        approved_by = args.get("approved_by") or seed_data.get("approved_by") or ""
        image_paths = list(args.get("images") or seed_data.get("images") or [])
        fmt = args.get("format", "docx")

        # 2. The Preview Panel is the default destination for a generated
        # document: the user reviews the content, attaches screenshots by
        # drag-and-drop, and exports when satisfied - so once the window
        # opens, this command's job is done. Writing a file straight to disk
        # skips that review, so it has to be asked for with --headless.
        # (A seed file always implies preview: there'd be no other way to
        # see the content a programmatic caller handed over.)
        if not args.get("headless") or seed_file:
            return self._launch_gui_preview(
                console, title_override, ticket_override, author, approved_by, image_paths, summary_override
            )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
            transient=True
        ) as progress:
            
            task = progress.add_task("[cyan]Initializing generation...", total=100)
            
            progress.update(task, advance=10, description="[cyan]Analyzing Git repository...")
            time.sleep(0.3)
            
            progress.update(task, advance=20, description="[cyan]Processing screenshots...")
            
            summary_step = (
                "[cyan]Generating AI summary..." if self.container.config.ai_api_key
                else "[cyan]Collecting changed files from the Git diff..."
            )
            progress.update(task, advance=20, description=summary_step)
            
            try:
                res_path = self.container.document_service.generate_documentation(
                    output_path=output_path,
                    title_override=title_override,
                    author=author,
                    approved_by=approved_by,
                    ticket_override=ticket_override,
                    image_paths=image_paths,
                    output_format=fmt
                )
                
                progress.update(task, advance=50, description="[green]Finalizing document...")
                time.sleep(0.2)
                
                console.print(f"\n[bold green]{OK} SUCCESS[/bold green] Documentation generated successfully!")
                console.print(f"[bold blue]Location:[/bold blue] {res_path}\n")
                
                return ExitCode.SUCCESS
            except Exception as e:
                console.print(f"\n[bold red]{FAIL} ERROR[/bold red] Failed to generate documentation: {e}")
                return ExitCode.UNEXPECTED_ERROR

    def _load_seed_file(self, seed_file: str, console: Console) -> Tuple[Optional[ChangeSummary], Dict[str, Any]]:
        """Reads a JSON seed file (written by a programmatic caller such as
        the MCP server) and deletes it once read - it's a one-shot handoff,
        not a config file, so nothing should be left behind on disk.

        Malformed/unreadable seed files degrade gracefully: the Preview
        Panel still opens with defaults rather than the whole command
        crashing over bad handoff data.
        """
        try:
            with open(seed_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("seed file must contain a JSON object")
        except Exception as e:
            console.print(
                f"[yellow]{WARN} Could not read seed file '{seed_file}': {e}. "
                "Opening the Preview Panel without pre-filled content.[/yellow]"
            )
            data = {}
        finally:
            try:
                os.remove(seed_file)
            except OSError:
                pass

        summary_data = data.get("summary") or {}
        summary_override: Optional[ChangeSummary] = None
        if isinstance(summary_data, dict) and any(
            summary_data.get(k) for k in ("overview", "key_points", "impact_areas", "test_recommendations", "test_cases")
        ):
            summary_override = ChangeSummary(
                overview=summary_data.get("overview") or "",
                key_points=list(summary_data.get("key_points") or []),
                impact_areas=list(summary_data.get("impact_areas") or []),
                test_recommendations=list(summary_data.get("test_recommendations") or []),
                test_cases=list(summary_data.get("test_cases") or []),
            )

        return summary_override, data

    @staticmethod
    def _graphical_session_available() -> bool:
        """Whether a desktop session exists to open a window on.

        macOS and Windows always have one for a logged-in user; X11/Wayland
        advertise theirs through the environment, and its absence is what a
        headless server or an SSH session without forwarding looks like.
        """
        if sys.platform in ("darwin", "win32"):
            return True
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

    def _launch_gui_preview(
        self, console, title_override, ticket_override, author, approved_by, image_paths, summary_override=None
    ) -> ExitCode:
        if not self._graphical_session_available():
            console.print(
                f"\n[bold red]{FAIL} ERROR[/bold red] No graphical session is available, so the Preview "
                "Panel cannot open.\n"
                "  Run this from a desktop session, or forward a display over SSH (ssh -X).\n"
                "  To write the document straight to disk instead, re-run with [bold]--headless[/bold].\n"
            )
            return ExitCode.VALIDATION_ERROR

        try:
            import tkinter  # noqa: F401
        except ImportError:
            console.print(
                f"\n[bold red]{FAIL} ERROR[/bold red] The interactive Preview Panel requires "
                "Tkinter.\n"
                f"  {tkinter_install_hint()}\n"
                "  Or re-run with [bold]--headless[/bold] to write the document without it.\n"
            )
            return ExitCode.VALIDATION_ERROR

        from dat.gui import macos_compat
        macos_compat.apply()

        try:
            import customtkinter  # noqa: F401
        except ImportError:
            console.print(
                f"\n[bold red]{FAIL} ERROR[/bold red] The interactive Preview Panel requires "
                "the 'customtkinter' package. Install with:\n"
                "  pip install customtkinter tkinterdnd2\n"
                "  Or re-run with [bold]--headless[/bold] to write the document without it.\n"
            )
            return ExitCode.VALIDATION_ERROR
        except Exception as e:
            console.print(f"\n[bold red]{FAIL} ERROR[/bold red] customtkinter failed to load: {e}")
            return ExitCode.UNEXPECTED_ERROR

        from dat.gui.app import DATGuiApp

        try:
            app = DATGuiApp(
                container=self.container,
                title_override=title_override,
                ticket_override=ticket_override,
                author_override=author,
                approved_by_override=approved_by,
                image_paths=image_paths,
                summary_override=summary_override,
            )
            app.run()
        except Exception as e:
            console.print(f"\n[bold red]{FAIL} ERROR[/bold red] Preview Panel failed to start: {e}")
            return ExitCode.UNEXPECTED_ERROR

        return ExitCode.SUCCESS
