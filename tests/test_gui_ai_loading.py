"""How the Preview Panel behaves while (and after) waiting on the AI.

The window opens with Git-diff content already in it, shows the wait, and
never lets a late or abandoned answer overwrite what the user sees. These
drive the real widget tree, so they need a display and are skipped without
one; the AI itself is never called - the summaries are handed in directly.
"""
import os
import sys
import unittest
from unittest import mock

from dat.models.doc_request import (
    SUMMARY_SOURCE_AI,
    SUMMARY_SOURCE_GIT_DIFF,
    ChangeSummary,
)
from dat.models.git_info import GitInfo

HAS_DISPLAY = bool(
    sys.platform in ("darwin", "win32")
    or os.environ.get("DISPLAY")
    or os.environ.get("WAYLAND_DISPLAY")
)
try:
    import customtkinter  # noqa: F401
    HAS_CTK = True
except Exception:
    HAS_CTK = False

GIT_INFO = GitInfo(
    branch_name="feature/NTRAK-1-Add-Sync",
    inferred_title="NTRAK-1 Add Sync",
    ticket_id="NTRAK-1",
    author_name="Dev",
    repo_name="repo",
    changed_files=["app/src/SyncService.kt", "app/res/layout/activity_main.xml"],
    recent_commits=[],
    raw_diff="+ fun sync() {}",
)

AI_SUMMARY = ChangeSummary(
    overview="AI overview",
    key_points=["AI wrote this point"],
    impact_areas=["Sync"],
    test_cases=["AI test case"],
    source=SUMMARY_SOURCE_AI,
)


