"""Control Center editor for the *content* of the active custom template.

The template builder defines the document's structure; this widget fills that
structure in. It lists every visible section of the active template and, per
block, renders exactly the fields the model declares as editable
(``template_model.content_fields``) - so selecting a structure immediately
shows that structure's own components instead of the previous document's
fields.

Edits mutate the live template and report upward through ``on_change``; the
app is responsible for refreshing the preview and persisting.
"""
import tkinter as tk
from typing import Callable, List, Optional, Set

import customtkinter as ctk

from dat.gui import theme
from dat.gui.widgets.editable_list import EditableListField
from dat.models.template_model import (
    FIELD_LINE,
    FIELD_LIST,
    FIELD_MULTILINE,
    FIELD_NOTE,
    FIELD_PATH,
    FIELD_TABLE,
    MAX_TABLE_ROWS,
    ContentField,
    DocumentTemplate,
    TemplateBlock,
    TemplateSection,
    block_label,
    content_fields,
    get_content,
    has_editable_content,
    set_content,
)

IMAGE_FILETYPES = [("Image files", "*.png *.jpg *.jpeg *.bmp *.webp *.gif"), ("All files", "*.*")]

# How a change was made, which decides how fast it is reflected.
# A keystroke is one of many in a burst, so those are coalesced; a click is a
# single deliberate action and must show up at once.
CHANGE_TEXT = "text"
CHANGE_ACTION = "action"


