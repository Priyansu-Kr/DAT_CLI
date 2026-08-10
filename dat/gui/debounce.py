"""Call coalescing for keystroke-driven work (preview redraw, file writes).

`Debouncer` is the usual trailing-edge debounce with a *max wait*: it runs
once the caller has been idle for `delay_ms`, but if calls keep arriving it
still runs every `max_delay_ms` so a continuous typist keeps seeing progress
instead of nothing until they stop.

Scheduling is injected (Tk's ``after``/``after_cancel`` in the app, a fake
clock in tests), so the timing logic is unit-testable without a display.
"""
import time
from typing import Callable, Optional


class Debouncer:
    def __init__(
        self,
        action: Callable[[], None],
        delay_ms: int,
        max_delay_ms: Optional[int] = None,
        schedule: Optional[Callable[[int, Callable[[], None]], object]] = None,
        cancel: Optional[Callable[[object], None]] = None,
        monotonic: Optional[Callable[[], float]] = None,
    ):
        if delay_ms < 0:
            raise ValueError("delay_ms must not be negative")
        if max_delay_ms is not None and max_delay_ms < delay_ms:
            raise ValueError("max_delay_ms must be >= delay_ms")

        self._action = action
        self._delay_ms = delay_ms
        self._max_delay_ms = max_delay_ms
        self._schedule = schedule
        self._cancel = cancel
        self._monotonic = monotonic or time.monotonic

        self._job: Optional[object] = None
        self._first_trigger: Optional[float] = None

    # --- State ----------------------------------------------------------

    @property
    def is_pending(self) -> bool:
        return self._job is not None

    # --- Control --------------------------------------------------------

    def trigger(self) -> None:
        """Register a call; the action runs later (or now, without a scheduler)."""
        if self._schedule is None:
            self._action()
            return

        now = self._monotonic()
        if self._first_trigger is None:
            self._first_trigger = now

        wait_ms = self._delay_ms
        if self._max_delay_ms is not None:
            elapsed_ms = (now - self._first_trigger) * 1000.0
            remaining_ms = self._max_delay_ms - elapsed_ms
            # Never push the run past the max wait, and never schedule a
            # negative delay if it is already overdue.
            wait_ms = max(0, min(wait_ms, remaining_ms))

        self._cancel_job()
        self._job = self._schedule(int(wait_ms), self._run)

    def flush(self) -> bool:
        """Run a pending action right now. True if it ran."""
        if not self.is_pending:
            return False
        self._cancel_job()
        self._first_trigger = None
        self._action()
        return True

    def cancel(self) -> None:
        """Drop a pending action without running it."""
        self._cancel_job()
        self._first_trigger = None

    # --- Internals ------------------------------------------------------

    def _run(self) -> None:
        self._job = None
        self._first_trigger = None
        self._action()

    def _cancel_job(self) -> None:
        if self._job is None:
            return
        if self._cancel is not None:
            try:
                self._cancel(self._job)
            except Exception:
                # A job that already fired is not cancellable; harmless.
                pass
        self._job = None
