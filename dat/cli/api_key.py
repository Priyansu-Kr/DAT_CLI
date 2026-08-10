"""Gemini API key: validation, prompting and persistence.

One home for the key handling shared by `dat save-api-key` and the optional
question `dat generate-doc` asks, so the format check and the "a saved key
means the Gemini pillar" rule can't drift apart between them.
"""

import re
import sys
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm, Prompt

from dat.cli.console import FAIL, OK
from dat.models.config_model import (
    AI_PROVIDER_GEMINI,
    AI_PROVIDER_GIT_DIFF,
    ai_choice_made,
)

GEMINI_KEY_URL = "https://aistudio.google.com/app/apikey"

# Deliberately loose: Google has changed key length and prefix over time, so
# this rejects obvious mistakes (a pasted URL, a truncated key, stray quotes)
# without rejecting a valid key it hasn't seen before.
_KEY_MIN_LENGTH = 30
_KEY_MAX_LENGTH = 65
_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9\._-]+$")


def is_valid_api_key(api_key: Optional[str]) -> bool:
    if not api_key:
        return False
    return bool(
        _KEY_MIN_LENGTH <= len(api_key) <= _KEY_MAX_LENGTH and _KEY_PATTERN.match(api_key)
    )


def prompt_for_api_key(console: Console) -> Optional[str]:
    """Ask for a key until a well-formed one is given.

    Returns None when the user backs out with an empty line - an escape hatch
    that matters now the key is optional: there has to be a way out of the
    prompt that isn't "paste something wrong".
    """
    console.print(f"Get a free key at: [blue]{GEMINI_KEY_URL}[/blue]")
    console.print("[dim](press Enter on an empty line to cancel)[/dim]\n")

    while True:
        api_key = Prompt.ask(
            "[bold cyan]Enter your Gemini API key[/bold cyan]",
            default="",
            # An empty default is the cancel path, not something to advertise
            # as "()" in the prompt.
            show_default=False,
        ).strip()

        if not api_key:
            return None
        if is_valid_api_key(api_key):
            return api_key

        console.print(
            f"[red]{FAIL} That doesn't look like a Gemini API key.[/red] "
            f"Expected {_KEY_MIN_LENGTH}-{_KEY_MAX_LENGTH} characters, "
            "letters/digits/._- only.\n"
        )


def apply_gemini_mode(container, api_key: str) -> None:
    """Switch this process onto the Gemini pillar, without touching disk."""
    container.config.ai_api_key = api_key
    container.config.ai_provider = AI_PROVIDER_GEMINI
    container.ai_service.adapter.api_key = api_key
    container.ai_service.adapter.provider = AI_PROVIDER_GEMINI


def save_api_key(container, api_key: str) -> None:
    """Persist the key and switch every path - this process included - onto
    the Gemini pillar."""
    apply_gemini_mode(container, api_key)
    # A key the user typed is theirs to keep, so it stops being the
    # environment's copy and gets written to the config file.
    container.config.ai_key_from_env = False
    container.configuration_service.save_config(container.config)


def use_git_diff_mode(container) -> None:
    """Record that the user declined AI content, so they are never asked
    again and documents are built from the Git diff instead."""
    container.config.ai_api_key = None
    container.config.ai_key_from_env = False
    container.config.ai_provider = AI_PROVIDER_GIT_DIFF
    container.ai_service.adapter.api_key = None
    container.ai_service.adapter.provider = AI_PROVIDER_GIT_DIFF
    container.configuration_service.save_config(container.config)


def stdin_is_interactive() -> bool:
    """Whether there's a terminal to answer a question on. False for CI, a
    piped stdin, or a detached launch - asking there would either hang or
    crash on EOF."""
    try:
        return bool(sys.stdin is not None and sys.stdin.isatty())
    except (AttributeError, ValueError):
        # ValueError: stdin exists but is already closed.
        return False


def ensure_ai_mode_chosen(container, console: Console, interactive: Optional[bool] = None) -> None:
    """Make sure a content pillar is settled before a document is generated.

    Asked once, never again: a key that's already saved means Gemini (repair
    a stale provider on the way past), and a previous "no" stays a no. When
    nothing has been chosen yet the user is offered the choice - answering
    "n" is a first-class answer, not a failure, so this never blocks
    generation and has no exit code to report.
    """
    cfg = container.config

    if cfg.ai_api_key:
        if cfg.ai_provider != AI_PROVIDER_GEMINI:
            # A key saved by an older DAT version that never flipped
            # ai_provider off its default - repair it so the key gets used.
            apply_gemini_mode(container, cfg.ai_api_key)
            if not cfg.ai_key_from_env:
                container.configuration_service.save_config(cfg)
        return

    if ai_choice_made(cfg.ai_provider, cfg.ai_api_key):
        return  # already answered "no" - stay quiet, use the Git diff

    if interactive is None:
        interactive = stdin_is_interactive()

    if not interactive:
        # No terminal to answer on (CI, a detached launch). Fall back to the
        # Git diff for this run without recording a choice the user never made.
        container.ai_service.adapter.api_key = None
        container.ai_service.adapter.provider = AI_PROVIDER_GIT_DIFF
        return

    _print_choice_intro(console)

    try:
        wants_ai = Confirm.ask(
            "[bold cyan]Do you have a Gemini API key?[/bold cyan]", default=False
        )
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]No answer given - continuing without AI for this run.[/yellow]\n")
        container.ai_service.adapter.api_key = None
        container.ai_service.adapter.provider = AI_PROVIDER_GIT_DIFF
        return

    if wants_ai:
        api_key = prompt_for_api_key(console)
        if api_key:
            save_api_key(container, api_key)
            console.print(f"[green]{OK} API key saved. AI-written summaries are now enabled.[/green]\n")
            return
        console.print("[yellow]No key entered - continuing without AI.[/yellow]")

    use_git_diff_mode(container)
    _print_git_diff_notice(console)


def _print_choice_intro(console: Console) -> None:
    console.print("\n[bold]How should this document's content be written?[/bold]")
    console.print(
        "  With a [bold]Gemini API key[/bold] (free), DAT reads the branch diff and writes a "
        "precise summary of\n  the changes plus test cases for them."
    )
    console.print(
        "  [bold]Without one[/bold], the document still gets built: 'Changes Done' lists the files "
        "your work\n  touched, and you fill in the test cases yourself.\n"
    )


def _print_git_diff_notice(console: Console) -> None:
    console.print(
        f"[green]{OK} Continuing without AI.[/green] 'Changes Done' will list the changed files from "
        "your Git diff,\n  and test cases are left empty for you to write."
    )
    console.print(
        "  You won't be asked again - run [bold]dat save-api-key[/bold] whenever you want "
        "AI-written content.\n"
    )