class TemplateContentEditor(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_change: Callable[[str], None],
        on_edit_structure: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        # Called with CHANGE_TEXT or CHANGE_ACTION so the owner can decide
        # whether to coalesce the refresh or run it straight away.
        self._on_change = on_change
        self._on_edit_structure = on_edit_structure
        self._template: Optional[DocumentTemplate] = None
        self._visible_section_ids: Optional[Set[str]] = None
        self._locked = False
        self._lock_reason = ""

        self._body = ctk.CTkFrame(self, fg_color="transparent")
        self._body.pack(fill="x")

    # --- Public API ------------------------------------------------------

    def set_template(
        self,
        template: Optional[DocumentTemplate],
        visible_section_ids: Optional[Set[str]] = None,
    ) -> None:
        self._template = template
        self._visible_section_ids = visible_section_ids
        self._rebuild()

    def set_locked(self, locked: bool, reason: str = "") -> None:
        """Disable editing (used while the builder owns the same template).

        Two writers on one template would silently lose whichever set of
        edits was saved first, so the Control Center yields to the builder.
        """
        if self._locked == locked and self._lock_reason == reason:
            return
        self._locked = locked
        self._lock_reason = reason
        self._rebuild()

    # --- Rendering -------------------------------------------------------

    def _rebuild(self) -> None:
        for child in self._body.winfo_children():
            child.destroy()

        if self._template is None:
            return

        if self._locked:
            self._note(self._lock_reason or "Editing is locked.")
            return

        sections = [s for s in self._template.sections if self._is_visible(s)]
        if not sections:
            self._note(
                "No visible sections. Enable one above, or add sections in the builder."
            )
            self._structure_button()
            return

        rendered_any = False
        for section in sections:
            editable = [b for b in section.blocks if has_editable_content(b)]
            self._section_header(section, len(section.blocks))
            if not editable:
                self._note("This section has no editable content.", indent=True)
                continue
            rendered_any = True
            for block in editable:
                self._block_card(block)

        if not rendered_any:
            self._note("Add components to this structure to fill in content.")
        self._structure_button()

    def _is_visible(self, section: TemplateSection) -> bool:
        if self._visible_section_ids is None:
            return section.enabled
        return section.section_id in self._visible_section_ids

    def _section_header(self, section: TemplateSection, block_count: int) -> None:
        row = ctk.CTkFrame(self._body, fg_color="transparent")
        row.pack(fill="x", pady=(theme.PADDING_SM, 2))
        ctk.CTkLabel(
            row, text=(section.title or "Untitled Section").upper(), anchor="w",
            text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3, "bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            row, text=f"{block_count} block{'s' if block_count != 1 else ''}", anchor="e",
            text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3),
        ).pack(side="right")

    def _block_card(self, block: TemplateBlock) -> None:
        card = ctk.CTkFrame(self._body, fg_color=theme.SURFACE_GREY_LIGHT, corner_radius=8)
        card.pack(fill="x", pady=3)

        ctk.CTkLabel(
            card, text=block_label(block.kind), anchor="w", text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3, "bold"),
        ).pack(fill="x", padx=8, pady=(6, 0))

        for field in content_fields(block):
            self._field_widget(card, block, field)

        tk.Frame(card, height=2, bg=theme.SURFACE_GREY_LIGHT, bd=0).pack()

    def _field_widget(self, parent, block: TemplateBlock, field: ContentField) -> None:
        if field.kind == FIELD_NOTE:
            ctk.CTkLabel(
                parent, text=field.placeholder, anchor="w", justify="left",
                wraplength=theme.LEFT_PANEL_WIDTH - 90, text_color=theme.TEXT_MUTED,
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3),
            ).pack(fill="x", padx=8, pady=(2, 6))
            return

        if field.kind == FIELD_LINE:
            entry = self._entry(parent, str(get_content(block, field.key)), field.placeholder)
            entry.pack(fill="x", padx=8, pady=(4, 6))
            entry.bind(
                "<KeyRelease>",
                lambda _e=None, b=block, k=field.key, w=entry: self._commit(b, k, w.get()),
            )
            return

        if field.kind == FIELD_MULTILINE:
            self._caption(parent, field.label)
            box = ctk.CTkTextbox(
                parent, height=68, fg_color=theme.SURFACE_GREY, border_color=theme.BORDER_MUTED,
                border_width=1, text_color=theme.TEXT_PRIMARY, wrap="word",
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
            )
            value = str(get_content(block, field.key))
            if value:
                box.insert("1.0", value)
            box.pack(fill="x", padx=8, pady=(0, 6))
            box.bind(
                "<KeyRelease>",
                lambda _e=None, b=block, k=field.key, w=box: self._commit(b, k, w.get("1.0", "end-1c")),
            )
            return

        if field.kind == FIELD_LIST:
            self._caption(parent, field.label)
            list_field = EditableListField(
                parent,
                on_change=lambda values, b=block, k=field.key: self._commit(b, k, list(values)),
                add_label="+ Add Item",
                row_placeholder=field.placeholder,
            )
            list_field.pack(fill="x", padx=8, pady=(0, 6))
            list_field.set_values(list(get_content(block, field.key) or []))
            return

        if field.kind == FIELD_PATH:
            self._caption(parent, field.label)
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=(0, 6))
            entry = self._entry(row, str(get_content(block, field.key)), field.placeholder)
            entry.pack(side="left", fill="x", expand=True)
            entry.bind(
                "<KeyRelease>",
                lambda _e=None, b=block, k=field.key, w=entry: self._commit(b, k, w.get()),
            )
            ctk.CTkButton(
                row, text="…", width=30, height=26,
                fg_color=theme.ACCENT_TECH_BLUE, hover_color=theme.ACCENT_TECH_BLUE_HOVER,
                command=lambda b=block, k=field.key: self._browse(b, k),
            ).pack(side="left", padx=(4, 0))
            return

        if field.kind == FIELD_TABLE:
            self._table_widget(parent, block, field.label)

    def _table_widget(self, parent, block: TemplateBlock, label: str) -> None:
        """One card per row, so a row is added/removed as easily as a test case.

        Rows stack vertically (rather than as a grid) because the panel is
        narrow: full-width fields stay readable at any column count, and a
        table with eight columns is just as editable as one with two.
        """
        self._caption(parent, f"{label} · {block.row_count} × {block.col_count} columns")

        if block.include_headers:
            self._column_headers(parent, block)

        for index in range(block.row_count):
            self._table_row(parent, block, index)

        footer = ctk.CTkFrame(parent, fg_color="transparent")
        footer.pack(fill="x", padx=8, pady=(2, 8))

        at_cap = block.row_count >= MAX_TABLE_ROWS
        ctk.CTkButton(
            footer, text="+ Add Row", height=26,
            fg_color=theme.SURFACE_GREY, hover_color=theme.ACCENT_TECH_BLUE,
            text_color=theme.TEXT_PRIMARY, state="disabled" if at_cap else "normal",
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
            command=lambda b=block: self._add_row(b),
        ).pack(fill="x")
        if at_cap:
            self._note(f"Row limit reached ({MAX_TABLE_ROWS}).", master=footer, indent=True)

    def _column_headers(self, parent, block: TemplateBlock) -> None:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="x", padx=8, pady=(0, 4))
        for col in range(block.col_count):
            entry = self._entry(
                wrap, block.table_headers[col] if col < len(block.table_headers) else "",
                f"Column {col + 1} heading", bold=True,
            )
            entry.pack(fill="x", pady=1)
            entry.bind(
                "<KeyRelease>",
                lambda _e=None, b=block, c=col, w=entry: self._commit_header(b, c, w.get()),
            )

    def _table_row(self, parent, block: TemplateBlock, index: int) -> None:
        card = ctk.CTkFrame(parent, fg_color=theme.SURFACE_GREY, corner_radius=6)
        card.pack(fill="x", padx=8, pady=2)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=6, pady=(4, 0))
        ctk.CTkLabel(
            head, text=f"ROW {index + 1}", anchor="w", text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3, "bold"),
        ).pack(side="left")
        ctk.CTkButton(
            head, text="✕", width=22, height=20, fg_color="transparent",
            hover_color=theme.STATUS_ERROR, text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 2),
            command=lambda b=block, i=index: self._remove_row(b, i),
        ).pack(side="right")

        row = block.table_rows[index]
        for col in range(block.col_count):
            header = block.table_headers[col] if col < len(block.table_headers) else ""
            entry = self._entry(
                card, row[col] if col < len(row) else "",
                (header.strip() or f"Column {col + 1}"),
            )
            entry.pack(fill="x", padx=6, pady=(2, 4 if col == block.col_count - 1 else 2))
            entry.bind(
                "<KeyRelease>",
                lambda _e=None, b=block, r=index, c=col, w=entry: self._commit_cell(b, r, c, w.get()),
            )

    # --- Small helpers ---------------------------------------------------

    def _entry(self, parent, value: str, placeholder: str = "", bold: bool = False) -> ctk.CTkEntry:
        entry = ctk.CTkEntry(
            parent, height=26, fg_color=theme.SURFACE_GREY, border_color=theme.BORDER_MUTED,
            text_color=theme.TEXT_PRIMARY, placeholder_text=placeholder,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1,
                  "bold" if bold else "normal"),
        )
        if value:
            entry.insert(0, value)
        return entry

    def _caption(self, parent, text: str) -> None:
        ctk.CTkLabel(
            parent, text=text, anchor="w", text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3),
        ).pack(fill="x", padx=8, pady=(4, 2))

    def _note(self, text: str, master=None, indent: bool = False) -> None:
        ctk.CTkLabel(
            master or self._body, text=text, anchor="w", justify="left",
            wraplength=theme.LEFT_PANEL_WIDTH - 70, text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 2),
        ).pack(fill="x", padx=(16 if indent else 2, 2), pady=4)

    def _structure_button(self) -> None:
        if self._on_edit_structure is None:
            return
        ctk.CTkButton(
            self._body, text="✎  Edit Structure in Builder", height=28,
            fg_color=theme.SURFACE_GREY_LIGHT, hover_color=theme.ACCENT_TECH_BLUE,
            text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
            command=self._on_edit_structure,
        ).pack(fill="x", pady=(6, 2))

    # --- Mutations -------------------------------------------------------

    def _notify(self, kind: str) -> None:
        self._on_change(kind)

    # Typed edits: one of a burst, so the owner coalesces them.

    def _commit(self, block: TemplateBlock, key: str, value) -> None:
        set_content(block, key, value)
        self._notify(CHANGE_TEXT)

    def _commit_header(self, block: TemplateBlock, col: int, value: str) -> None:
        block.set_header(col, value)
        self._notify(CHANGE_TEXT)

    def _commit_cell(self, block: TemplateBlock, row: int, col: int, value: str) -> None:
        block.set_cell(row, col, value)
        self._notify(CHANGE_TEXT)

    # Clicked actions: single, deliberate, and reflected immediately.

    def _add_row(self, block: TemplateBlock) -> None:
        if not block.add_row():
            return
        self._rebuild()
        self._notify(CHANGE_ACTION)

    def _remove_row(self, block: TemplateBlock, index: int) -> None:
        if not block.remove_row(index):
            return
        self._rebuild()
        self._notify(CHANGE_ACTION)

    def _browse(self, block: TemplateBlock, key: str) -> None:
        # parent= keeps the sheet attached to our window on macOS, where an
        # unparented dialog can open behind the app.
        path = ctk.filedialog.askopenfilename(
            title="Select Image", filetypes=IMAGE_FILETYPES, parent=self.winfo_toplevel()
        )
        if not path:
            return
        set_content(block, key, path)
        self._rebuild()
        self._notify(CHANGE_ACTION)

