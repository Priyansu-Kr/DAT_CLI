"""Left panel: the Control Center for input and configuration."""
import tkinter as tk
from typing import Callable, List, Optional

import customtkinter as ctk

from dat.gui import theme
from dat.gui.state import TOGGLE_LABELS, TOGGLE_ORDER
from dat.gui.widgets.dropzone import DropZone
from dat.gui.widgets.editable_list import EditableListField
from dat.models.screenshot_info import ScreenshotInfo


class ControlPanel(ctk.CTkScrollableFrame):
    def __init__(
        self,
        master,
        on_ticket_change: Callable[[str], None],
        on_topic_change: Callable[[str], None],
        on_author_change: Callable[[str], None],
        on_approved_by_change: Callable[[str], None],
        on_toggle_change: Callable[[str, bool], None],
        on_impact_areas_change: Callable[[str], None],
        on_key_points_change: Callable[[List[str]], None],
        on_test_cases_change: Callable[[List[str]], None],
        on_files_added: Callable[[List[str]], None],
        on_file_removed: Callable[[str], None],
        on_reorder: Callable[[List[str]], None],
        on_assign_test_case: Callable[[str, Optional[int]], None],
        **kwargs,
    ):
        super().__init__(
            master,
            width=theme.LEFT_PANEL_WIDTH,
            fg_color=theme.SURFACE_GREY,
            corner_radius=0,
            **kwargs,
        )
        self.on_ticket_change = on_ticket_change
        self.on_topic_change = on_topic_change
        self.on_author_change = on_author_change
        self.on_approved_by_change = on_approved_by_change
        self.on_toggle_change = on_toggle_change
        self.on_impact_areas_change = on_impact_areas_change

        self._build_header()
        self._build_ticket_field()
        self._build_topic_field()
        self._build_task_detail_fields()
        self._build_toggles()
        self._build_ai_content(on_key_points_change, on_test_cases_change)
        self._build_dropzone(on_files_added, on_file_removed, on_reorder, on_assign_test_case)

    def _section_label(self, text: str, icon: str = "") -> ctk.CTkLabel:
        display = f"{icon}  {text}" if icon else text
        return ctk.CTkLabel(
            self, text=display, anchor="w", text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
        )

    def _build_header(self):
        title = ctk.CTkLabel(
            self, text="Control Center", anchor="w", text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_HEADING, "bold"),
        )
        title.pack(fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_MD, theme.PADDING_SM))

    def _build_ticket_field(self):
        self._section_label("Ticket ID", icon="🎫").pack(
            fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_SM, 4)
        )
        self.ticket_var = tk.StringVar()
        self.ticket_var.trace_add("write", lambda *_: self.on_ticket_change(self.ticket_var.get()))
        self.ticket_entry = ctk.CTkEntry(
            self, textvariable=self.ticket_var, placeholder_text="e.g. JIRA-1042",
            fg_color=theme.SURFACE_GREY_LIGHT, border_color=theme.BORDER_MUTED,
            text_color=theme.TEXT_PRIMARY, corner_radius=theme.CORNER_RADIUS,
        )
        self.ticket_entry.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))

    def _build_topic_field(self):
        self._section_label("Feature Topic", icon="📝").pack(
            fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_SM, 4)
        )
        self.topic_text = ctk.CTkTextbox(
            self, height=70, fg_color=theme.SURFACE_GREY_LIGHT,
            border_color=theme.BORDER_MUTED, border_width=1,
            text_color=theme.TEXT_PRIMARY, corner_radius=theme.CORNER_RADIUS,
            wrap="word",
        )
        self.topic_text.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))
        self.topic_text.bind("<KeyRelease>", self._on_topic_key_release)

    def _on_topic_key_release(self, _event=None):
        self.on_topic_change(self.topic_text.get("1.0", "end-1c"))

    def _build_task_detail_fields(self):
        self._section_label("Created By", icon="🖊").pack(
            fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_SM, 4)
        )
        self.author_var = tk.StringVar()
        self.author_var.trace_add("write", lambda *_: self.on_author_change(self.author_var.get()))
        self.author_entry = ctk.CTkEntry(
            self, textvariable=self.author_var, placeholder_text="e.g. Jane Doe",
            fg_color=theme.SURFACE_GREY_LIGHT, border_color=theme.BORDER_MUTED,
            text_color=theme.TEXT_PRIMARY, corner_radius=theme.CORNER_RADIUS,
        )
        self.author_entry.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))

        self._section_label("Approved By", icon="✅").pack(
            fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_SM, 4)
        )
        self.approved_by_var = tk.StringVar()
        self.approved_by_var.trace_add("write", lambda *_: self.on_approved_by_change(self.approved_by_var.get()))
        self.approved_by_entry = ctk.CTkEntry(
            self, textvariable=self.approved_by_var, placeholder_text="e.g. Reviewer Name",
            fg_color=theme.SURFACE_GREY_LIGHT, border_color=theme.BORDER_MUTED,
            text_color=theme.TEXT_PRIMARY, corner_radius=theme.CORNER_RADIUS,
        )
        self.approved_by_entry.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))

    def _build_toggles(self):
        self._section_label("Document Structure").pack(
            fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_MD, 4)
        )
        self.toggle_vars = {}
        for key in TOGGLE_ORDER:
            var = tk.BooleanVar(value=True)
            self.toggle_vars[key] = var
            switch = ctk.CTkSwitch(
                self,
                text=TOGGLE_LABELS[key],
                variable=var,
                onvalue=True,
                offvalue=False,
                progress_color=theme.ACCENT_TECH_BLUE,
                text_color=theme.TEXT_PRIMARY,
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
                command=lambda k=key: self.on_toggle_change(k, self.toggle_vars[k].get()),
            )
            switch.pack(fill="x", padx=theme.PADDING_MD, pady=6)

    def _build_ai_content(self, on_key_points_change, on_test_cases_change):
        self._section_label("AI Generated Content", icon="✨").pack(
            fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_MD, 4)
        )

        ctk.CTkLabel(
            self, text="Affected Module(s)", anchor="w", text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
        ).pack(fill="x", padx=theme.PADDING_MD, pady=(0, 2))
        self.impact_areas_entry = ctk.CTkEntry(
            self, placeholder_text="e.g. Checkout, Payments",
            fg_color=theme.SURFACE_GREY_LIGHT, border_color=theme.BORDER_MUTED,
            text_color=theme.TEXT_PRIMARY, corner_radius=theme.CORNER_RADIUS,
        )
        self.impact_areas_entry.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))
        self.impact_areas_entry.bind("<KeyRelease>", self._on_impact_areas_key_release)

        ctk.CTkLabel(
            self, text="Key Points", anchor="w", text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
        ).pack(fill="x", padx=theme.PADDING_MD, pady=(0, 2))
        self.key_points_field = EditableListField(
            self, on_change=on_key_points_change, add_label="+ Add Key Point",
            row_placeholder="Key point",
        )
        self.key_points_field.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))

        ctk.CTkLabel(
            self, text="Test Cases", anchor="w", text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
        ).pack(fill="x", padx=theme.PADDING_MD, pady=(0, 2))
        self.test_cases_field = EditableListField(
            self, on_change=on_test_cases_change, add_label="+ Add Test Case",
            row_placeholder="Test case",
        )
        self.test_cases_field.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_MD))

    def _on_impact_areas_key_release(self, _event=None):
        self.on_impact_areas_change(self.impact_areas_entry.get())

    def _build_dropzone(self, on_files_added, on_file_removed, on_reorder, on_assign_test_case):
        self._section_label("Assets & Evidence", icon="🖼").pack(
            fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_MD, 4)
        )
        self.dropzone = DropZone(
            self,
            on_files_added=on_files_added,
            on_file_removed=on_file_removed,
            on_reorder=on_reorder,
            on_assign_test_case=on_assign_test_case,
        )
        self.dropzone.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_MD))

    # --- Programmatic setters (do not trigger on_change callbacks) --------

    def set_ticket_id(self, value: str):
        self.ticket_var.set(value)

    def set_topic(self, value: str):
        self.topic_text.delete("1.0", "end")
        self.topic_text.insert("1.0", value)

    def set_toggle(self, key: str, value: bool):
        self.toggle_vars[key].set(value)

    def set_author(self, value: str):
        self.author_var.set(value)

    def set_approved_by(self, value: str):
        self.approved_by_var.set(value)

    def set_impact_areas_text(self, value: str):
        self.impact_areas_entry.delete(0, "end")
        self.impact_areas_entry.insert(0, value)

    def set_key_points(self, values: List[str]):
        self.key_points_field.set_values(values)

    def set_test_cases(self, values: List[str]):
        self.test_cases_field.set_values(values)

    def refresh_screenshots(self, screenshots: List[ScreenshotInfo], test_case_labels: List[str]):
        self.dropzone.refresh(screenshots, test_case_labels)
