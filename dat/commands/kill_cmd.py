"""`dat kill` - close DAT windows that can no longer be closed normally."""
from typing import Any, Dict, List

from dat.commands.base import BaseCommand
from dat.utils.exit_codes import ExitCode
from dat.utils import process_scan
from dat.utils.process_scan import (
    DatProcess,
    ProcessScanError,
    WINDOW_KINDS,
    KIND_CLI,
    KIND_MCP,
)

DEFAULT_TIMEOUT = 5.0


def _print_table(processes: List[DatProcess]) -> None:
    print(f"{'PID':>8}  {'TYPE':<28}  COMMAND")
    for proc in processes:
        print(f"{proc.pid:>8}  {proc.label:<28}  {proc.short_command}")


class KillCommand(BaseCommand):
    def execute(self, args: Dict[str, Any]) -> ExitCode:
        include_all = bool(args.get("all"))
        list_only = bool(args.get("list_only"))
        force = bool(args.get("force"))
        timeout = float(args.get("timeout") or DEFAULT_TIMEOUT)

        kinds = None if include_all else WINDOW_KINDS

        try:
            targets = process_scan.find_dat_processes(kinds)
        except ProcessScanError as exc:
            print(f"[Error] Could not read the process list: {exc}")
            return ExitCode.EXTERNAL_TOOL_ERROR

        if not targets:
            scope = "DAT processes" if include_all else "DAT GUI windows"
            print(f"No running {scope} found.")
            if not include_all:
                skipped = self._other_kinds()
                if skipped:
                    print(f"({skipped} - run 'dat kill --all' to include those.)")
            return ExitCode.SUCCESS

        print(f"\nFound {len(targets)} DAT process{'es' if len(targets) != 1 else ''}:\n")
        _print_table(targets)
        print()

        if list_only:
            print("Nothing was stopped (--list). Re-run without --list to close them.")
            return ExitCode.SUCCESS

        failures: Dict[int, str] = {}
        for proc in targets:
            error = process_scan.request_stop(proc.pid, force=force)
            if error:
                failures[proc.pid] = error

        pending = [p.pid for p in targets if p.pid not in failures]
        survivors = process_scan.wait_for_exit(pending, timeout)

        # A Tk window wedged in a native modal loop can ignore SIGTERM
        # entirely; that's the exact situation this command exists for, so
        # escalate rather than report failure and leave the window up.
        if survivors and not force:
            print(f"{len(survivors)} process(es) did not exit within {timeout:g}s - forcing.")
            for pid in survivors:
                error = process_scan.request_stop(pid, force=True)
                if error:
                    failures[pid] = error
            survivors = process_scan.wait_for_exit(
                [pid for pid in survivors if pid not in failures], timeout
            )

        stopped = [p for p in targets if p.pid not in failures and p.pid not in survivors]
        for proc in stopped:
            print(f"  Closed  {proc.pid}  ({proc.label})")
        for pid in survivors:
            print(f"  FAILED  {pid}  (still running)")
        for pid, error in failures.items():
            print(f"  FAILED  {pid}  ({error})")

        if failures or survivors:
            print("\nSome processes could not be stopped. They may belong to another user or session.")
            return ExitCode.EXTERNAL_TOOL_ERROR

        print(f"\nStopped {len(stopped)} DAT process{'es' if len(stopped) != 1 else ''}.")
        return ExitCode.SUCCESS

    def _other_kinds(self) -> str:
        """Describes the non-window DAT processes left untouched, so a user
        who ran `dat kill` expecting it to cover an MCP server isn't left
        thinking DAT simply failed to see it."""
        try:
            others = process_scan.find_dat_processes((KIND_MCP, KIND_CLI))
        except ProcessScanError:
            return ""
        if not others:
            return ""
        mcp = sum(1 for p in others if p.kind == KIND_MCP)
        cli = len(others) - mcp
        parts = []
        if mcp:
            parts.append(f"{mcp} MCP server{'s' if mcp != 1 else ''}")
        if cli:
            parts.append(f"{cli} CLI command{'s' if cli != 1 else ''}")
        return " and ".join(parts) + " still running"
