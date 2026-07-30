import sys
import os
import time
import platform
import subprocess
from typing import Dict, Any
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.console import Console
from dat.commands.base import BaseCommand
from dat.utils.exit_codes import ExitCode

class GenerateDocCommand(BaseCommand):
    def execute(self, args: Dict[str, Any]) -> ExitCode:
        console = Console()
        
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
        title_override = args.get("title")
        ticket_override = args.get("ticket")
        author = args.get("author") or self.container.config.author_name
        image_paths = list(args.get("images") or [])
        capture_adb = args.get("adb", False)
        fmt = args.get("format", "docx")

        # 2. Feature: Open file dialog to select multiple images from computer
        if args.get("select_images"):
            selected = []
            
            # 1. Try macOS Native Picker (Bypasses the tkinter crash)
            if platform.system() == "Darwin":
                try:
                    script = (
                        'set theFiles to choose file with prompt '
                        '"Select Screenshots to include in Documentation" '
                        'of type {"png", "jpg", "jpeg", "webp"} '
                        'with multiple selections allowed\n'
                        'set thePaths to {}\n'
                        'repeat with aFile in theFiles\n'
                        '    set end of thePaths to POSIX path of aFile\n'
                        'end repeat\n'
                        'set AppleScript\'s text item delimiters to linefeed\n'
                        'return thePaths as text'
                    )
                    result = subprocess.run(
                        ["osascript", "-e", script],
                        capture_output=True, text=True
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        selected = [p for p in result.stdout.strip().split("\n") if p]
                except Exception as e:
                    console.print(f"[yellow]Native Mac picker failed, trying fallback: {e}[/yellow]")

            # 2. Fallback to Tkinter for Windows/Linux (or if Mac script failed)
            if not selected:
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    root = tk.Tk()
                    root.withdraw()
                    # Ensure the window stays on top
                    root.attributes("-topmost", True)
                    selected = filedialog.askopenfilenames(
                        title="Select Screenshots to include in Documentation",
                        filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.webp")]
                    )
                    root.destroy()
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not open file dialog: {e}[/yellow]")

            if selected:
                image_paths.extend(list(selected))

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
                    ticket_override=ticket_override,
                    image_paths=image_paths,
                    capture_adb=capture_adb,
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
