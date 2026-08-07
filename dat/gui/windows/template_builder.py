"""Template Builder: the "Create your custom doc" authoring screen.

Layout (mirrors the product design):

    ┌─ header: back | name + status | Editor/Preview | Save ─────────┐
    │ ┌ sidebar ──────────┐ ┌ canvas ─────────────────────────────┐ │
    │ │ search            │ │  Editor:  section cards with        │ │
    │ │ Components|Layers │ │           inline block editors      │ │
    │ │ palette / outline │ │  Preview: DocumentCanvas (identical │ │
    │ └───────────────────┘ │           to the main live preview) │ │
    └───────────────────────┴─────────────────────────────────────┴─┘

The window edits an isolated *copy* of the template, so closing without
saving can never mutate what the main window is currently rendering.
"""
import os
import platform
from datetime import datetime
from tkinter import filedialog, messagebox
from typing import Callable, List, Optional

import customtkinter as ctk

from dat.gui import theme
from dat.gui.state import build_template_blocks
from dat.gui.text_fit import truncate_to_length
from dat.gui.widgets.document_canvas import DocumentCanvas
from dat.gui.widgets.editable_list import EditableListField
from dat.models.screenshot_info import ScreenshotInfo
from dat.models.template_model import (
    BLOCK_BULLET_LIST,
    BLOCK_CODE,
    BLOCK_HEADING,
    BLOCK_IMAGE,
    BLOCK_PARAGRAPH,
    BLOCK_SCREENSHOTS,
    BLOCK_SEPARATOR,
    BLOCK_SUBHEADING,
    BLOCK_TABLE,
    BLOCK_TWO_COLUMNS,
    BLOCK_SPEC_BY_KIND,
    MAX_COL_WEIGHT,
    MAX_TABLE_COLS,
    MIN_COL_WEIGHT,
    MIN_TABLE_COLS,
    PALETTE_GROUPS,
    SUPPORTED_TOKENS,
    DocumentTemplate,
    TemplateBlock,
    TemplateContext,
    TemplateError,
    TemplateSection,
    block_label,
    block_specs_for_group,
)
from dat.services.template_store import TemplateStore

MODE_EDITOR = "Editor"
MODE_PREVIEW = "Preview"

IMAGE_FILETYPES = [("Image files", "*.png *.jpg *.jpeg *.bmp *.webp *.gif"), ("All files", "*.*")]

_IS_MACOS = platform.system() == "Darwin"
SAVE_SEQUENCES = ["<Control-s>"] + (["<Command-s>"] if _IS_MACOS else [])
CLOSE_SEQUENCES = ["<Command-w>"] if _IS_MACOS else []

# Sidebar text budget: the scrollable frame is narrower than the sidebar
# itself (padding + scrollbar), so labels wrap/truncate against this.
SIDEBAR_TEXT_WRAP = 132


