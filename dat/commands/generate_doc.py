import json
import os
import sys
import time
from typing import Any, Dict, Optional, Tuple
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.console import Console
from dat.commands.base import BaseCommand
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
            # the summary is already final, so skip the AI-key prompt below
            # entirely (this process is typically launched detached, with no
            # attached terminal to prompt on).
            summary_override, seed_data = self._load_seed_file(seed_file, console)
        else:
            # 1. Check for AI API Key first
            api_key = self.container.config.ai_api_key
            if not api_key:
                console.print("\n[bold yellow]⚠ Gemini API Key Missing[/bold yellow]")
                console.print("To use AI-powered summaries, please provide your free Gemini API key.")
                console.print("You can get one at: [blue]https://aistudio.google.com/app/apikey[/blue]\n")

                from rich.prompt import Prompt
                import re

                while True:
                    api_key = Prompt.ask("[bold cyan]Enter your Gemini API key[/bold cyan]")

                    # Professional Validation (Flexible):
                    # 1. Minimum length of 30 characters
                    # 2. Maximum length of 65 characters
                    # 3. Only contains letters, numbers, dots, dashes, or underscores
                    import re
                    if api_key and 30 <= len(api_key) <= 65 and re.match(r"^[a-zA-Z0-9\._-]+$", api_key):
                        break
                    else:
                        console.print("[red]✘ Invalid API Key format.[/red]")
                        if not api_key: return ExitCode.VALIDATION_ERROR

                if api_key:
                    # Update current session config
                    self.container.config.ai_api_key = api_key
                    self.container.ai_service.adapter.api_key = api_key
                    # Save it permanently so they aren't asked again
                    self.container.configuration_service.save_config(self.container.config)
                    console.print("[green]✔ API Key saved successfully.[/green]\n")
                else:
                    console.print("[red]✘ Error: API Key is required to proceed.[/red]")
                    return ExitCode.VALIDATION_ERROR

        output_path = args.get("output")
        title_override = args.get("title") or seed_data.get("title")
        ticket_override = args.get("ticket") or seed_data.get("ticket")
        author = args.get("author") or seed_data.get("author") or self.container.config.author_name
        approved_by = args.get("approved_by") or seed_data.get("approved_by") or ""
        image_paths = list(args.get("images") or seed_data.get("images") or [])
        fmt = args.get("format", "docx")

        # 2. Interactive mode: open the DAT Control Center GUI instead of
        # generating headlessly. The Preview Panel lets the user configure,
        # attach screenshots (drag-and-drop), and export directly - so once
        # the window opens, this command's job is done. A seed file always
        # implies preview mode - there'd be no other way to see its content.
        if args.get("select_images") or seed_file:
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
            
            progress.update(task, advance=20, description="[cyan]Generating AI summary...")
            
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
                
                console.print(f"\n[bold green]✔ SUCCESS[/bold green] Documentation generated successfully!")
                console.print(f"[bold blue]Location:[/bold blue] {res_path}\n")
                
                return ExitCode.SUCCESS
            except Exception as e:
                console.print(f"\n[bold red]✘ ERROR[/bold red] Failed to generate documentation: {e}")
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
                f"[yellow]⚠ Could not read seed file '{seed_file}': {e}. "
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

    def _launch_gui_preview(
        self, console, title_override, ticket_override, author, approved_by, image_paths, summary_override=None
    ) -> ExitCode:
        try:
            import tkinter  # noqa: F401
        except ImportError:
            console.print(
                "\n[bold red]✘ ERROR[/bold red] The interactive Preview Panel (-s) requires "
                "Tkinter.\n"
                "  Linux: sudo apt install python3-tk\n"
                "  Windows/macOS: Tkinter ships with the standard python.org installer.\n"
            )
            return ExitCode.VALIDATION_ERROR

        from dat.gui import macos_compat
        macos_compat.apply()

        try:
            import customtkinter  # noqa: F401
        except ImportError:
            console.print(
                "\n[bold red]✘ ERROR[/bold red] The interactive Preview Panel (-s) requires "
                "the 'customtkinter' package. Install with:\n"
                "  pip install customtkinter tkinterdnd2\n"
            )
            return ExitCode.VALIDATION_ERROR
        except Exception as e:
            console.print(f"\n[bold red]✘ ERROR[/bold red] customtkinter failed to load: {e}")
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
            console.print(f"\n[bold red]✘ ERROR[/bold red] Preview Panel failed to start: {e}")
            return ExitCode.UNEXPECTED_ERROR

        return ExitCode.SUCCESS
