from typing import Any, Dict

from rich.console import Console

from dat.cli.console import FAIL, OK, WARN
from dat.cli.api_key import (
    is_valid_api_key,
    prompt_for_api_key,
    save_api_key,
    use_git_diff_mode,
)
from dat.commands.base import BaseCommand
from dat.utils.exit_codes import ExitCode


class SaveApiKeyCommand(BaseCommand):
    """`dat save-api-key` - store a Gemini API key (or clear a stored one).

    The way into the Gemini pillar at any time: a user who declined the key
    question at first, or who never had a key, isn't locked out of AI-written
    content by that answer.
    """

    def execute(self, args: Dict[str, Any]) -> ExitCode:
        console = Console()

        if args.get("clear"):
            if not self.container.config.ai_api_key:
                console.print("\n[yellow]No Gemini API key is stored.[/yellow] "
                              "Documents already use the Git diff for content.\n")
                return ExitCode.SUCCESS
            from_env = self.container.config.ai_key_from_env
            use_git_diff_mode(self.container)
            console.print(
                f"\n[green]{OK} Gemini API key removed.[/green] Documents will now list the changed "
                "files from your\n  Git diff, with test cases left empty.\n"
            )
            if from_env:
                # Nothing here can un-export a variable in the user's shell,
                # so say so rather than let the key silently come back.
                console.print(
                    f"[yellow]{WARN} That key came from $DAT_AI_KEY.[/yellow] Unset it "
                    "(or remove it from your shell profile),\n  otherwise DAT will pick it up "
                    "again on the next run.\n"
                )
            return ExitCode.SUCCESS

        console.print("\n[bold]Save your Gemini API key[/bold]")
        if self.container.config.ai_api_key:
            console.print(
                "[dim]A key is already stored; entering a new one replaces it "
                "(or run 'dat save-api-key --clear' to remove it).[/dim]"
            )
        console.print(
            "Once saved, DAT writes each document's summary and test cases from your branch diff.\n"
        )

        # A key passed on the command line skips the prompt - useful for
        # scripted setup - but goes through the same format check.
        api_key = (args.get("api_key") or "").strip()
        if api_key:
            if not is_valid_api_key(api_key):
                console.print(
                    f"[bold red]{FAIL} ERROR[/bold red] That doesn't look like a Gemini API key.\n"
                )
                return ExitCode.VALIDATION_ERROR
        else:
            api_key = prompt_for_api_key(console)

        if not api_key:
            console.print("[yellow]Cancelled - nothing was saved.[/yellow]\n")
            return ExitCode.SUCCESS

        save_api_key(self.container, api_key)
        console.print(
            f"\n[green]{OK} API key saved[/green] to "
            f"{self.container.configuration_service.config_file}\n"
            "  AI-written summaries and test cases are now enabled for every document.\n"
        )
        return ExitCode.SUCCESS