def _relative_time(iso_value: str) -> str:
    """'2M AGO'-style stamp for the header, mirroring the design."""
    try:
        moment = datetime.fromisoformat(iso_value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    seconds = max(0, int((datetime.now() - moment).total_seconds()))
    if seconds < 45:
        return "JUST NOW"
    if seconds < 3600:
        return f"{seconds // 60}M AGO"
    if seconds < 86400:
        return f"{seconds // 3600}H AGO"
    return f"{seconds // 86400}D AGO"


class TemplateBuilderWindow(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        store: TemplateStore,
        template: Optional[DocumentTemplate] = None,
        on_saved: Optional[Callable[[DocumentTemplate], None]] = None,
        on_closed: Optional[Callable[[], None]] = None,
        context_provider: Optional[Callable[[], TemplateContext]] = None,
        screenshots_provider: Optional[Callable[[], List[ScreenshotInfo]]] = None,
    ):
        super().__init__(master)
        self.store = store
        self.on_saved = on_saved
        self.on_closed = on_closed
        self._context_provider = context_provider or (lambda: TemplateContext())
        self._screenshots_provider = screenshots_provider or (lambda: [])

        # Work on a copy: the main window keeps rendering its own instance
        # until the user actually saves.
        source = template or DocumentTemplate.starter()
        self.template = source.copy()
        self._is_new = template is None
        self._dirty = self._is_new
        self._mode = MODE_EDITOR
        self._search_term = ""
        self._sidebar_tab = "Components"
        self._selected_section_id: Optional[str] = (
            self.template.sections[0].section_id if self.template.sections else None
        )
        self._selected_block_id: Optional[str] = None
        self._closed_notified = False

        self.title(f"DAT · {self.template.name}")
        self.geometry("1180x820")
        self.minsize(940, 620)
        self.configure(fg_color=theme.BG_DEEP_DARK)

        self._build_header()
        self._build_body()
        self._rebuild_sidebar()
        self._rebuild_editor()
        self._refresh_status()

        self.protocol("WM_DELETE_WINDOW", self.request_close)
        self.bind("<Escape>", lambda _e: self.request_close())
        # Ctrl+S everywhere, plus the Command equivalents macOS users expect.
        for sequence in SAVE_SEQUENCES:
            self.bind(sequence, lambda _e: self._on_save())
        for sequence in CLOSE_SEQUENCES:
            self.bind(sequence, lambda _e: self.request_close())

        # transient() keeps the builder above its parent without a grab, so
        # the main window stays usable (e.g. to add screenshots) while the
        # structure is being authored.
        try:
            self.transient(master)
        except Exception:
            pass
        self.after(100, self._focus_window)

    def _focus_window(self) -> None:
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    # --- Header ----------------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=theme.BG_HEADER, corner_radius=0, height=56)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left", fill="y", padx=(12, 0))

        ctk.CTkButton(
            left, text="←", width=32, height=32, fg_color="transparent",
            hover_color=theme.SURFACE_CARD_HOVER, text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, 18), command=self.request_close,
        ).pack(side="left", pady=12)

        ctk.CTkLabel(
            left, text="▤", width=28, text_color=theme.ACCENT_TECH_BLUE,
            font=(theme.FONT_INTERFACE_FAMILY, 16),
        ).pack(side="left", padx=(6, 4))

        titles = ctk.CTkFrame(left, fg_color="transparent")
        titles.pack(side="left", pady=8)

        self.name_var = ctk.StringVar(value=self.template.name)
        self.name_entry = ctk.CTkEntry(
            titles, textvariable=self.name_var, width=300, height=24,
            fg_color="transparent", border_width=0, text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_HEADING - 1, "bold"),
            placeholder_text="Template name",
        )
        self.name_entry.pack(anchor="w")
        self.name_entry.bind("<KeyRelease>", self._on_name_change)

        self.status_label = ctk.CTkLabel(
            titles, text="", anchor="w", text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3),
        )
        self.status_label.pack(anchor="w", padx=(8, 0))

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right", fill="y", padx=(0, 16))

        self.save_btn = ctk.CTkButton(
            right, text="Save Template", width=130, height=32,
            fg_color=theme.ACCENT_TECH_BLUE, hover_color=theme.ACCENT_TECH_BLUE_HOVER,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
            command=self._on_save,
        )
        self.save_btn.pack(side="right", pady=12)

        self.mode_switch = ctk.CTkSegmentedButton(
            header, values=[MODE_EDITOR, MODE_PREVIEW], width=200, height=30,
            selected_color=theme.ACCENT_TECH_BLUE,
            selected_hover_color=theme.ACCENT_TECH_BLUE_HOVER,
            unselected_color=theme.SURFACE_CARD,
            unselected_hover_color=theme.SURFACE_CARD_HOVER,
            fg_color=theme.SURFACE_CARD,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
            command=self._on_mode_change,
        )
        self.mode_switch.set(MODE_EDITOR)
        self.mode_switch.pack(pady=12)

    def _on_name_change(self, _event=None) -> None:
        self.template.name = self.name_var.get()
        self.title(f"DAT · {self.template.name or 'Untitled Template'}")
        self._mark_dirty()

    def _refresh_status(self) -> None:
        kind = "NEW TEMPLATE" if self._is_new else "CUSTOM TEMPLATE"
        if self._dirty:
            text = f"{kind} • UNSAVED CHANGES"
            color = theme.STATUS_WARNING
        else:
            text = f"{kind} • LAST SAVED {_relative_time(self.template.updated_at)}"
            color = theme.TEXT_MUTED
        blocks = self.template.block_count
        sections = len(self.template.sections)
        text += f" • {sections} SECTION{'S' if sections != 1 else ''} · {blocks} BLOCK{'S' if blocks != 1 else ''}"
        self.status_label.configure(text=text, text_color=color)

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._refresh_status()

    # --- Body ------------------------------------------------------------

    def _build_body(self) -> None:
        body = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._build_sidebar(body)

        self.canvas_area = ctk.CTkFrame(body, fg_color=theme.BG_DEEP_DARK, corner_radius=0)
        self.canvas_area.grid(row=0, column=1, sticky="nsew")

        self.editor_container = ctk.CTkFrame(self.canvas_area, fg_color="transparent")
        self.editor_scroll = ctk.CTkScrollableFrame(self.editor_container, fg_color="transparent")
        self.editor_scroll.pack(fill="both", expand=True, padx=theme.PADDING_SM, pady=theme.PADDING_SM)

        self.preview_container = ctk.CTkFrame(self.canvas_area, fg_color="transparent")
        self.preview_canvas = DocumentCanvas(
            self.preview_container,
            empty_message="Nothing to preview - add a block or enable a section.",
        )
        self.preview_canvas.pack(fill="both", expand=True, padx=theme.PADDING_MD, pady=theme.PADDING_MD)

        self.editor_container.pack(fill="both", expand=True)

    def _build_sidebar(self, parent) -> None:
        sidebar = ctk.CTkFrame(
            parent, fg_color=theme.SURFACE_GREY, corner_radius=0, width=theme.BUILDER_SIDEBAR_WIDTH
        )
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        # No textvariable here: CustomTkinter suppresses placeholder_text when
        # an entry is bound to one, and the placeholder is the only label this
        # search field gets.
        self.search_entry = ctk.CTkEntry(
            sidebar, height=32,
            placeholder_text="🔍  Search components...",
            fg_color=theme.SURFACE_GREY_LIGHT, border_color=theme.BORDER_MUTED,
            text_color=theme.TEXT_PRIMARY, corner_radius=theme.CORNER_RADIUS,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
        )
        self.search_entry.pack(fill="x", padx=theme.PADDING_SM, pady=(theme.PADDING_SM, 8))
        self.search_entry.bind("<KeyRelease>", self._on_search)

        self.tab_switch = ctk.CTkSegmentedButton(
            sidebar, values=["Components", "Layers"], height=28,
            selected_color=theme.ACCENT_TECH_BLUE,
            selected_hover_color=theme.ACCENT_TECH_BLUE_HOVER,
            unselected_color=theme.SURFACE_GREY_LIGHT,
            unselected_hover_color=theme.SURFACE_CARD_HOVER,
            fg_color=theme.SURFACE_GREY_LIGHT,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
            command=self._on_sidebar_tab,
        )
        self.tab_switch.set(self._sidebar_tab)
        self.tab_switch.pack(fill="x", padx=theme.PADDING_SM, pady=(0, 8))

        self.sidebar_scroll = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        self.sidebar_scroll.pack(fill="both", expand=True, padx=(6, 2), pady=(0, theme.PADDING_SM))

    def _on_search(self, _event=None) -> None:
        self._search_term = self.search_entry.get().strip().lower()
        self._rebuild_sidebar()

    def _on_sidebar_tab(self, value: str) -> None:
        self._sidebar_tab = value
        # Keep the control in sync when switched programmatically.
        if self.tab_switch.get() != value:
            self.tab_switch.set(value)
        self._rebuild_sidebar()

    def _on_mode_change(self, value: str) -> None:
        self._mode = value
        if self.mode_switch.get() != value:
            self.mode_switch.set(value)
        if value == MODE_PREVIEW:
            self.editor_container.pack_forget()
            self.preview_container.pack(fill="both", expand=True)
            self._refresh_preview()
        else:
            self.preview_container.pack_forget()
            self.editor_container.pack(fill="both", expand=True)

    def _refresh_preview(self) -> None:
        blocks = build_template_blocks(
            self.template,
            self._context_provider(),
            screenshots=self._screenshots_provider(),
        )
        self.preview_canvas.render(blocks)
        self.preview_canvas.scroll_to_top()

    # --- Sidebar content -------------------------------------------------

    def _rebuild_sidebar(self) -> None:
        for child in self.sidebar_scroll.winfo_children():
            child.destroy()
        if self._sidebar_tab == "Layers":
            self._build_layers()
        else:
            self._build_palette()

    def _sidebar_group_label(self, text: str) -> None:
        ctk.CTkLabel(
            self.sidebar_scroll, text=text, anchor="w", text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3, "bold"),
        ).pack(fill="x", padx=6, pady=(theme.PADDING_SM, 6))

    def _build_palette(self) -> None:
        matched_any = False
        for group in PALETTE_GROUPS:
            specs = [s for s in block_specs_for_group(group) if self._matches_search(s)]
            if not specs:
                continue
            matched_any = True
            self._sidebar_group_label(group)
            for spec in specs:
                self._build_palette_card(spec)

        if not matched_any:
            ctk.CTkLabel(
                self.sidebar_scroll, text="No components match your search.",
                text_color=theme.TEXT_MUTED, wraplength=SIDEBAR_TEXT_WRAP + 40,
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
            ).pack(fill="x", padx=6, pady=theme.PADDING_MD)
            return

        ctk.CTkLabel(
            self.sidebar_scroll,
            text="TOKENS\n" + ", ".join(f"{{{{{t}}}}}" for t in SUPPORTED_TOKENS),
            anchor="w", justify="left", text_color=theme.TEXT_MUTED, wraplength=SIDEBAR_TEXT_WRAP + 40,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3),
        ).pack(fill="x", padx=6, pady=(theme.PADDING_MD, theme.PADDING_SM))

    def _matches_search(self, spec) -> bool:
        if not self._search_term:
            return True
        return self._search_term in spec.label.lower() or self._search_term in spec.description.lower()

    def _build_palette_card(self, spec) -> None:
        card = ctk.CTkFrame(self.sidebar_scroll, fg_color=theme.SURFACE_CARD, corner_radius=8)
        card.pack(fill="x", padx=6, pady=4)

        icon = ctk.CTkLabel(
            card, text=spec.icon, width=26, height=26, corner_radius=6,
            fg_color=theme.SURFACE_GREY_LIGHT, text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
        )
        icon.grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=10)

        title = ctk.CTkLabel(
            card, text=spec.label, anchor="w", text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
        )
        title.grid(row=0, column=1, sticky="w", pady=(10, 0))

        desc = ctk.CTkLabel(
            card, text=spec.description, anchor="w", text_color=theme.TEXT_MUTED,
            wraplength=SIDEBAR_TEXT_WRAP, justify="left",
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3),
        )
        desc.grid(row=1, column=1, sticky="w", pady=(0, 10))
        card.grid_columnconfigure(1, weight=1)

        for widget in (card, icon, title, desc):
            widget.bind("<Button-1>", lambda _e=None, kind=spec.kind: self._add_block(kind))
            widget.bind("<Enter>", lambda _e=None, c=card: c.configure(fg_color=theme.SURFACE_CARD_HOVER))
            widget.bind("<Leave>", lambda _e=None, c=card: c.configure(fg_color=theme.SURFACE_CARD))
            try:
                widget.configure(cursor="hand2")
            except Exception:
                pass  # cursor names vary by platform/Tk build

    def _build_layers(self) -> None:
        if not self.template.sections:
            ctk.CTkLabel(
                self.sidebar_scroll, text="No sections yet.\nAdd one from the canvas.",
                text_color=theme.TEXT_MUTED, justify="left",
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
            ).pack(fill="x", padx=6, pady=theme.PADDING_MD)
            return

        self._sidebar_group_label("DOCUMENT OUTLINE")
        for section in self.template.sections:
            selected = section.section_id == self._selected_section_id
            row = ctk.CTkFrame(
                self.sidebar_scroll,
                fg_color=theme.SURFACE_CARD_HOVER if selected else theme.SURFACE_CARD,
                corner_radius=6,
            )
            row.pack(fill="x", padx=6, pady=(6, 2))

            # Packed before the (expanding) title so the toggle always keeps
            # its slot, however long the section name is.
            ctk.CTkButton(
                row, text="👁" if section.enabled else "🚫", width=26, height=22,
                fg_color="transparent", hover_color=theme.SURFACE_GREY_LIGHT,
                text_color=theme.TEXT_SECONDARY,
                command=lambda sid=section.section_id: self._toggle_section_visibility(sid),
            ).pack(side="right", padx=(2, 6))

            label = ctk.CTkLabel(
                row, text=f"▤  {truncate_to_length(section.title or 'Untitled Section', 18)}", anchor="w",
                text_color=theme.TEXT_PRIMARY if section.enabled else theme.TEXT_MUTED,
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
            )
            label.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=6)
            for widget in (row, label):
                widget.bind("<Button-1>", lambda _e=None, sid=section.section_id: self._select_section(sid))

            for block in section.blocks:
                block_row = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent")
                block_row.pack(fill="x", padx=(22, 6))
                text = self._block_summary(block)
                block_label_widget = ctk.CTkLabel(
                    block_row, text=text, anchor="w",
                    text_color=theme.ACCENT_TECH_BLUE if block.block_id == self._selected_block_id
                    else theme.TEXT_SECONDARY,
                    font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 2),
                )
                block_label_widget.pack(side="left", fill="x", expand=True, pady=2)
                for widget in (block_row, block_label_widget):
                    widget.bind(
                        "<Button-1>",
                        lambda _e=None, sid=section.section_id, bid=block.block_id: self._select_block(sid, bid),
                    )

    def _block_summary(self, block: TemplateBlock) -> str:
        spec = BLOCK_SPEC_BY_KIND.get(block.kind)
        icon = spec.icon if spec else "•"
        detail = ""
        if block.kind in (BLOCK_HEADING, BLOCK_SUBHEADING, BLOCK_PARAGRAPH):
            detail = (block.text or "").strip().splitlines()[0][:26] if block.text.strip() else ""
        elif block.kind == BLOCK_TABLE:
            detail = f"{block.row_count}×{block.col_count}"
        elif block.kind == BLOCK_BULLET_LIST:
            detail = f"{len(block.items)} items"
        elif block.kind == BLOCK_IMAGE and block.image_path:
            detail = os.path.basename(block.image_path)[:24]
        label = block_label(block.kind)
        return f"{icon}  {label}" + (f" · {detail}" if detail else "")

    # --- Editor canvas ---------------------------------------------------

    def _rebuild_editor(self, preserve_scroll: bool = True) -> None:
        offset = 0.0
        if preserve_scroll:
            try:
                offset = self.editor_scroll._parent_canvas.yview()[0]
            except Exception:
                offset = 0.0

        for child in self.editor_scroll.winfo_children():
            child.destroy()

        holder = ctk.CTkFrame(self.editor_scroll, fg_color="transparent")
        holder.pack(fill="both", expand=True)
        page = ctk.CTkFrame(holder, fg_color="transparent")
        page.pack(fill="both", expand=True, padx=theme.PADDING_SM)

        self._build_editor_toolbar(page)

        if not self.template.sections:
            ctk.CTkLabel(
                page,
                text="Your document is empty.\n\nAdd a section, then click components on the left to build it.",
                text_color=theme.TEXT_MUTED, justify="center",
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_BODY),
            ).pack(fill="x", pady=60)
        else:
            for index, section in enumerate(self.template.sections):
                self._build_section_card(page, section, index)

        ctk.CTkButton(
            page, text="＋  Add Section", height=36, corner_radius=8,
            fg_color=theme.SURFACE_CARD, hover_color=theme.SURFACE_CARD_HOVER,
            border_width=1, border_color=theme.BORDER_MUTED, text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
            command=self._add_section,
        ).pack(fill="x", pady=(theme.PADDING_SM, theme.PADDING_LG))

        self._rebuild_sidebar()
        if preserve_scroll and offset:
            self.after_idle(lambda: self._restore_scroll(offset))

    def _restore_scroll(self, offset: float) -> None:
        try:
            self.editor_scroll._parent_canvas.yview_moveto(offset)
        except Exception:
            pass

    def _build_editor_toolbar(self, parent) -> None:
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", pady=(theme.PADDING_SM, theme.PADDING_SM))

        ctk.CTkLabel(
            bar, text="DOCUMENT STRUCTURE", anchor="w", text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3, "bold"),
        ).pack(side="left")

        ctk.CTkLabel(
            bar,
            text="Click a component on the left to append it to the selected section",
            anchor="e", text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3),
        ).pack(side="right")

    def _build_section_card(self, parent, section: TemplateSection, index: int) -> None:
        selected = section.section_id == self._selected_section_id
        card = ctk.CTkFrame(
            parent, fg_color=theme.SURFACE_CARD, corner_radius=10,
            border_width=1,
            border_color=theme.ACCENT_TECH_BLUE if selected else theme.BORDER_MUTED,
        )
        card.pack(fill="x", pady=6)
        card.bind("<Button-1>", lambda _e=None, sid=section.section_id: self._select_section(sid))

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 4))

        handle = ctk.CTkLabel(
            head, text="⋮⋮", width=16, text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
        )
        handle.pack(side="left")
        handle.bind("<Button-1>", lambda _e=None, sid=section.section_id: self._select_section(sid))

        title_var = ctk.StringVar(value=section.title)
        title_entry = ctk.CTkEntry(
            head, textvariable=title_var, height=28, fg_color=theme.SURFACE_GREY_LIGHT,
            border_color=theme.BORDER_MUTED, text_color=theme.TEXT_PRIMARY,
            placeholder_text="Section title",
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_BODY, "bold"),
        )
        title_entry.pack(side="left", fill="x", expand=True, padx=8)
        title_entry.bind(
            "<KeyRelease>",
            lambda _e=None, s=section, v=title_var: self._set_section_title(s, v.get()),
        )
        title_entry.bind("<FocusIn>", lambda _e=None, sid=section.section_id: self._select_section(sid, rebuild=False))

        # side="right" packs right-to-left, so build the row in reverse to
        # read ▲ ▼ ✕ from left to right.
        self._icon_button(head, "✕", lambda: self._delete_section(section.section_id), danger=True)
        self._icon_button(head, "▼", lambda: self._move_section(section.section_id, 1),
                          enabled=index < len(self.template.sections) - 1)
        self._icon_button(head, "▲", lambda: self._move_section(section.section_id, -1),
                          enabled=index > 0)

        options = ctk.CTkFrame(card, fg_color="transparent")
        options.pack(fill="x", padx=12, pady=(0, 6))

        visible_var = ctk.BooleanVar(value=section.enabled)
        ctk.CTkSwitch(
            options, text="Visible", variable=visible_var, width=40, switch_width=32, switch_height=16,
            progress_color=theme.ACCENT_TECH_BLUE, text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 2),
            command=lambda s=section, v=visible_var: self._set_section_enabled(s, v.get()),
        ).pack(side="left")

        show_title_var = ctk.BooleanVar(value=section.show_title)
        ctk.CTkSwitch(
            options, text="Print title as heading", variable=show_title_var, width=40,
            switch_width=32, switch_height=16,
            progress_color=theme.ACCENT_TECH_BLUE, text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 2),
            command=lambda s=section, v=show_title_var: self._set_section_show_title(s, v.get()),
        ).pack(side="left", padx=(14, 0))

        ctk.CTkLabel(
            options, text=f"{len(section.blocks)} block{'s' if len(section.blocks) != 1 else ''}",
            text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3),
        ).pack(side="right")

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=12, pady=(0, 12))

        if not section.blocks:
            empty = ctk.CTkLabel(
                body, text="No blocks yet - pick a component from the left panel.",
                text_color=theme.TEXT_MUTED,
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
            )
            empty.pack(fill="x", pady=10)
            empty.bind("<Button-1>", lambda _e=None, sid=section.section_id: self._select_section(sid))
            return

        for block_index, block in enumerate(section.blocks):
            self._build_block_card(body, section, block, block_index)

    def _build_block_card(self, parent, section: TemplateSection, block: TemplateBlock, index: int) -> None:
        selected = block.block_id == self._selected_block_id
        card = ctk.CTkFrame(
            parent, fg_color=theme.SURFACE_GREY_LIGHT, corner_radius=8,
            border_width=1,
            border_color=theme.ACCENT_TECH_BLUE if selected else theme.SURFACE_GREY_LIGHT,
        )
        card.pack(fill="x", pady=4)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(8, 2))

        spec = BLOCK_SPEC_BY_KIND.get(block.kind)
        label = ctk.CTkLabel(
            head, text=f"{spec.icon if spec else '•'}  {block_label(block.kind).upper()}",
            anchor="w", text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3, "bold"),
        )
        label.pack(side="left")

        def select(_event, sid=section.section_id, bid=block.block_id):
            self._select_block(sid, bid)

        for widget in (card, head, label):
            widget.bind("<Button-1>", select)

        self._icon_button(head, "✕", lambda: self._delete_block(section, block.block_id), danger=True)
        self._icon_button(head, "⧉", lambda: self._duplicate_block(section, block.block_id))
        self._icon_button(head, "▼", lambda: self._move_block(section, block.block_id, 1),
                          enabled=index < len(section.blocks) - 1)
        self._icon_button(head, "▲", lambda: self._move_block(section, block.block_id, -1),
                          enabled=index > 0)

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=10, pady=(0, 10))
        self._build_block_fields(body, section, block)

    # --- Per-kind inline editors -----------------------------------------

    def _build_block_fields(self, parent, section: TemplateSection, block: TemplateBlock) -> None:
        kind = block.kind

        if kind in (BLOCK_HEADING, BLOCK_SUBHEADING):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x")
            entry = self._text_entry(row, block.text, placeholder="Heading text")
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<KeyRelease>", lambda _e=None, b=block, w=entry: self._set_block_field(b, "text", w.get()))

            level_menu = ctk.CTkOptionMenu(
                row, values=["H1", "H2", "H3"], width=68, height=28,
                fg_color=theme.SURFACE_GREY, button_color=theme.ACCENT_TECH_BLUE,
                button_hover_color=theme.ACCENT_TECH_BLUE_HOVER,
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
                command=lambda choice, b=block: self._set_block_field(b, "level", int(choice[1])),
            )
            level_menu.set(f"H{max(1, min(3, block.level))}")
            level_menu.pack(side="left", padx=(8, 0))

        elif kind == BLOCK_PARAGRAPH:
            textbox = self._textbox(parent, block.text, height=76)
            textbox.pack(fill="x")
            textbox.bind(
                "<KeyRelease>",
                lambda _e=None, b=block, w=textbox: self._set_block_field(b, "text", w.get("1.0", "end-1c")),
            )

        elif kind == BLOCK_BULLET_LIST:
            ordered_var = ctk.BooleanVar(value=block.ordered)
            ctk.CTkSwitch(
                parent, text="Numbered list", variable=ordered_var, width=40,
                switch_width=32, switch_height=16,
                progress_color=theme.ACCENT_TECH_BLUE, text_color=theme.TEXT_SECONDARY,
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 2),
                command=lambda b=block, v=ordered_var: self._set_block_field(b, "ordered", v.get()),
            ).pack(anchor="w", pady=(0, 6))

            field = EditableListField(
                parent,
                on_change=lambda values, b=block: self._set_block_field(b, "items", list(values)),
                add_label="+ Add List Item",
                row_placeholder="List item",
            )
            field.pack(fill="x")
            field.set_values(block.items)

        elif kind == BLOCK_TABLE:
            self._build_table_fields(parent, block)

        elif kind == BLOCK_IMAGE:
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x")
            path_entry = self._text_entry(row, block.image_path, placeholder="Image file path")
            path_entry.pack(side="left", fill="x", expand=True)
            path_entry.bind(
                "<KeyRelease>",
                lambda _e=None, b=block, w=path_entry: self._set_block_field(b, "image_path", w.get()),
            )
            ctk.CTkButton(
                row, text="Browse", width=76, height=28,
                fg_color=theme.ACCENT_TECH_BLUE, hover_color=theme.ACCENT_TECH_BLUE_HOVER,
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
                command=lambda b=block: self._browse_image(b),
            ).pack(side="left", padx=(8, 0))

            caption = self._text_entry(parent, block.caption, placeholder="Caption (optional)")
            caption.pack(fill="x", pady=(6, 0))
            caption.bind(
                "<KeyRelease>",
                lambda _e=None, b=block, w=caption: self._set_block_field(b, "caption", w.get()),
            )

        elif kind == BLOCK_SCREENSHOTS:
            heading = self._text_entry(parent, block.text, placeholder="Screenshots heading")
            heading.pack(fill="x")
            heading.bind(
                "<KeyRelease>",
                lambda _e=None, b=block, w=heading: self._set_block_field(b, "text", w.get()),
            )
            ctk.CTkLabel(
                parent,
                text="Automatically inserts every screenshot attached in Assets & Evidence, "
                     "grouped by its assigned test case.",
                anchor="w", justify="left", wraplength=600, text_color=theme.TEXT_MUTED,
                font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3),
            ).pack(fill="x", pady=(6, 0))

        elif kind == BLOCK_CODE:
            language = self._text_entry(parent, block.language, placeholder="Language (e.g. python)")
            language.pack(fill="x")
            language.bind(
                "<KeyRelease>",
                lambda _e=None, b=block, w=language: self._set_block_field(b, "language", w.get()),
            )
            textbox = self._textbox(parent, block.text, height=96, mono=True)
            textbox.pack(fill="x", pady=(6, 0))
            textbox.bind(
                "<KeyRelease>",
                lambda _e=None, b=block, w=textbox: self._set_block_field(b, "text", w.get("1.0", "end-1c")),
            )

        elif kind == BLOCK_TWO_COLUMNS:
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x")
            row.grid_columnconfigure(0, weight=1, uniform="cols")
            row.grid_columnconfigure(1, weight=1, uniform="cols")
            columns = list(block.columns) + ["", ""]
            for index in range(2):
                textbox = self._textbox(row, columns[index], height=76)
                textbox.grid(row=0, column=index, sticky="nsew", padx=(0, 6) if index == 0 else (6, 0))
                textbox.bind(
                    "<KeyRelease>",
                    lambda _e=None, b=block, w=textbox, i=index: self._set_column(b, i, w.get("1.0", "end-1c")),
                )

        elif kind == BLOCK_SEPARATOR:
            ctk.CTkFrame(parent, fg_color=theme.BORDER_MUTED, height=2).pack(fill="x", pady=8)

    def _build_table_fields(self, parent, block: TemplateBlock) -> None:
        """Columns only.

        A table's column count is part of the document's structure and is
        fixed here; rows are content, so they are added while filling the
        document in (Control Center → Document Content), however many the
        reader needs.
        """
        weights = block.normalized_col_weights()

        controls = ctk.CTkFrame(parent, fg_color="transparent")
        controls.pack(fill="x", pady=(0, 8))

        self._stepper(
            controls, "Columns", block.col_count, MIN_TABLE_COLS, MAX_TABLE_COLS,
            lambda value, b=block: self._resize_table(b, b.row_count, value),
        )

        header_var = ctk.BooleanVar(value=block.include_headers)
        ctk.CTkSwitch(
            controls, text="Header row", variable=header_var, width=40,
            switch_width=32, switch_height=16,
            progress_color=theme.ACCENT_TECH_BLUE, text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 2),
            command=lambda b=block, v=header_var: self._set_block_field(b, "include_headers", v.get()),
        ).pack(side="left", padx=(14, 0))

        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="x")
        for col in range(max(1, block.col_count)):
            # Mirror the document: each editor column is as wide as the column
            # it configures, so the widths being set are visible at a glance.
            grid.grid_columnconfigure(col, weight=weights[col], uniform="tablecols")

        if block.include_headers:
            for col in range(block.col_count):
                entry = self._text_entry(
                    grid, block.table_headers[col] if col < len(block.table_headers) else "",
                    placeholder=f"Header {col + 1}", bold=True,
                )
                entry.grid(row=0, column=col, sticky="ew", padx=2, pady=2)
                entry.bind(
                    "<KeyRelease>",
                    lambda _e=None, b=block, c=col, w=entry: self._set_table_header(b, c, w.get()),
                )

        percentages = block.col_width_percentages()
        for col in range(block.col_count):
            self._width_control(grid, block, col, weights[col], percentages[col]).grid(
                row=1, column=col, sticky="ew", padx=2, pady=(2, 0)
            )

        row_word = "row" if block.row_count == 1 else "rows"
        split = " · ".join(f"{p}%" for p in percentages)
        ctk.CTkLabel(
            parent,
            text=f"{block.col_count} columns ({split}) · {block.row_count} {row_word} of content — "
                 f"add or remove rows while filling the document in.",
            anchor="w", justify="left", wraplength=600, text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 3),
        ).pack(fill="x", pady=(6, 0))

    def _width_control(self, parent, block: TemplateBlock, col: int, weight: int, percent: int):
        """Compact −/+ control for one column's relative width."""
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        # Centre the group rather than letting the buttons drift to the cell
        # edges, where a wide column's "+" would sit against its neighbour's "−".
        inner = ctk.CTkFrame(wrap, fg_color="transparent")
        inner.pack(expand=True)

        ctk.CTkButton(
            inner, text="−", width=22, height=22, fg_color=theme.SURFACE_GREY,
            hover_color=theme.SURFACE_CARD_HOVER, text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
            state="normal" if weight > MIN_COL_WEIGHT else "disabled",
            command=lambda: self._set_col_weight(block, col, weight - 1),
        ).pack(side="left")

        ctk.CTkLabel(
            inner, text=f"{percent}%", width=42, text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 2),
        ).pack(side="left")

        ctk.CTkButton(
            inner, text="＋", width=22, height=22, fg_color=theme.SURFACE_GREY,
            hover_color=theme.SURFACE_CARD_HOVER, text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
            state="normal" if weight < MAX_COL_WEIGHT else "disabled",
            command=lambda: self._set_col_weight(block, col, weight + 1),
        ).pack(side="left")

        return wrap

    # --- Small widget factories ------------------------------------------

    def _text_entry(self, parent, value: str, placeholder: str = "", bold: bool = False) -> ctk.CTkEntry:
        entry = ctk.CTkEntry(
            parent, height=28, fg_color=theme.SURFACE_GREY, border_color=theme.BORDER_MUTED,
            text_color=theme.TEXT_PRIMARY, placeholder_text=placeholder,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold" if bold else "normal"),
        )
        if value:
            entry.insert(0, value)
        return entry

    def _textbox(self, parent, value: str, height: int = 80, mono: bool = False) -> ctk.CTkTextbox:
        font = theme.mono_font_tuple(theme.FONT_SIZE_LABEL - 1) if mono else (
            theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL
        )
        textbox = ctk.CTkTextbox(
            parent, height=height, fg_color=theme.SURFACE_GREY, border_color=theme.BORDER_MUTED,
            border_width=1, text_color=theme.TEXT_PRIMARY, wrap="word", font=font,
        )
        if value:
            textbox.insert("1.0", value)
        return textbox

    def _icon_button(
        self, parent, text: str, command: Callable[[], None],
        enabled: bool = True, danger: bool = False,
    ) -> ctk.CTkButton:
        button = ctk.CTkButton(
            parent, text=text, width=26, height=24, fg_color="transparent",
            hover_color=theme.STATUS_ERROR if danger else theme.SURFACE_CARD_HOVER,
            text_color=theme.TEXT_SECONDARY if enabled else theme.BORDER_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
            state="normal" if enabled else "disabled",
            command=command,
        )
        button.pack(side="right", padx=1)
        return button

    def _stepper(
        self, parent, label: str, value: int, minimum: int, maximum: int,
        on_change: Callable[[int], None],
    ) -> None:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(side="left", padx=(0, 14))

        ctk.CTkLabel(
            wrap, text=label, text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 2),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            wrap, text="−", width=24, height=24, fg_color=theme.SURFACE_GREY,
            hover_color=theme.SURFACE_CARD_HOVER, text_color=theme.TEXT_PRIMARY,
            state="normal" if value > minimum else "disabled",
            command=lambda: on_change(value - 1),
        ).pack(side="left")

        ctk.CTkLabel(
            wrap, text=str(value), width=26, text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
        ).pack(side="left")

        ctk.CTkButton(
            wrap, text="＋", width=24, height=24, fg_color=theme.SURFACE_GREY,
            hover_color=theme.SURFACE_CARD_HOVER, text_color=theme.TEXT_PRIMARY,
            state="normal" if value < maximum else "disabled",
            command=lambda: on_change(value + 1),
        ).pack(side="left")

    # --- Mutations -------------------------------------------------------

    def _selected_section(self) -> Optional[TemplateSection]:
        if self._selected_section_id:
            section = self.template.find_section(self._selected_section_id)
            if section is not None:
                return section
        return self.template.sections[-1] if self.template.sections else None

    def _select_section(self, section_id: str, rebuild: bool = True) -> None:
        if self._selected_section_id == section_id and self._selected_block_id is None:
            return
        self._selected_section_id = section_id
        self._selected_block_id = None
        if rebuild:
            self._rebuild_editor()

    def _select_block(self, section_id: str, block_id: str) -> None:
        self._selected_section_id = section_id
        self._selected_block_id = block_id
        self._rebuild_editor()

    def _add_section(self) -> None:
        section = self.template.add_section()
        self._selected_section_id = section.section_id
        self._selected_block_id = None
        self._mark_dirty()
        self._rebuild_editor()

    def _delete_section(self, section_id: str) -> None:
        section = self.template.find_section(section_id)
        if section is None:
            return
        if section.blocks and not messagebox.askyesno(
            "Delete Section",
            f"Delete '{section.title}' and its {len(section.blocks)} block(s)?",
            parent=self,
        ):
            return
        self.template.remove_section(section_id)
        if self._selected_section_id == section_id:
            self._selected_section_id = (
                self.template.sections[0].section_id if self.template.sections else None
            )
            self._selected_block_id = None
        self._mark_dirty()
        self._rebuild_editor()

    def _move_section(self, section_id: str, delta: int) -> None:
        if self.template.move_section(section_id, delta):
            self._mark_dirty()
            self._rebuild_editor()

    def _set_section_title(self, section: TemplateSection, value: str) -> None:
        section.title = value
        self._mark_dirty()

    def _set_section_enabled(self, section: TemplateSection, value: bool) -> None:
        section.enabled = bool(value)
        self._mark_dirty()
        self._rebuild_sidebar()

    def _set_section_show_title(self, section: TemplateSection, value: bool) -> None:
        section.show_title = bool(value)
        self._mark_dirty()

    def _toggle_section_visibility(self, section_id: str) -> None:
        section = self.template.find_section(section_id)
        if section is None:
            return
        section.enabled = not section.enabled
        self._mark_dirty()
        self._rebuild_editor()

    def _add_block(self, kind: str) -> None:
        section = self._selected_section()
        if section is None:
            section = self.template.add_section(TemplateSection(title="Section 1"))
            self._selected_section_id = section.section_id
        try:
            block = TemplateBlock.create(kind)
        except TemplateError as e:
            messagebox.showerror("Unsupported Block", str(e), parent=self)
            return
        section.add_block(block)
        self._selected_block_id = block.block_id
        self._selected_section_id = section.section_id
        self._mark_dirty()
        self._rebuild_editor()

    def _delete_block(self, section: TemplateSection, block_id: str) -> None:
        if section.remove_block(block_id):
            if self._selected_block_id == block_id:
                self._selected_block_id = None
            self._mark_dirty()
            self._rebuild_editor()

    def _duplicate_block(self, section: TemplateSection, block_id: str) -> None:
        block = section.find_block(block_id)
        if block is None:
            return
        index = section.blocks.index(block)
        clone = block.clone()
        section.add_block(clone, index=index + 1)
        self._selected_block_id = clone.block_id
        self._mark_dirty()
        self._rebuild_editor()

    def _move_block(self, section: TemplateSection, block_id: str, delta: int) -> None:
        if section.move_block(block_id, delta):
            self._mark_dirty()
            self._rebuild_editor()

    def _set_block_field(self, block: TemplateBlock, field_name: str, value) -> None:
        previous = getattr(block, field_name, None)
        setattr(block, field_name, value)
        self._mark_dirty()

        # The Layers outline summarises level/flags/counts, so refresh it when
        # one of those actually changes - but never on every keystroke inside
        # a list item, which would rebuild the sidebar continuously.
        if field_name == "items":
            if isinstance(previous, list) and len(previous) != len(value):
                self._rebuild_sidebar()
        elif field_name in ("level", "ordered", "include_headers"):
            self._rebuild_sidebar()

    def _set_column(self, block: TemplateBlock, index: int, value: str) -> None:
        columns = list(block.columns) + ["", ""]
        columns[index] = value
        block.columns = columns[:2]
        self._mark_dirty()

    def _set_table_header(self, block: TemplateBlock, col: int, value: str) -> None:
        block.set_header(col, value)
        self._mark_dirty()

    def _resize_table(self, block: TemplateBlock, rows: int, cols: int) -> None:
        block.set_table_size(rows, cols)
        self._mark_dirty()
        self._rebuild_editor()

    def _set_col_weight(self, block: TemplateBlock, col: int, weight: int) -> None:
        if not block.set_col_weight(col, weight):
            return
        self._mark_dirty()
        self._rebuild_editor()
        if self._mode == MODE_PREVIEW:
            self._refresh_preview()

    def _browse_image(self, block: TemplateBlock) -> None:
        path = filedialog.askopenfilename(
            title="Select Image", filetypes=IMAGE_FILETYPES, parent=self
        )
        if not path:
            return
        block.image_path = path
        self._mark_dirty()
        self._rebuild_editor()

    # --- Save --------------------------------------------------------------

    def _on_save(self) -> bool:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name Required", "Give your template a name before saving.", parent=self)
            self.name_entry.focus_set()
            return False
        if not self.template.sections:
            messagebox.showwarning(
                "Nothing to Save", "Add at least one section before saving.", parent=self
            )
            return False

        self.template.name = name
        try:
            self.store.save(self.template)
        except (TemplateError, OSError) as e:
            messagebox.showerror("Save Failed", f"Could not save this template:\n{e}", parent=self)
            return False

        self._dirty = False
        self._is_new = False
        self._refresh_status()
        if self.on_saved:
            # Hand out a copy so later edits here can't leak into the main
            # window before the user saves again.
            self.on_saved(self.template.copy())
        return True

    # --- Close -----------------------------------------------------------

    def request_close(self) -> None:
        if self._dirty:
            answer = messagebox.askyesnocancel(
                "Unsaved Changes",
                "Save this template before closing?",
                parent=self,
            )
            if answer is None:
                return
            if answer and not self._on_save():
                return
        self.destroy()

    def destroy(self) -> None:
        """Notify the owner however this window goes away.

        The Control Center disables its content editor while this window owns
        the template, so a close path that skipped the callback left those
        fields permanently uneditable - "I can't type in the panel". Hooking
        destroy() covers every route: the back button, the window manager's
        close box, Escape, and a programmatic destroy during shutdown.
        """
        already_notified = self._closed_notified
        self._closed_notified = True
        try:
            super().destroy()
        finally:
            if not already_notified and self.on_closed:
                self.on_closed()
