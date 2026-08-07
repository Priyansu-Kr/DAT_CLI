"""Left panel: the Control Center for input and configuration."""
import tkinter as tk
from typing import Callable, Dict, List, Optional, Set, Tuple

import customtkinter as ctk

from dat.gui import theme
from dat.gui.state import TOGGLE_LABELS, TOGGLE_ORDER
from dat.gui.widgets.dropzone import DropZone
from dat.gui.widgets.editable_list import EditableListField
from dat.gui.widgets.template_content_editor import CHANGE_TEXT, TemplateContentEditor
from dat.models.screenshot_info import ScreenshotInfo
from dat.models.template_model import DocumentTemplate
from dat.services.template_store import TemplateSummary

STANDARD_TEMPLATE_LABEL = "Standard Document (built-in)"


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
        on_create_template: Optional[Callable[[], None]] = None,
        on_edit_template: Optional[Callable[[], None]] = None,
        on_duplicate_template: Optional[Callable[[], None]] = None,
        on_delete_template: Optional[Callable[[], None]] = None,
        on_template_selected: Optional[Callable[[Optional[str]], None]] = None,
        on_template_content_change: Optional[Callable[[], None]] = None,
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
        self.on_create_template = on_create_template
        self.on_edit_template = on_edit_template
        self.on_duplicate_template = on_duplicate_template
        self.on_delete_template = on_delete_template
        self.on_template_selected = on_template_selected
        self.on_template_content_change = on_template_content_change

        # label -> template_id (None for the built-in standard document)
        self._template_options: Dict[str, Optional[str]] = {STANDARD_TEMPLATE_LABEL: None}
        self._suppress_template_callback = False

        self._build_header()
        self._build_ticket_field()
        self._build_topic_field()
        self._build_task_detail_fields()
        self._build_custom_doc_section()
        self._build_toggles()
        self._build_content_section(on_key_points_change, on_test_cases_change)
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
        """Created By / Approved By.

        These feed the built-in layout's metadata table, so a custom
        structure only shows them when it actually writes `{{author}}` /
        `{{approved_by}}`. Each lives in its own frame so it can be hidden
        without disturbing the order of the panel.
        """
        self.task_detail_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.task_detail_frame.pack(fill="x")

        self.author_field = ctk.CTkFrame(self.task_detail_frame, fg_color="transparent")
        ctk.CTkLabel(
            self.author_field, text="🖊  Created By", anchor="w", text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
        ).pack(fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_SM, 4))
        self.author_var = tk.StringVar()
        self.author_var.trace_add("write", lambda *_: self.on_author_change(self.author_var.get()))
        self.author_entry = ctk.CTkEntry(
            self.author_field, textvariable=self.author_var, placeholder_text="e.g. Jane Doe",
            fg_color=theme.SURFACE_GREY_LIGHT, border_color=theme.BORDER_MUTED,
            text_color=theme.TEXT_PRIMARY, corner_radius=theme.CORNER_RADIUS,
        )
        self.author_entry.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))

        self.approved_by_field = ctk.CTkFrame(self.task_detail_frame, fg_color="transparent")
        ctk.CTkLabel(
            self.approved_by_field, text="✅  Approved By", anchor="w",
            text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
        ).pack(fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_SM, 4))
        self.approved_by_var = tk.StringVar()
        self.approved_by_var.trace_add("write", lambda *_: self.on_approved_by_change(self.approved_by_var.get()))
        self.approved_by_entry = ctk.CTkEntry(
            self.approved_by_field, textvariable=self.approved_by_var,
            placeholder_text="e.g. Reviewer Name",
            fg_color=theme.SURFACE_GREY_LIGHT, border_color=theme.BORDER_MUTED,
            text_color=theme.TEXT_PRIMARY, corner_radius=theme.CORNER_RADIUS,
        )
        self.approved_by_entry.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))

        self._author_visible = True
        self._approved_by_visible = True
        self._task_detail_packed = True
        self._repack_task_detail_fields()

    def _repack_task_detail_fields(self):
        # Re-pack both in canonical order: pack_forget() + pack() alone would
        # append the re-shown field after its sibling.
        self.author_field.pack_forget()
        self.approved_by_field.pack_forget()
        if self._author_visible:
            self.author_field.pack(fill="x")
        if self._approved_by_visible:
            self.approved_by_field.pack(fill="x")

        # An empty CTkFrame still claims its default height, which would
        # leave a gap where the fields used to be - so drop the container
        # too, and restore it in place (before the next section) later.
        should_show = self._author_visible or self._approved_by_visible
        if should_show and not self._task_detail_packed:
            anchor = getattr(self, "_custom_doc_anchor", None)
            if anchor is not None and anchor.winfo_exists():
                self.task_detail_frame.pack(fill="x", before=anchor)
            else:
                self.task_detail_frame.pack(fill="x")
        elif not should_show and self._task_detail_packed:
            self.task_detail_frame.pack_forget()
        self._task_detail_packed = should_show

    def set_task_detail_visibility(self, author: bool, approved_by: bool) -> None:
        """Show/hide Created By and Approved By."""
        if (author, approved_by) == (self._author_visible, self._approved_by_visible):
            return
        self._author_visible = bool(author)
        self._approved_by_visible = bool(approved_by)
        self._repack_task_detail_fields()

    def _build_custom_doc_section(self):
        """Entry point to the template builder + saved-template picker."""
        # Kept as the anchor the task-detail block re-packs itself before.
        self._custom_doc_anchor = self._section_label("Custom Document", icon="🧩")
        self._custom_doc_anchor.pack(
            fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_MD, 4)
        )

        ctk.CTkButton(
            self, text="＋  Create Your Custom Doc", height=36,
            fg_color=theme.ACCENT_TECH_BLUE, hover_color=theme.ACCENT_TECH_BLUE_HOVER,
            text_color=theme.TEXT_PRIMARY, corner_radius=theme.CORNER_RADIUS,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
            command=lambda: self.on_create_template and self.on_create_template(),
        ).pack(fill="x", padx=theme.PADDING_MD, pady=(0, 8))

        self.template_menu = ctk.CTkOptionMenu(
            self, values=[STANDARD_TEMPLATE_LABEL], height=30,
            fg_color=theme.SURFACE_GREY_LIGHT, button_color=theme.BORDER_MUTED,
            button_hover_color=theme.SURFACE_CARD_HOVER, text_color=theme.TEXT_PRIMARY,
            dynamic_resizing=False,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
            command=self._on_template_menu_change,
        )
        self.template_menu.set(STANDARD_TEMPLATE_LABEL)
        self.template_menu.pack(fill="x", padx=theme.PADDING_MD, pady=(0, 6))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))
        for index in range(3):
            actions.grid_columnconfigure(index, weight=1, uniform="tmplactions")

        self.edit_template_btn = self._small_action_button(
            actions, "Edit", lambda: self.on_edit_template and self.on_edit_template()
        )
        self.edit_template_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.duplicate_template_btn = self._small_action_button(
            actions, "Duplicate", lambda: self.on_duplicate_template and self.on_duplicate_template()
        )
        self.duplicate_template_btn.grid(row=0, column=1, sticky="ew", padx=4)

        self.delete_template_btn = self._small_action_button(
            actions, "Delete",
            lambda: self.on_delete_template and self.on_delete_template(),
            hover_color=theme.STATUS_ERROR,
        )
        self.delete_template_btn.grid(row=0, column=2, sticky="ew", padx=(4, 0))

        self._set_template_actions_enabled(False)

    def _small_action_button(
        self, parent, text: str, command: Callable[[], None], hover_color: Optional[str] = None
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=text, height=26, fg_color=theme.SURFACE_GREY_LIGHT,
            hover_color=hover_color or theme.ACCENT_TECH_BLUE, text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 2),
            command=command,
        )

    def _set_template_actions_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (self.edit_template_btn, self.duplicate_template_btn, self.delete_template_btn):
            button.configure(state=state)

    def _on_template_menu_change(self, label: str) -> None:
        if self._suppress_template_callback or self.on_template_selected is None:
            return
        self.on_template_selected(self._template_options.get(label))

    def _build_toggles(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_MD, 4))
        ctk.CTkLabel(
            header, text="Document Structure", anchor="w", text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
        ).pack(fill="x")
        self.structure_hint = ctk.CTkLabel(
            header, text="Built-in layout", anchor="w", text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3),
        )
        self.structure_hint.pack(fill="x")

        self.toggles_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.toggles_frame.pack(fill="x")

        self.toggle_vars: Dict[str, tk.BooleanVar] = {}
        self.set_structure_items(
            [(key, TOGGLE_LABELS[key], True) for key in TOGGLE_ORDER]
        )

    def set_structure_items(self, items: List[Tuple[str, str, bool]]) -> None:
        """Rebuild the show/hide switches.

        Called with the built-in sections normally, or with one entry per
        section of the active custom template - the hide/show behaviour is
        identical in both modes.
        """
        for child in self.toggles_frame.winfo_children():
            child.destroy()
        self.toggle_vars = {}

        if not items:
            ctk.CTkLabel(
                self.toggles_frame, text="This template has no sections yet.",
                anchor="w", text_color=theme.TEXT_MUTED,
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
            ).pack(fill="x", padx=theme.PADDING_MD, pady=6)
            return

        for key, label, value in items:
            var = tk.BooleanVar(value=value)
            self.toggle_vars[key] = var
            ctk.CTkSwitch(
                self.toggles_frame,
                text=label,
                variable=var,
                onvalue=True,
                offvalue=False,
                progress_color=theme.ACCENT_TECH_BLUE,
                text_color=theme.TEXT_PRIMARY,
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
                command=lambda k=key: self.on_toggle_change(k, self.toggle_vars[k].get()),
            ).pack(fill="x", padx=theme.PADDING_MD, pady=6)

    def _build_content_section(self, on_key_points_change, on_test_cases_change):
        """Content input for whichever document is active.

        Both editors live in one slot and only one is ever packed, so the
        standard document's AI fields can never sit under a custom
        structure's sections (and vice versa) - and the panel's layout order
        stays stable when they swap.
        """
        self.content_slot = ctk.CTkFrame(self, fg_color="transparent")
        self.content_slot.pack(fill="x")

        self.ai_content_frame = ctk.CTkFrame(self.content_slot, fg_color="transparent")
        self._build_ai_content(self.ai_content_frame, on_key_points_change, on_test_cases_change)

        self.template_content_frame = ctk.CTkFrame(self.content_slot, fg_color="transparent")
        ctk.CTkLabel(
            self.template_content_frame, text="📄  Document Content", anchor="w",
            text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
        ).pack(fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_MD, 0))
        self.template_content_hint = ctk.CTkLabel(
            self.template_content_frame, text="", anchor="w", text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3),
        )
        self.template_content_hint.pack(fill="x", padx=theme.PADDING_MD, pady=(0, 4))

        self.template_content_editor = TemplateContentEditor(
            self.template_content_frame,
            on_change=self._on_content_change,
            on_edit_structure=lambda: self.on_edit_template and self.on_edit_template(),
        )
        self.template_content_editor.pack(
            fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_MD)
        )

        self._show_ai_content()

    def _build_ai_content(self, parent, on_key_points_change, on_test_cases_change):
        ctk.CTkLabel(
            parent, text="✨  AI Generated Content", anchor="w", text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
        ).pack(fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_MD, 4))

        ctk.CTkLabel(
            parent, text="Affected Module(s)", anchor="w", text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
        ).pack(fill="x", padx=theme.PADDING_MD, pady=(0, 2))
        self.impact_areas_entry = ctk.CTkEntry(
            parent, placeholder_text="e.g. Checkout, Payments",
            fg_color=theme.SURFACE_GREY_LIGHT, border_color=theme.BORDER_MUTED,
            text_color=theme.TEXT_PRIMARY, corner_radius=theme.CORNER_RADIUS,
        )
        self.impact_areas_entry.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))
        self.impact_areas_entry.bind("<KeyRelease>", self._on_impact_areas_key_release)

        ctk.CTkLabel(
            parent, text="Key Points", anchor="w", text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
        ).pack(fill="x", padx=theme.PADDING_MD, pady=(0, 2))
        self.key_points_field = EditableListField(
            parent, on_change=on_key_points_change, add_label="+ Add Key Point",
            row_placeholder="Key point",
        )
        self.key_points_field.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))

        ctk.CTkLabel(
            parent, text="Test Cases", anchor="w", text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
        ).pack(fill="x", padx=theme.PADDING_MD, pady=(0, 2))
        self.test_cases_field = EditableListField(
            parent, on_change=on_test_cases_change, add_label="+ Add Test Case",
            row_placeholder="Test case",
        )
        self.test_cases_field.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_MD))

    def _on_impact_areas_key_release(self, _event=None):
        self.on_impact_areas_change(self.impact_areas_entry.get())

    def _show_ai_content(self):
        self.template_content_frame.pack_forget()
        self.ai_content_frame.pack(fill="x")

    def _show_template_content(self):
        self.ai_content_frame.pack_forget()
        self.template_content_frame.pack(fill="x")

    def set_document_content(
        self,
        template: Optional["DocumentTemplate"] = None,
        visible_section_ids: Optional[Set[str]] = None,
    ) -> None:
        """Point the content editor at the active document.

        ``template=None`` restores the built-in document's AI fields.
        """
        if template is None:
            self.template_content_editor.set_template(None)
            self._show_ai_content()
            return

        self.template_content_hint.configure(
            text=f"Fill in the sections of “{template.name}”"
        )
        self.template_content_editor.set_template(template, visible_section_ids)
        self._show_template_content()

    def set_content_locked(self, locked: bool, reason: str = "") -> None:
        self.template_content_editor.set_locked(locked, reason)

    def _on_content_change(self, kind: str = CHANGE_TEXT) -> None:
        if self.on_template_content_change is not None:
            self.on_template_content_change(kind)

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
        if key in self.toggle_vars:
            self.toggle_vars[key].set(value)

    def set_structure_hint(self, text: str):
        self.structure_hint.configure(text=text)

    def set_templates(self, summaries: List[TemplateSummary], active_id: Optional[str]) -> None:
        """Refresh the saved-template picker without firing on_template_selected."""
        options: Dict[str, Optional[str]] = {STANDARD_TEMPLATE_LABEL: None}
        used_labels = {STANDARD_TEMPLATE_LABEL}
        for summary in summaries:
            label = summary.name.strip() or "Untitled Template"
            if label in used_labels:
                # Same-named templates are legal; keep the picker unambiguous.
                label = f"{label} · {summary.template_id[:6]}"
            used_labels.add(label)
            options[label] = summary.template_id
        self._template_options = options

        active_label = next(
            (label for label, tid in options.items() if tid == active_id and active_id is not None),
            STANDARD_TEMPLATE_LABEL,
        )

        self._suppress_template_callback = True
        try:
            self.template_menu.configure(values=list(options.keys()))
            self.template_menu.set(active_label)
        finally:
            self._suppress_template_callback = False

        self._set_template_actions_enabled(active_id is not None)

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
