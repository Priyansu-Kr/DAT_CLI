"""DATGuiApp: the DAT Control Center main window.

Built on CustomTkinter (Tk) - CPU/software rasterized, no GPU required, so
it runs unmodified inside headless VMs and remote desktops.
"""
import os
import queue
import sys
import threading
from tkinter import filedialog, messagebox
from typing import List, Optional

from dat.gui import macos_compat
macos_compat.apply()

import customtkinter as ctk

try:
    from tkinterdnd2 import TkinterDnD
    _DND_MIXIN = (ctk.CTk, TkinterDnD.DnDWrapper)
except ImportError:
    TkinterDnD = None
    _DND_MIXIN = (ctk.CTk,)

from dat.gui import theme
from dat.gui.debounce import Debouncer
from dat.gui.panels.control_panel import ControlPanel
from dat.gui.panels.preview_panel import PreviewPanel
from dat.gui.state import (
    GuiState,
    build_preview_content,
    editable_list_tokens,
    structure_toggle_items,
)
from dat.gui.widgets.template_content_editor import CHANGE_ACTION, CHANGE_TEXT
from dat.gui.windows.template_builder import TemplateBuilderWindow
from dat.adapters.ai_adapter import build_git_diff_summary, deadline_for_diff
from dat.models.doc_request import SUMMARY_SOURCE_AI, ChangeSummary
from dat.models.git_info import GitInfo
from dat.models.template_model import DocumentTemplate, TemplateError
from dat.services.ai_service import default_change_summary
from dat.utils.container import Container


# Typing in the Control Center's content editor fires on every keystroke, so
# both the preview redraw and the template file write are coalesced. Each has
# a max wait as well as an idle delay: a continuous typist still sees the
# preview keep up (and their work still reaches disk) instead of nothing at
# all until they stop.
PREVIEW_DEBOUNCE_MS = 220
PREVIEW_MAX_WAIT_MS = 900
AUTOSAVE_DEBOUNCE_MS = 900
AUTOSAVE_MAX_WAIT_MS = 5000

# AI progress chip: how fast the dots animate, how long a success message
# lingers, and how much slack the watchdog gives the HTTP layer's own deadline
# before it declares the wait over on the UI's behalf.
AI_SPINNER_INTERVAL_MS = 400
AI_STATUS_CLEAR_MS = 4000
AI_WATCHDOG_GRACE_SECONDS = 3
# How often the main thread checks whether the AI worker has finished. Short
# enough that the content appears immediately once the answer is in.
AI_POLL_INTERVAL_MS = 120
# Status-chip states. Only the "applied" message auto-clears; a warning
# stays until the user acts on it.
AI_STATUS_APPLIED = "applied"


def _patch_scrollable_frame_string_widget_bug() -> None:
    """Some Linux/VM Tk builds deliver `event.widget` as the widget's string
    path name instead of the resolved widget object during mouse-wheel
    events. CTkScrollableFrame.check_if_master_is_canvas recurses on
    `widget.master` and crashes with `AttributeError: 'str' object has no
    attribute 'master'`. Resolve the string via nametowidget() before
    delegating to the original logic.

    The method's name (and its presence) has moved between customtkinter
    releases - it was `_check_if_valid_scroll` in some versions, and is
    `check_if_master_is_canvas` in 5.2.2. Patch whichever exists; do nothing
    if neither does, rather than crashing the whole GUI at import time.
    """
    method_name = next(
        (
            name
            for name in ("check_if_master_is_canvas", "_check_if_valid_scroll")
            if hasattr(ctk.CTkScrollableFrame, name)
        ),
        None,
    )
    if method_name is None:
        return

    original = getattr(ctk.CTkScrollableFrame, method_name)
    if getattr(original, "_dat_string_widget_patched", False):
        return

    def _patched(self, widget):
        if isinstance(widget, str):
            try:
                widget = self.nametowidget(widget)
            except KeyError:
                return False
        return original(self, widget)

    _patched._dat_string_widget_patched = True
    setattr(ctk.CTkScrollableFrame, method_name, _patched)


_patch_scrollable_frame_string_widget_bug()


