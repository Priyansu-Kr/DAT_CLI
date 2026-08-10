import unittest

from dat.gui.debounce import Debouncer


class FakeScheduler:
    """Deterministic stand-in for Tk's after()/after_cancel() plus a clock."""

    def __init__(self):
        self.now = 0.0
        self._jobs = {}
        self._next_id = 0

    # --- injected into Debouncer ---------------------------------------

    def schedule(self, delay_ms, callback):
        self._next_id += 1
        job_id = f"job{self._next_id}"
        self._jobs[job_id] = (self.now + delay_ms / 1000.0, callback)
        return job_id

    def cancel(self, job_id):
        self._jobs.pop(job_id, None)

    def monotonic(self):
        return self.now

    # --- test driving ---------------------------------------------------

    def advance(self, ms):
        """Move time forward, running anything that comes due."""
        target = self.now + ms / 1000.0
        while True:
            due = [(t, jid, cb) for jid, (t, cb) in self._jobs.items() if t <= target]
            if not due:
                break
            due.sort()
            fire_at, job_id, callback = due[0]
            self.now = fire_at
            del self._jobs[job_id]
            callback()
        self.now = target

    @property
    def pending(self):
        return len(self._jobs)


class TestDebouncer(unittest.TestCase):
    def setUp(self):
        self.clock = FakeScheduler()
        self.runs = []

    def make(self, delay_ms=200, max_delay_ms=None):
        return Debouncer(
            lambda: self.runs.append(self.clock.now),
            delay_ms=delay_ms,
            max_delay_ms=max_delay_ms,
            schedule=self.clock.schedule,
            cancel=self.clock.cancel,
            monotonic=self.clock.monotonic,
        )

    def test_runs_once_after_the_idle_delay(self):
        debouncer = self.make(delay_ms=200)
        debouncer.trigger()

        self.clock.advance(150)
        self.assertEqual(self.runs, [])
        self.clock.advance(100)
        self.assertEqual(len(self.runs), 1)

    def test_a_burst_of_calls_collapses_into_one_run(self):
        debouncer = self.make(delay_ms=200)
        for _ in range(20):
            debouncer.trigger()
            self.clock.advance(20)  # faster than the delay
        self.assertEqual(self.runs, [])

        self.clock.advance(200)
        self.assertEqual(len(self.runs), 1)

    def test_max_wait_keeps_a_continuous_typist_updated(self):
        debouncer = self.make(delay_ms=200, max_delay_ms=500)
        # Keystrokes every 50ms would postpone an idle-only debounce forever.
        for _ in range(40):
            debouncer.trigger()
            self.clock.advance(50)

        self.assertGreaterEqual(len(self.runs), 3)
        gaps = [b - a for a, b in zip(self.runs, self.runs[1:])]
        for gap in gaps:
            self.assertLessEqual(gap, 0.55, gaps)

    def test_without_max_wait_a_continuous_burst_never_runs(self):
        debouncer = self.make(delay_ms=200)
        for _ in range(40):
            debouncer.trigger()
            self.clock.advance(50)
        self.assertEqual(self.runs, [])

    def test_separate_bursts_run_separately(self):
        debouncer = self.make(delay_ms=100)
        debouncer.trigger()
        self.clock.advance(150)
        debouncer.trigger()
        self.clock.advance(150)
        self.assertEqual(len(self.runs), 2)

    def test_flush_runs_immediately_and_clears_the_job(self):
        debouncer = self.make(delay_ms=1000)
        debouncer.trigger()
        self.assertTrue(debouncer.is_pending)

        self.assertTrue(debouncer.flush())
        self.assertEqual(len(self.runs), 1)
        self.assertFalse(debouncer.is_pending)

        self.clock.advance(2000)
        self.assertEqual(len(self.runs), 1)  # the scheduled job did not also fire

    def test_flush_with_nothing_pending_does_nothing(self):
        debouncer = self.make()
        self.assertFalse(debouncer.flush())
        self.assertEqual(self.runs, [])

    def test_cancel_drops_the_pending_run(self):
        debouncer = self.make(delay_ms=100)
        debouncer.trigger()
        debouncer.cancel()

        self.clock.advance(500)
        self.assertEqual(self.runs, [])
        self.assertFalse(debouncer.is_pending)

    def test_cancel_resets_the_max_wait_window(self):
        debouncer = self.make(delay_ms=200, max_delay_ms=400)
        debouncer.trigger()
        self.clock.advance(150)      # still inside the idle delay
        debouncer.cancel()
        self.assertEqual(self.runs, [])

        # A fresh window: the next call waits the full idle delay again
        # rather than inheriting 150ms of the cancelled max wait.
        debouncer.trigger()
        self.clock.advance(150)
        self.assertEqual(self.runs, [])
        self.clock.advance(100)
        self.assertEqual(len(self.runs), 1)

    def test_runs_synchronously_without_a_scheduler(self):
        runs = []
        debouncer = Debouncer(lambda: runs.append(1), delay_ms=500)
        debouncer.trigger()
        self.assertEqual(runs, [1])
        self.assertFalse(debouncer.is_pending)

    def test_rejects_a_max_wait_below_the_delay(self):
        with self.assertRaises(ValueError):
            self.make(delay_ms=300, max_delay_ms=100)

    def test_rejects_a_negative_delay(self):
        with self.assertRaises(ValueError):
            self.make(delay_ms=-1)

    def test_a_dead_cancel_callback_does_not_escape(self):
        def exploding_cancel(_job):
            raise RuntimeError("window already gone")

        debouncer = Debouncer(
            lambda: self.runs.append(1), delay_ms=100,
            schedule=self.clock.schedule, cancel=exploding_cancel,
            monotonic=self.clock.monotonic,
        )
        debouncer.trigger()
        debouncer.cancel()  # must not raise
        self.assertFalse(debouncer.is_pending)


if __name__ == "__main__":
    unittest.main()
