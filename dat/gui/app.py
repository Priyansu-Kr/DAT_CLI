"""DATGuiApp: the DAT Control Center main window.

Built on CustomTkinter (Tk) - CPU/software rasterized, no GPU required, so
it runs unmodified inside headless VMs and remote desktops.
"""
import os
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
from dat.gui.panels.control_panel import ControlPanel
from dat.gui.panels.preview_panel import PreviewPanel
from dat.gui.state import GuiState, build_preview_content
from dat.models.git_info import GitInfo
from dat.services.ai_service import default_change_summary
from dat.utils.container import Container


def _patch_scrollable_frame_string_widget_bug() -> None:
    """Some Linux/VM Tk builds deliver `event.widget` as the widget's string
    path name instead of the resolved widget object during mouse-wheel
    events. CTkScrollableFrame._check_if_valid_scroll always expects an
    object and crashes with `AttributeError: 'str' object has no attribute
    'master'`. Resolve the string via nametowidget() before delegating to
    the original logic.
    """
    original = ctk.CTkScrollableFrame._check_if_valid_scroll
    if getattr(original, "_dat_string_widget_patched", False):
        return

    def _check_if_valid_scroll(self, widget):
        if isinstance(widget, str):
            try:
                widget = self.nametowidget(widget)
            except KeyError:
                return False
        return original(self, widget)

    _check_if_valid_scroll._dat_string_widget_patched = True
    ctk.CTkScrollableFrame._check_if_valid_scroll = _check_if_valid_scroll


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
        )
        self.control_panel.grid(row=0, column=0, sticky="nsw")

        self.preview_panel = PreviewPanel(self, on_export=self._on_export)
        self.preview_panel.grid(row=0, column=1, sticky="nsew")

        self.control_panel.set_ticket_id(self.state_model.ticket_id)
        self.control_panel.set_topic(self.state_model.topic)
        self.control_panel.set_author(self.state_model.author)
        self.control_panel.set_approved_by(self.state_model.approved_by)

        if image_paths:
            screenshots = self.container.screenshot_service.process_local_images(image_paths)
            for shot in screenshots:
                self.state_model.add_screenshot(shot)
            self._sync_screenshot_list()

        self._refresh_preview()
        self._load_summary_async()

    # --- Reactive wiring -------------------------------------------------

    def _on_ticket_change(self, value: str):
        self.state_model.ticket_id = value
        self._refresh_preview()

    def _on_topic_change(self, value: str):
        self.state_model.topic = value
        self._refresh_preview()

    def _on_toggle_change(self, key: str, value: bool):
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
        self.preview_panel.set_title(self.state_model.title)
        blocks = build_preview_content(self.state_model)
        self.preview_panel.render(blocks)

    def _load_summary_async(self):
        git_info = self.state_model.git_info

        def worker():
            # AIService already guarantees a usable default ChangeSummary
            # even when the AI provider fails, but guard here too so the
            # left panel never ends up permanently blank.
            try:
                summary = self.container.ai_service.generate_change_summary(git_info)
            except Exception as e:
                print(f"[Warning] AI summary generation failed, using defaults: {e}")
                summary = default_change_summary(getattr(git_info, "inferred_title", None))
            self.after(0, lambda: self._apply_summary(summary))

        threading.Thread(target=worker, daemon=True).start()

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
        )
        if not output_path:
            return

        try:
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

    def run(self):
        self.mainloop()