class DATGuiApp(*_DND_MIXIN):
    def __init__(
        self,
        container: Optional[Container] = None,
        title_override: Optional[str] = None,
        ticket_override: Optional[str] = None,
        author_override: Optional[str] = None,
        approved_by_override: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        summary_override: Optional[ChangeSummary] = None,
    ):
        super().__init__()
        if TkinterDnD is not None:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception:
                pass

        # Arial/Inter aren't installed by default on most Linux systems -
        # pick the closest available match now that a Tk root exists.
        theme.resolve_fonts()

        self.container = container or Container.get_instance()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("DAT Control Center")
        self.geometry("1280x800")
        self.minsize(960, 600)
        self.configure(fg_color=theme.BG_DEEP_DARK)

        # GitService already guarantees a usable default GitInfo even when
        # git itself is unavailable/misbehaves, but guard here too so a
        # truly unexpected error can't stop the window from opening at all.
        try:
            git_info = self.container.git_service.get_git_info()
        except Exception as e:
            print(f"[Warning] Could not read git info, using defaults: {e}")
            git_info = GitInfo(
                branch_name="standalone-repo",
                inferred_title="Software Feature Documentation",
                author_name="Developer",
            )
        self.state_model = GuiState.from_git_info(
            git_info, author=author_override or self.container.config.author_name
        )
        if title_override:
            self.state_model.topic = title_override
        if ticket_override:
            self.state_model.ticket_id = ticket_override
        if approved_by_override:
            self.state_model.approved_by = approved_by_override

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.control_panel = ControlPanel(
            self,
            on_ticket_change=self._on_ticket_change,
            on_topic_change=self._on_topic_change,
            on_author_change=self._on_author_change,
            on_approved_by_change=self._on_approved_by_change,
            on_toggle_change=self._on_toggle_change,
            on_impact_areas_change=self._on_impact_areas_change,
            on_key_points_change=self._on_key_points_change,
            on_test_cases_change=self._on_test_cases_change,
            on_files_added=self._on_files_added,
            on_file_removed=self._on_file_removed,
            on_reorder=self._on_reorder,
            on_assign_test_case=self._on_assign_test_case,
            on_create_template=self._on_create_template,
            on_edit_template=self._on_edit_template,
            on_duplicate_template=self._on_duplicate_template,
            on_delete_template=self._on_delete_template,
            on_template_selected=self._on_template_selected,
            on_template_content_change=self._on_template_content_change,
            on_token_list_change=self._on_token_list_change,
        )
        self.control_panel.grid(row=0, column=0, sticky="nsw")

        self.preview_panel = PreviewPanel(self, on_export=self._on_export)
        self.preview_panel.grid(row=0, column=1, sticky="nsew")

        self.control_panel.set_ticket_id(self.state_model.ticket_id)
        self.control_panel.set_topic(self.state_model.topic)
        self.control_panel.set_author(self.state_model.author)
        self.control_panel.set_approved_by(self.state_model.approved_by)

        # Restore the custom document structure the user last worked with so
        # reopening the app shows the same layout they built.
        self._builder_window: Optional[TemplateBuilderWindow] = None
        self._content_dirty = False
        self._closing = False
        # AI request bookkeeping: an attempt counter so a superseded or
        # abandoned answer can be recognised and ignored, plus the timer ids
        # that have to be cancelled when it settles or the window closes.
        self._ai_attempt = 0
        self._ai_pending = False
        self._ai_results: "queue.Queue" = queue.Queue()
        self._ai_watchdog_id = None
        self._ai_spinner_id = None
        self._ai_poll_id = None
        self._ai_spinner_frame = 0
        self._ai_status_text = ""
        self._ai_status_kind = ""
        self._preview_debounce = Debouncer(
            self._refresh_preview,
            delay_ms=PREVIEW_DEBOUNCE_MS,
            max_delay_ms=PREVIEW_MAX_WAIT_MS,
            schedule=lambda ms, fn: self.after(ms, fn),
            cancel=self.after_cancel,
        )
        self._autosave_debounce = Debouncer(
            self._write_active_template,
            delay_ms=AUTOSAVE_DEBOUNCE_MS,
            max_delay_ms=AUTOSAVE_MAX_WAIT_MS,
            schedule=lambda ms, fn: self.after(ms, fn),
            cancel=self.after_cancel,
        )
        self._restore_active_template()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._register_macos_quit_handler()
        # Launched from a terminal, macOS often shows this window without
        # giving it real keyboard focus at the OS level - it's visible but
        # not the "key" window, so nothing typed reaches any field until the
        # user clicks elsewhere and back. macos_compat's lift() patch (a
        # no-op on other platforms) fixes this, but only for windows that
        # actually call lift(); TemplateBuilderWindow does this for itself
        # (see _focus_window there) and the root window needs the same.
        self.after(100, self._focus_window)

        if image_paths:
            screenshots = self.container.screenshot_service.process_local_images(image_paths)
            for shot in screenshots:
                self.state_model.add_screenshot(shot)
            self._sync_screenshot_list()

        if summary_override is not None:
            # Content already came from an LLM with far more context on the
            # actual change than a fresh AI call could infer from the diff
            # alone - apply it directly and lock it so the (otherwise
            # automatic) background AI call below never fires and can't
            # clobber it. This also avoids burning an AI-provider call/quota
            # for content we're about to throw away anyway.
            self._apply_summary(summary_override)
            self.state_model.summary_user_edited = True
        else:
            self._refresh_preview()
            self._load_initial_summary()

    # --- Reactive wiring -------------------------------------------------

    def _on_ticket_change(self, value: str):
        self.state_model.ticket_id = value
        self._refresh_preview()

    def _on_topic_change(self, value: str):
        self.state_model.topic = value
        self._refresh_preview()

    def _on_toggle_change(self, key: str, value: bool):
        # The same switches drive built-in sections and custom-template
        # sections; the key tells us which model to update.
        if self.state_model.uses_custom_template:
            self.state_model.set_template_toggle(key, value)
            # Content of a hidden section shouldn't stay editable below.
            self._refresh_content_editor()
        else:
            self.state_model.set_toggle(key, value)
        self._refresh_preview()

    def _on_author_change(self, value: str):
        self.state_model.author = value
        self._refresh_preview()

    def _on_approved_by_change(self, value: str):
        self.state_model.set_approved_by(value)
        self._refresh_preview()

    def _on_impact_areas_change(self, text: str):
        self.state_model.set_impact_areas_text(text)
        self._refresh_preview()

    def _on_key_points_change(self, points: List[str]):
        self.state_model.set_key_points(points)
        self._refresh_preview()

    def _on_test_cases_change(self, cases: List[str]):
        self.state_model.set_test_cases(cases)
        # Test case count/labels changed -> the per-screenshot assignment
        # dropdown options need to be rebuilt too.
        self._sync_screenshot_list()
        self._refresh_preview()

    def _on_token_list_change(self, token: str, values: List[str]):
        """An entry behind one of the active template's list tokens was edited.

        The token expands into bullets/table rows at render time, so writing
        the list back and refreshing is all it takes for those to update.
        """
        self.state_model.set_list_token(token, values)
        if token == "test_cases":
            self._sync_screenshot_list()
        self._refresh_preview()

    def _on_files_added(self, paths: List[str]):
        screenshots = self.container.screenshot_service.process_local_images(paths)
        for shot in screenshots:
            self.state_model.add_screenshot(shot)
        self._sync_screenshot_list()
        self._refresh_preview()

    def _on_file_removed(self, path: str):
        self.state_model.remove_screenshot(path)
        self._sync_screenshot_list()
        self._refresh_preview()

    def _on_reorder(self, new_order_paths: List[str]):
        self.state_model.reorder_screenshots(new_order_paths)
        self._refresh_preview()

    def _on_assign_test_case(self, file_path: str, index: Optional[int]):
        self.state_model.set_screenshot_test_case(file_path, index)
        self._refresh_preview()

    def _sync_screenshot_list(self):
        self.control_panel.refresh_screenshots(
            self.state_model.screenshots, self.state_model.summary.test_cases
        )

    def _refresh_preview(self):
        # Editing content can introduce or remove a token, so the shared
        # fields and list-token editors are re-evaluated here; both setters
        # no-op when unchanged (a rebuild mid-keystroke would lose focus).
        self._refresh_shared_fields()
        self.control_panel.sync_token_lists(
            self._token_list_values(self.state_model.active_template)
        )
        if self.state_model.active_template is not None and not self._builder_is_open():
            # Cheap self-heal: if the builder is gone, editing is ours again.
            self.control_panel.set_content_locked(False)
        self.preview_panel.set_title(self.state_model.title)
        template = self.state_model.active_template
        self.preview_panel.set_subtitle(
            f"Custom Template · {template.name}" if template else "Standard Document"
        )
        blocks = build_preview_content(self.state_model)
        self.preview_panel.render(blocks)

    # --- Custom document templates ---------------------------------------

    @property
    def _template_store(self):
        return self.container.template_store

    def _restore_active_template(self):
        template = self._template_store.load_active()
        if template is not None:
            self.state_model.set_active_template(template)
        self._refresh_template_list()
        self._refresh_structure_toggles()
        self._refresh_content_editor()

    def _refresh_template_list(self):
        try:
            summaries = self._template_store.list_templates()
        except OSError as e:
            print(f"[Warning] Could not list templates: {e}")
            summaries = []
        active = self.state_model.active_template
        self.control_panel.set_templates(summaries, active.template_id if active else None)

    def _refresh_structure_toggles(self):
        self.control_panel.set_structure_items(structure_toggle_items(self.state_model))
        template = self.state_model.active_template
        self.control_panel.set_structure_hint(
            f"Sections of “{template.name}”" if template else "Built-in layout"
        )

    def _refresh_shared_fields(self):
        """Show only the shared inputs the active document actually consumes.

        Created By / Approved By belong to the built-in metadata table, so a
        custom structure hides them unless it writes `{{author}}` /
        `{{approved_by}}` - in which case the value still needs typing
        somewhere.
        """
        template = self.state_model.active_template
        if template is None:
            self.control_panel.set_task_detail_visibility(author=True, approved_by=True)
            return
        tokens = template.referenced_tokens()
        self.control_panel.set_task_detail_visibility(
            author="author" in tokens,
            approved_by="approved_by" in tokens,
        )

    def _refresh_content_editor(self):
        """Point the Control Center's content editor at the active document.

        With a custom structure selected this replaces the built-in
        document's AI fields, so only the selected structure's own
        components are on screen and editable.
        """
        template = self.state_model.active_template
        if template is None:
            self.control_panel.set_document_content(None)
            return
        visible = {
            section.section_id
            for section in template.enabled_sections(self.state_model.template_toggles)
        }
        self.control_panel.set_document_content(
            template, visible, self._token_list_values(template)
        )
        self.control_panel.set_content_locked(
            self._builder_is_open(),
            "This structure is open in the Template Builder - close it to edit content here.",
        )

    def _token_list_values(self, template: Optional[DocumentTemplate]) -> dict:
        """Current entries for each list token the template references."""
        return {
            token: self.state_model.list_token_values(token)
            for token in editable_list_tokens(template)
        }

    def _activate_template(self, template: Optional[DocumentTemplate], persist: bool = True):
        # Any pending content edits belong to the outgoing template; write
        # them out before it is swapped away.
        self._flush_template_autosave()
        self.state_model.set_active_template(template)
        if persist:
            self._template_store.set_active_id(template.template_id if template else None)
        self._refresh_template_list()
        self._refresh_structure_toggles()
        self._refresh_content_editor()
        self._refresh_preview()

    # --- Live content editing -------------------------------------------

    def _on_template_content_change(self, kind: str = CHANGE_TEXT):
        """A content field in the left panel changed.

        Only *typing* is coalesced. A click (add/remove a row, pick an image)
        is a single deliberate action, so it redraws at once - waiting on a
        debounce there would just feel unresponsive.

        The file write stays coalesced either way: it is invisible to the
        user, and switching template, exporting or closing flushes it.
        """
        self._content_dirty = True
        self._autosave_debounce.trigger()

        if kind == CHANGE_ACTION:
            self._preview_debounce.cancel()   # no stale redraw behind us
            self._refresh_preview()
        else:
            self._preview_debounce.trigger()

    def _write_active_template(self):
        """Persist in-flight content edits to the active template file.

        A no-op unless content actually changed - otherwise routine flushes
        (switching templates, closing the window) would rewrite, or even
        resurrect, files nobody edited.
        """
        template = self.state_model.active_template
        if template is None or not self._content_dirty:
            return
        try:
            self._template_store.save(template)
            self._content_dirty = False
        except (TemplateError, OSError) as e:
            # Never interrupt typing with a dialog; the user can still export
            # and the next edit retries the write.
            print(f"[Warning] Could not auto-save template content: {e}")

    def _flush_template_autosave(self):
        """Write any queued content edits out right now."""
        self._autosave_debounce.cancel()
        self._write_active_template()

    def _discard_pending_content_edits(self):
        """Drop queued edits (their template is being deleted or replaced)."""
        self._autosave_debounce.cancel()
        self._content_dirty = False

    def _on_template_selected(self, template_id: Optional[str]):
        if template_id is None:
            self._activate_template(None)
            return
        try:
            template = self._template_store.load(template_id)
        except (TemplateError, OSError) as e:
            messagebox.showerror("Template Error", f"Could not open that template:\n{e}")
            self._refresh_template_list()
            return
        self._activate_template(template)

    def _on_create_template(self):
        self._open_builder(None)

    def _on_edit_template(self):
        template = self.state_model.active_template
        if template is None:
            messagebox.showinfo(
                "No Template Selected",
                "Select a saved custom template first, or create a new one.",
            )
            return
        self._open_builder(template)

    def _on_duplicate_template(self):
        template = self.state_model.active_template
        if template is None:
            return
        clone = template.duplicate()
        try:
            self._template_store.save(clone)
        except (TemplateError, OSError) as e:
            messagebox.showerror("Duplicate Failed", f"Could not duplicate this template:\n{e}")
            return
        self._activate_template(clone)

    def _on_delete_template(self):
        template = self.state_model.active_template
        if template is None:
            return
        if not messagebox.askyesno("Delete Template", f"Delete “{template.name}” permanently?"):
            return
        # Queued edits for a template being deleted must not write it back.
        self._discard_pending_content_edits()
        try:
            self._template_store.delete(template.template_id)
        except (TemplateError, OSError) as e:
            messagebox.showerror("Delete Failed", f"Could not delete this template:\n{e}")
            return
        self._activate_template(None)

    def _builder_is_open(self) -> bool:
        if self._builder_window is None:
            return False
        try:
            alive = bool(self._builder_window.winfo_exists())
        except Exception:
            alive = False
        if not alive:
            # Drop the reference as soon as we notice, so a builder that went
            # away without notifying can't keep the content editor locked.
            self._builder_window = None
        return alive

    def _open_builder(self, template: Optional[DocumentTemplate]):
        # One builder at a time: a second window editing the same template
        # would let two copies race each other on save.
        if self._builder_is_open():
            self._builder_window.focus_force()
            self._builder_window.lift()
            return

        # The builder opens a snapshot of the template, so make sure any
        # unsaved content edits are in it before it takes that snapshot.
        self._flush_template_autosave()

        self._builder_window = TemplateBuilderWindow(
            self,
            store=self._template_store,
            template=template,
            on_saved=self._on_template_saved,
            on_closed=self._on_builder_closed,
            context_provider=self.state_model.template_context,
            screenshots_provider=lambda: list(self.state_model.screenshots),
        )
        # While the builder holds this structure it is the single writer.
        self._refresh_content_editor()

    def _on_builder_closed(self):
        self._builder_window = None
        self._refresh_content_editor()

    def _on_template_saved(self, template: DocumentTemplate):
        """A save in the builder immediately becomes the previewed document."""
        self._activate_template(template)

    def _load_initial_summary(self):
        """Fill the document immediately, then improve it if AI is available.

        The Git diff is local and instant, so the panel opens with real
        content - changed file names - instead of a blank document that
        rewrites itself seconds later. When a Gemini key is configured, the
        AI call runs on top of that with the wait made visible.
        """
        git_info = self.state_model.git_info
        self._apply_summary(
            build_git_diff_summary(
                getattr(git_info, "inferred_title", "") or self.state_model.title,
                getattr(git_info, "changed_files", None) or [],
            )
        )

        if self.container.config.ai_api_key:
            self._start_ai_summary()

    def _start_ai_summary(self):
        """Ask the AI for a better summary, showing progress and a deadline."""
        git_info = self.state_model.git_info
        # Each attempt gets a token: a result from a superseded or timed-out
        # attempt must not land in the panel after we've stopped waiting for it.
        self._ai_attempt += 1
        attempt = self._ai_attempt
        self._ai_pending = True

        self._start_ai_spinner()
        deadline = deadline_for_diff(getattr(git_info, "raw_diff", "") or "")
        # Grace period on top of the request's own deadline: this only fires
        # if the HTTP layer overshoots, so the UI can never wait forever.
        self._ai_watchdog_id = self.after(
            int((deadline + AI_WATCHDOG_GRACE_SECONDS) * 1000),
            lambda: self._on_ai_deadline_passed(attempt),
        )

        def worker():
            # AIService already guarantees a usable ChangeSummary even when
            # the provider fails, but guard here too so a truly unexpected
            # error can't leave the spinner running forever.
            try:
                summary = self.container.ai_service.generate_change_summary(git_info)
            except Exception as e:
                print(f"[Warning] AI summary generation failed, using defaults: {e}")
                summary = default_change_summary(
                    getattr(git_info, "inferred_title", None),
                    getattr(git_info, "changed_files", None),
                )
            # Hand the result over a queue rather than calling into Tk from
            # this thread: Tk is not thread-safe, and after() from here raises
            # outright ("main thread is not in main loop") whenever the main
            # thread isn't sitting inside mainloop().
            self._ai_results.put((attempt, summary))

        threading.Thread(target=worker, daemon=True).start()
        self._ai_poll_id = self.after(AI_POLL_INTERVAL_MS, self._poll_ai_result)

    def _poll_ai_result(self):
        """Main-thread side of the handover: pick up a finished summary."""
        self._ai_poll_id = None
        if self._closing:
            return
        try:
            attempt, summary = self._ai_results.get_nowait()
        except queue.Empty:
            if self._ai_pending:
                self._ai_poll_id = self.after(AI_POLL_INTERVAL_MS, self._poll_ai_result)
            return
        self._on_ai_summary_ready(attempt, summary)

    def _on_ai_summary_ready(self, attempt: int, summary):
        if attempt != self._ai_attempt or not self._ai_pending:
            return  # a late answer we already gave up on
        self._settle_ai_request()

        if summary.source == SUMMARY_SOURCE_AI:
            if self.state_model.summary_user_edited:
                # Their typing wins, but silently dropping a summary they
                # watched being generated would look like a bug.
                self._set_ai_status(
                    "AI summary discarded - your edits kept", theme.TEXT_MUTED,
                    action_label="Use AI text", action=lambda: self._replace_with_ai(summary),
                )
                return
            self._apply_summary(summary)
            self._set_ai_status("AI summary applied", theme.TEXT_MUTED,
                                kind=AI_STATUS_APPLIED)
            self.after(AI_STATUS_CLEAR_MS, self._clear_ai_status_if_idle)
            return

        # The adapter fell back, so the request failed or ran out of time -
        # the Git-diff content already on screen stands.
        self._show_ai_unavailable("AI unavailable - showing changed files")

    def _on_ai_deadline_passed(self, attempt: int):
        if attempt != self._ai_attempt or not self._ai_pending:
            return
        self._settle_ai_request()
        self._show_ai_unavailable("AI timed out - showing changed files")

    def _show_ai_unavailable(self, message: str):
        self._set_ai_status(
            message, theme.STATUS_WARNING,
            action_label="Retry AI", action=self._start_ai_summary,
        )

    def _replace_with_ai(self, summary):
        """Take the AI text after all, at the user's explicit request."""
        self.state_model.summary_user_edited = False
        self._apply_summary(summary)
        self.state_model.summary_user_edited = True
        self._set_ai_status()

    def _settle_ai_request(self):
        self._ai_pending = False
        self._stop_ai_spinner()
        if self._ai_watchdog_id is not None:
            try:
                self.after_cancel(self._ai_watchdog_id)
            except Exception:
                pass
            self._ai_watchdog_id = None

    # --- AI progress indicator --------------------------------------------

    def _start_ai_spinner(self):
        self._ai_spinner_frame = 0
        self._tick_ai_spinner()

    def _tick_ai_spinner(self):
        if not self._ai_pending or self._closing:
            return
        # Trailing dots rather than a glyph spinner: every font ships them,
        # including the fallback fonts on bare Linux VMs.
        dots = "." * (1 + self._ai_spinner_frame % 3)
        self._set_ai_status(f"Writing AI summary{dots}", theme.ACCENT_TECH_BLUE)
        self._ai_spinner_frame += 1
        self._ai_spinner_id = self.after(AI_SPINNER_INTERVAL_MS, self._tick_ai_spinner)

    def _stop_ai_spinner(self):
        if self._ai_spinner_id is not None:
            try:
                self.after_cancel(self._ai_spinner_id)
            except Exception:
                pass
            self._ai_spinner_id = None

    def _set_ai_status(self, text: str = "", color: str = None, action_label: str = "",
                       action=None, kind: str = ""):
        self._ai_status_text = text
        # Tracked as state rather than sniffed back out of the label text:
        # the wording (and any icon in it) is presentation, and matching on it
        # would break the moment either changed.
        self._ai_status_kind = kind
        try:
            self.preview_panel.set_status(text, color, action_label, action)
        except Exception:
            # A status chip is never worth taking the window down for.
            pass

    def _clear_ai_status_if_idle(self):
        # Only clear the message this timer was started for; a retry or a new
        # state may have replaced it in the meantime.
        if not self._ai_pending and self._ai_status_kind == AI_STATUS_APPLIED:
            self._set_ai_status()

    def _apply_summary(self, summary):
        # The user may have already started editing the summary by hand
        # before the (possibly network-bound) AI generation finished -
        # don't clobber their edits.
        if self.state_model.summary_user_edited:
            return
        self.state_model.summary = summary
        self.control_panel.set_impact_areas_text(", ".join(summary.impact_areas))
        self.control_panel.set_key_points(summary.key_points)
        self.control_panel.set_test_cases(summary.test_cases)
        # The same lists feed any {{token}} editors a custom structure shows.
        self.control_panel.set_token_list_values(
            self._token_list_values(self.state_model.active_template)
        )
        self._sync_screenshot_list()
        self._refresh_preview()

    # --- Export ------------------------------------------------------------

    def _on_export(self):
        default_dir = self.container.config.default_output_dir or "."
        os.makedirs(default_dir, exist_ok=True)
        default_name = f"{self.state_model.title}.docx"

        output_path = filedialog.asksaveasfilename(
            title="Export Documentation",
            initialdir=default_dir,
            initialfile=default_name,
            defaultextension=".docx",
            filetypes=[("Word Document", "*.docx")],
            # parent= keeps the save sheet attached to this window on macOS,
            # where an unparented dialog can open behind the app.
            parent=self,
        )
        if not output_path:
            return

        try:
            if self.state_model.active_template is not None:
                result_path = self.container.template_docx_renderer.render(
                    template=self.state_model.active_template,
                    context=self.state_model.template_context(),
                    output_path=output_path,
                    screenshots=list(self.state_model.screenshots),
                    section_overrides=dict(self.state_model.template_toggles),
                )
            else:
                result_path = self.container.document_service.generate_documentation(
                    output_path=output_path,
                    title_override=self.state_model.title,
                    author=self.state_model.author,
                    approved_by=self.state_model.approved_by,
                    ticket_override=self.state_model.ticket_id or None,
                    output_format="docx",
                    sections=dict(self.state_model.toggles),
                    summary_override=self.state_model.summary,
                    screenshots_override=list(self.state_model.screenshots),
                )
            messagebox.showinfo("Export Successful", f"Documentation generated:\n{result_path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Failed to generate documentation:\n{e}")

    # --- Shutdown ----------------------------------------------------------

    def _register_macos_quit_handler(self):
        """Route macOS's ⌘Q through our own close path.

        Tk on Aqua handles ⌘Q with its default `tk::mac::Quit`, which exits
        without ever firing WM_DELETE_WINDOW - so the debounced content
        edits would never be flushed and the last thing typed would be lost.
        Overriding that command is the documented way to hook it.
        """
        if sys.platform != "darwin":
            return
        try:
            self.createcommand("tk::mac::Quit", self._on_close)
        except Exception as e:
            # Not fatal: the window's own close box still flushes properly.
            print(f"[Warning] Could not install the macOS Quit handler: {e}")

    def _on_close(self):
        """Flush debounced content edits so closing never loses the last word."""
        self._closing = True
        try:
            self._flush_template_autosave()
        finally:
            self.destroy()

    def _cancel_pending_jobs(self):
        for debouncer in (
            getattr(self, "_preview_debounce", None),
            getattr(self, "_autosave_debounce", None),
        ):
            if debouncer is not None:
                debouncer.cancel()

        # The AI spinner and its watchdog are plain after() timers, and would
        # fire into a destroyed window just as noisily.
        self._ai_pending = False
        for timer_attr in ("_ai_spinner_id", "_ai_watchdog_id", "_ai_poll_id"):
            timer_id = getattr(self, timer_attr, None)
            if timer_id is not None:
                try:
                    self.after_cancel(timer_id)
                except Exception:
                    pass
                setattr(self, timer_attr, None)

    def destroy(self):
        # A debounced callback that fires after the interpreter is gone raises
        # "invalid command name" from Tk's background error handler, so drop
        # anything still queued - including on a programmatic destroy().
        self._closing = True
        self._cancel_pending_jobs()
        super().destroy()

    def _focus_window(self) -> None:
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def run(self):
        self.mainloop()