@unittest.skipUnless(HAS_DISPLAY and HAS_CTK, "needs a display and customtkinter")
class TestPreviewPanelAiLoading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dat.gui.app import DATGuiApp
        from dat.utils.container import Container

        container = Container()
        container.config.ai_api_key = None  # no AI call fires on open
        container.git_service = mock.Mock()
        container.git_service.get_git_info.return_value = GIT_INFO

        # Building the widget tree costs ~2.5s, so the window is shared and
        # each test re-seeds it instead - the alternative is a suite slow
        # enough that people stop running it.
        try:
            cls.app = DATGuiApp(container=container)
            cls.app.withdraw()
        except Exception as e:
            # A display can be advertised and still be unusable - a macOS CI
            # runner with no window server, a broken Tk install. Skip rather
            # than fail a suite that has nothing to do with the GUI.
            raise unittest.SkipTest(f"cannot open a Tk window here: {e}")
        cls.addClassCleanup(cls.app.destroy)

    def setUp(self):
        self.app.state_model.summary_user_edited = False
        self.app._ai_attempt = 0
        self.app._ai_pending = False
        self.app._set_ai_status()
        self.app._load_initial_summary()  # back to the just-opened state

    # --- helpers ---
    @property
    def status(self) -> str:
        return self.app.preview_panel.status_label.cget("text")

    @property
    def retry_offered(self) -> bool:
        btn = self.app.preview_panel.status_action_btn
        # winfo_manager() rather than winfo_ismapped(): nothing inside a
        # withdrawn window reports as mapped.
        return btn.winfo_manager() == "pack" and "Retry" in btn.cget("text")

    def test_status_text_is_plain_ascii_so_it_renders_on_every_platform(self):
        """The resolved UI font differs per OS; a decorative glyph outside its
        coverage shows up as a missing-glyph box (macOS is the usual victim)."""
        panel = self.app.preview_panel
        self._pretend_waiting()

        seen = []
        for act in (lambda: self.app._on_ai_deadline_passed(1),
                    lambda: self.app._on_ai_summary_ready(1, AI_SUMMARY)):
            self._pretend_waiting()
            act()
            seen.append(panel.status_label.cget("text"))
            seen.append(panel.status_action_btn.cget("text"))

        for text in seen:
            self.assertTrue(text.isascii(), f"non-ASCII in status text: {text!r}")

    def test_action_button_is_wide_enough_for_its_label(self):
        """A CTkButton clips rather than grows, and macOS renders the same
        nominal font wider than Linux does."""
        panel = self.app.preview_panel
        self._pretend_waiting()
        self.app._on_ai_deadline_passed(1)

        label = panel.status_action_btn.cget("text")
        needed = panel._subtitle_font.measure(label)
        self.assertGreater(panel.status_action_btn.cget("width"), needed)

    def _pretend_waiting(self):
        self.app._ai_attempt = 1
        self.app._ai_pending = True

    # --- tests ---
    def test_opens_with_git_diff_content_not_an_empty_document(self):
        """The panel used to open blank and rewrite itself seconds later."""
        summary = self.app.state_model.summary
        self.assertEqual(summary.key_points, ["SyncService.kt", "activity_main.xml"])
        self.assertEqual(summary.test_cases, [], "test cases are the user's to write")
        self.assertEqual(summary.source, SUMMARY_SOURCE_GIT_DIFF)

    def test_no_ai_key_means_no_spinner(self):
        self.assertEqual(self.status, "")
        self.assertFalse(self.app._ai_pending)

    def test_ai_answer_replaces_the_seeded_content(self):
        self._pretend_waiting()
        self.app._on_ai_summary_ready(1, AI_SUMMARY)

        self.assertEqual(self.app.state_model.summary.key_points, ["AI wrote this point"])
        self.assertEqual(self.app.state_model.summary.test_cases, ["AI test case"])
        self.assertIn("AI summary applied", self.status)
        self.assertFalse(self.app._ai_pending)

    def test_timeout_keeps_the_git_diff_content_and_offers_a_retry(self):
        self._pretend_waiting()
        self.app._on_ai_deadline_passed(1)

        self.assertEqual(self.app.state_model.summary.key_points,
                         ["SyncService.kt", "activity_main.xml"])
        self.assertEqual(self.app.state_model.summary.test_cases, [])
        self.assertIn("timed out", self.status)
        self.assertTrue(self.retry_offered)

    def test_a_failed_call_reports_itself_rather_than_looking_like_ai_output(self):
        self._pretend_waiting()
        fallback = ChangeSummary(overview="o", key_points=["SyncService.kt"],
                                 source=SUMMARY_SOURCE_GIT_DIFF)
        self.app._on_ai_summary_ready(1, fallback)

        self.assertIn("AI unavailable", self.status)
        self.assertTrue(self.retry_offered)

    def test_an_answer_that_arrives_after_the_deadline_is_ignored(self):
        self._pretend_waiting()
        self.app._on_ai_deadline_passed(1)
        self.app._on_ai_summary_ready(1, AI_SUMMARY)  # the late reply

        self.assertEqual(self.app.state_model.summary.key_points,
                         ["SyncService.kt", "activity_main.xml"])
        self.assertIn("timed out", self.status)

    def test_a_superseded_attempts_answer_is_ignored(self):
        """Attempt 1 is abandoned, the user retries; attempt 1's late answer
        must not land while attempt 2 is still running."""
        self._pretend_waiting()
        self.app._ai_attempt = 2
        self.app._on_ai_summary_ready(1, AI_SUMMARY)

        self.assertEqual(self.app.state_model.summary.key_points,
                         ["SyncService.kt", "activity_main.xml"])

    def test_user_edits_are_never_clobbered_but_the_ai_text_stays_available(self):
        self._pretend_waiting()
        self.app.state_model.set_key_points(["My own point"])
        self.app.state_model.summary_user_edited = True

        self.app._on_ai_summary_ready(1, AI_SUMMARY)
        self.assertEqual(self.app.state_model.summary.key_points, ["My own point"])
        self.assertIn("your edits kept", self.status)

        # ...and the offered action swaps in the AI text on request.
        self.app.preview_panel.status_action_btn.invoke()
        self.assertEqual(self.app.state_model.summary.key_points, ["AI wrote this point"])

    def test_closing_cancels_the_ai_timers(self):
        self._pretend_waiting()
        self.app._ai_spinner_id = self.app.after(60_000, lambda: None)
        self.app._ai_watchdog_id = self.app.after(60_000, lambda: None)

        self.app._cancel_pending_jobs()

        self.assertFalse(self.app._ai_pending)
        self.assertIsNone(self.app._ai_spinner_id)
        self.assertIsNone(self.app._ai_watchdog_id)


if __name__ == "__main__":
    unittest.main()
