"""Scrollable white "paper" canvas that renders a list of PreviewBlock.

Extracted from PreviewPanel so the exact same rendering powers both the
main window's live preview and the template builder's Preview mode - a
custom template can therefore never look different in the two places.
"""
import tkinter as tk
from typing import Any, Dict, List, Optional, Tuple

import customtkinter as ctk
from PIL import Image

from dat.gui import theme
from dat.gui.state import PreviewBlock

PAGE_BG = "#ffffff"
PAGE_TEXT = "#000000"
PAGE_MUTED = "#666666"
PAGE_BORDER = "#d0d0d0"
PAGE_CODE_BG = "#f4f5f7"
PAGE_HEADER_BG = "#f2f2f2"

THUMB_MAX_WIDTH = 220
IMAGE_MAX_WIDTH = 360
DEFAULT_CONTENT_WIDTH = 560
MIN_CONTENT_WIDTH = 240
# A table cell's own padding (internal padx + grid gap), subtracted from the
# column's share when working out where its text should wrap.
CELL_PADDING = 24

HEADING_SIZES = {
    1: theme.FONT_SIZE_DOC_HEADING,
    2: theme.FONT_SIZE_DOC_HEADING - 2,
    3: theme.FONT_SIZE_DOC_HEADING - 4,
}

EMPTY_MESSAGE = "Nothing to preview - enable a section on the left."


def _layout_signature(block: PreviewBlock) -> tuple:
    """Everything about a block that decides which *widgets* it needs.

    Text is deliberately excluded: two renders with the same signature
    differ only in the strings, which can be pushed into the existing
    labels. Anything that would add, remove or resize a widget (counts,
    heading level, image path, screenshot grouping) belongs here.
    """
    return (
        block.kind,
        block.level,
        block.ordered,
        block.image_path,
        block.heading is not None,
        block.text is not None,
        len(block.bullets),
        len(block.table_headers),
        tuple(len(row) for row in block.table_rows),
        tuple(block.col_weights),
        len(block.columns),
        tuple(
            (case_index, tuple(shot.file_path for shot in shots))
            for case_index, _label, shots in block.screenshot_groups
        ),
    )


class DocumentCanvas(ctk.CTkFrame):
    """Renders PreviewBlocks, updating text in place wherever it can.

    Rebuilding every widget on each keystroke is what makes a live preview
    flicker, so a render that only changes *text* (the common case while
    typing) reconfigures the existing labels instead. Widgets are only
    destroyed and recreated when the document's shape actually changes -
    a block added, a row removed, a different image.
    """

    def __init__(self, master, empty_message: str = EMPTY_MESSAGE, **kwargs):
        super().__init__(master, fg_color="transparent", corner_radius=0, **kwargs)
        self._empty_message = empty_message
        self._image_refs: List[ctk.CTkImage] = []
        self._wrapping_labels: List[tuple] = []  # (label, padding_px, width_fraction)
        self._content_width = DEFAULT_CONTENT_WIDTH
        self._blocks: List[PreviewBlock] = []
        # Per-block map of slot name -> label(s), filled during a full build
        # and reused for in-place text updates.
        self._text_slots: List[Dict[str, Any]] = []
        self._slots: Dict[str, Any] = {}
        self._layout_signature: Optional[tuple] = None
        self.rebuild_count = 0       # exposed for tests/diagnostics
        self.text_update_count = 0

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True)

        self.page = ctk.CTkFrame(self._scroll, fg_color=PAGE_BG, corner_radius=4)
        self.page.pack(fill="both", expand=True)
        self.page.bind("<Configure>", self._on_page_resize)

    # --- Public API ------------------------------------------------------

    def render(self, blocks: List[PreviewBlock]) -> None:
        blocks = list(blocks)
        signature = tuple(_layout_signature(block) for block in blocks)

        # Same shape as what is on screen -> just push the new strings into
        # the labels already there. No teardown, so no flicker, no scroll
        # jump, and no image reloads while the user types.
        if blocks and signature == self._layout_signature and len(self._text_slots) == len(blocks):
            self._blocks = blocks
            self._apply_text_updates(blocks)
            self.text_update_count += 1
            return

        self._full_render(blocks, signature)

    def _full_render(self, blocks: List[PreviewBlock], signature: tuple) -> None:
        offset = self._scroll_offset()

        self._blocks = blocks
        for child in self.page.winfo_children():
            child.destroy()
        self._image_refs.clear()
        self._wrapping_labels.clear()
        self._text_slots = []
        self._layout_signature = signature
        self.rebuild_count += 1

        if not blocks:
            tk.Label(
                self.page, text=self._empty_message, bg=PAGE_BG, fg="#888888",
                font=theme.document_font_tuple(),
            ).pack(padx=theme.PADDING_MD, pady=theme.PADDING_MD)
            return

        for block in blocks:
            self._slots = {}
            self._render_block(block)
            self._text_slots.append(self._slots)
        self._slots = {}
        self._apply_wraplengths()

        # Keep the reader where they were when the shape changed under them.
        if offset:
            self.after_idle(lambda: self._restore_scroll(offset))

    # --- In-place text updates -------------------------------------------

    def _apply_text_updates(self, blocks: List[PreviewBlock]) -> None:
        for block, slots in zip(blocks, self._text_slots):
            self._set_text(slots.get("heading"), block.heading)
            self._set_text(slots.get("text"), block.text)
            self._set_many(slots.get("bullets"), self._bullet_texts(block))
            self._set_many(slots.get("headers"), block.table_headers)
            self._set_many(slots.get("columns"), block.columns)
            self._set_many(slots.get("groups"), [label for _i, label, _s in block.screenshot_groups])
            cells = slots.get("cells")
            if cells:
                for row_index, row_labels in enumerate(cells):
                    row = block.table_rows[row_index] if row_index < len(block.table_rows) else []
                    self._set_many(row_labels, row)

    @staticmethod
    def _bullet_texts(block: PreviewBlock) -> List[str]:
        return [
            f"{index}.  {point}" if block.ordered else f"•  {point}"
            for index, point in enumerate(block.bullets, start=1)
        ]

    @staticmethod
    def _set_text(label, value) -> None:
        if label is None:
            return
        text = value or ""
        try:
            if label.cget("text") != text:
                label.configure(text=text)
        except tk.TclError:
            pass  # widget went away between renders

    def _set_many(self, labels, values) -> None:
        if not labels:
            return
        values = list(values or [])
        for index, label in enumerate(labels):
            self._set_text(label, values[index] if index < len(values) else "")

    # --- Slot registration (used by the renderers below) ------------------

    def _slot(self, name: str, widget):
        self._slots[name] = widget
        return widget

    def _slot_list(self, name: str, widgets):
        self._slots[name] = widgets
        return widgets

    def scroll_to_top(self) -> None:
        try:
            self._scroll._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

    def _scroll_offset(self) -> float:
        try:
            return float(self._scroll._parent_canvas.yview()[0])
        except Exception:
            return 0.0

    def _restore_scroll(self, offset: float) -> None:
        try:
            self._scroll._parent_canvas.yview_moveto(offset)
        except Exception:
            pass

    # --- Responsive text wrapping ---------------------------------------

    def _on_page_resize(self, event) -> None:
        width = max(MIN_CONTENT_WIDTH, event.width - 2 * theme.PADDING_MD)
        if abs(width - self._content_width) < 8:
            return
        self._content_width = width
        self._apply_wraplengths()

    def _wrap_width(self, padding: int, fraction: float) -> int:
        floor = max(80, int(MIN_CONTENT_WIDTH * fraction))
        return max(floor, int(self._content_width * fraction) - padding)

    def _apply_wraplengths(self) -> None:
        for label, padding, fraction in self._wrapping_labels:
            try:
                label.configure(wraplength=self._wrap_width(padding, fraction))
            except tk.TclError:
                pass  # label destroyed by a re-render mid-resize

    def _track_wrapping(self, label: tk.Label, padding: int = 0, fraction: float = 1.0) -> tk.Label:
        """Keep ``label`` wrapping to the page width as the panel resizes.

        ``fraction`` is the share of the page the label occupies (0.5 for one
        cell of a two-column block).
        """
        self._wrapping_labels.append((label, padding, fraction))
        label.configure(wraplength=self._wrap_width(padding, fraction))
        return label

    # --- Dispatch --------------------------------------------------------

    def _render_block(self, block: PreviewBlock) -> None:
        renderer = getattr(self, f"_render_{block.kind}", None)
        if renderer:
            renderer(block)

    def _heading(self, text: str, size: int = theme.FONT_SIZE_DOC_HEADING) -> tk.Label:
        label = tk.Label(
            self.page, text=text, bg=PAGE_BG, fg=PAGE_TEXT,
            font=(theme.FONT_DOCUMENT_FAMILY, size, "bold"), anchor="w", justify="left",
        )
        self._track_wrapping(label, padding=2 * theme.PADDING_MD)
        label.pack(fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_SM, 4))
        return label

    # --- Built-in document sections --------------------------------------

    def _render_title(self, block: PreviewBlock) -> None:
        label = tk.Label(
            self.page, text=block.text or "", bg=PAGE_BG, fg=PAGE_TEXT,
            font=(theme.FONT_DOCUMENT_FAMILY, theme.FONT_SIZE_DOC_TITLE, "bold"),
            anchor="w", justify="left",
        )
        self._track_wrapping(label, padding=2 * theme.PADDING_MD)
        label.pack(fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_MD, theme.PADDING_SM))
        self._slot("text", label)

    def _render_metadata_table(self, block: PreviewBlock) -> None:
        self._slot("heading", self._heading(block.heading or "Task Detail"))
        headers, cells = self._build_table(block.table_rows, col_weights=(1, 2))
        self._slot_list("cells", cells)

    def _render_changes_done(self, block: PreviewBlock) -> None:
        self._slot("heading", self._heading(block.heading or "Changes Done"))
        if block.text:
            label = tk.Label(
                self.page, text=block.text, bg=PAGE_BG, fg=PAGE_TEXT,
                font=theme.document_font_tuple(weight="bold"), anchor="w", justify="left",
            )
            self._track_wrapping(label, padding=2 * theme.PADDING_MD)
            label.pack(fill="x", padx=theme.PADDING_MD, pady=(0, 4))
            self._slot("text", label)
        self._slot_list("bullets", self._render_bullets(block.bullets))
        tk.Label(self.page, text="", bg=PAGE_BG).pack(pady=4)

    def _render_test_cases_table(self, block: PreviewBlock) -> None:
        self._slot("heading", self._heading(block.heading or "Test Cases"))
        headers, cells = self._build_table(
            block.table_rows, headers=block.table_headers, col_weights=(1, 5, 1)
        )
        self._slot_list("headers", headers)
        self._slot_list("cells", cells)

    def _render_screenshots(self, block: PreviewBlock) -> None:
        self._slot("heading", self._heading(block.heading or "Screenshots"))
        group_labels = []
        for _case_idx, label, shots in block.screenshot_groups:
            sub = tk.Label(
                self.page, text=label, bg=PAGE_BG, fg=PAGE_TEXT,
                font=(theme.FONT_DOCUMENT_FAMILY, 13), anchor="w", justify="left",
            )
            self._track_wrapping(sub, padding=2 * theme.PADDING_MD)
            sub.pack(fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_SM, 4))
            group_labels.append(sub)

            if not shots:
                continue

            grid = tk.Frame(self.page, bg=PAGE_BG)
            grid.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))

            col = 0
            row_frame = None
            for shot in shots:
                if col == 0:
                    row_frame = tk.Frame(grid, bg=PAGE_BG)
                    row_frame.pack(fill="x", pady=6)
                cell = tk.Frame(row_frame, bg=PAGE_BG)
                cell.pack(side="left", padx=6, expand=True)
                self._add_image_label(cell, shot.file_path, THUMB_MAX_WIDTH)
                col = (col + 1) % 2
        self._slot_list("groups", group_labels)

    # --- Custom template blocks ------------------------------------------

    def _render_doc_heading(self, block: PreviewBlock) -> None:
        self._slot("text", self._heading(
            block.text or "", size=HEADING_SIZES.get(block.level, theme.FONT_SIZE_DOC_BODY + 1)
        ))

    def _render_paragraph(self, block: PreviewBlock) -> None:
        label = tk.Label(
            self.page, text=block.text or "", bg=PAGE_BG, fg=PAGE_TEXT,
            font=theme.document_font_tuple(), anchor="w", justify="left",
        )
        self._track_wrapping(label, padding=2 * theme.PADDING_MD)
        label.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))
        self._slot("text", label)

    def _render_bullet_list(self, block: PreviewBlock) -> None:
        self._slot_list("bullets", self._render_bullets(block.bullets, ordered=block.ordered))
        tk.Label(self.page, text="", bg=PAGE_BG).pack(pady=2)

    def _render_bullets(self, bullets: List[str], ordered: bool = False) -> List[tk.Label]:
        labels: List[tk.Label] = []
        for index, point in enumerate(bullets, start=1):
            marker = f"{index}." if ordered else "•"
            label = tk.Label(
                self.page, text=f"{marker}  {point}", bg=PAGE_BG, fg=PAGE_TEXT,
                font=theme.document_font_tuple(), anchor="w", justify="left",
            )
            self._track_wrapping(label, padding=2 * theme.PADDING_MD + 10)
            label.pack(fill="x", padx=(theme.PADDING_MD + 10, theme.PADDING_MD), pady=1)
            labels.append(label)
        return labels

    def _render_table(self, block: PreviewBlock) -> None:
        headers, cells = self._build_table(
            block.table_rows,
            headers=block.table_headers or None,
            col_weights=tuple(block.col_weights) or None,
        )
        self._slot_list("headers", headers)
        self._slot_list("cells", cells)

    def _render_image(self, block: PreviewBlock) -> None:
        holder = tk.Frame(self.page, bg=PAGE_BG)
        holder.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))
        self._add_image_label(holder, block.image_path, IMAGE_MAX_WIDTH)
        if block.text:
            caption = tk.Label(
                holder, text=block.text, bg=PAGE_BG, fg=PAGE_MUTED,
                font=(theme.FONT_DOCUMENT_FAMILY, theme.FONT_SIZE_DOC_BODY - 1, "italic"),
            )
            caption.pack(pady=(4, 0))
            self._slot("text", caption)

    def _render_code(self, block: PreviewBlock) -> None:
        wrap = tk.Frame(self.page, bg=PAGE_CODE_BG, highlightbackground=PAGE_BORDER, highlightthickness=1)
        wrap.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))
        label = tk.Label(
            wrap, text=block.text or "", bg=PAGE_CODE_BG, fg=PAGE_TEXT,
            font=theme.mono_font_tuple(theme.FONT_SIZE_DOC_BODY - 1), anchor="w", justify="left",
        )
        label.pack(fill="x", padx=10, pady=8)
        self._slot("text", label)

    def _render_two_columns(self, block: PreviewBlock) -> None:
        wrap = tk.Frame(self.page, bg=PAGE_BG)
        wrap.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))
        columns = list(block.columns) + ["", ""]
        column_labels = []
        for index in range(2):
            wrap.columnconfigure(index, weight=1, uniform="cols")
            label = tk.Label(
                wrap, text=columns[index], bg=PAGE_BG, fg=PAGE_TEXT,
                font=theme.document_font_tuple(), anchor="nw", justify="left",
            )
            # Each cell owns half the page, minus the 12px gutter either side.
            self._track_wrapping(label, padding=theme.PADDING_MD + 12, fraction=0.5)
            label.grid(row=0, column=index, sticky="nsew", padx=(0, 12) if index == 0 else (12, 0))
            column_labels.append(label)
        self._slot_list("columns", column_labels)

    def _render_separator(self, _block: PreviewBlock) -> None:
        line = tk.Frame(self.page, bg=PAGE_BORDER, height=1)
        line.pack(fill="x", padx=theme.PADDING_MD, pady=theme.PADDING_SM)

    # --- Shared primitives -----------------------------------------------

    def _add_image_label(self, parent, file_path: Optional[str], max_width: int) -> None:
        try:
            with Image.open(file_path) as img:
                img.load()
                ratio = max_width / float(img.width)
                size = (max_width, max(1, int(img.height * ratio)))
                ctk_img = ctk.CTkImage(light_image=img.copy(), dark_image=img.copy(), size=size)
            self._image_refs.append(ctk_img)
            ctk.CTkLabel(parent, image=ctk_img, text="").pack()
        except Exception:
            tk.Label(
                parent, text="[image unavailable]", bg=PAGE_BG, fg="#999999",
                font=theme.document_font_tuple(),
            ).pack()

    def _build_table(
        self,
        rows: List[List[str]],
        headers: Optional[List[str]] = None,
        col_weights=None,
    ) -> Tuple[List[tk.Label], List[List[tk.Label]]]:
        """Build the grid and hand back its labels (header row, then cells) so
        the caller can update their text in place on the next render."""
        if not rows and not headers:
            return [], []

        wrap = tk.Frame(self.page, bg=PAGE_BORDER)
        wrap.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))

        col_count = len(headers) if headers else (len(rows[0]) if rows else 0)
        if col_weights is None or len(col_weights) != col_count:
            col_weights = tuple(1 for _ in range(col_count))

        # `uniform` is what makes Tk size the columns in proportion to their
        # weights; without it, weight only shares out leftover space.
        for c, weight in enumerate(col_weights):
            wrap.columnconfigure(c, weight=max(1, int(weight)), uniform="table")

        total_weight = sum(max(1, int(w)) for w in col_weights) or 1
        fractions = [max(1, int(w)) / total_weight for w in col_weights]

        def cell(text: str, column: int, row_index: int, header: bool) -> tk.Label:
            label = tk.Label(
                wrap, text=text,
                bg=PAGE_HEADER_BG if header else PAGE_BG, fg=PAGE_TEXT,
                font=theme.document_font_tuple(weight="bold" if header else "normal"),
                anchor="w", justify="left", padx=8, pady=6,
            )
            # Wrap to the column's own share, so a narrow column stays narrow
            # instead of being forced wide by one long value.
            self._track_wrapping(label, padding=CELL_PADDING, fraction=fractions[column])
            label.grid(row=row_index, column=column, sticky="nsew", padx=1, pady=1)
            return label

        header_labels: List[tk.Label] = []
        cell_labels: List[List[tk.Label]] = []

        r = 0
        if headers:
            header_labels = [
                cell(headers[c] if c < len(headers) else "", c, r, header=True)
                for c in range(col_count)
            ]
            r += 1

        for row in rows:
            cell_labels.append([
                cell(row[c] if c < len(row) else "", c, r, header=False)
                for c in range(col_count)
            ])
            r += 1

        return header_labels, cell_labels
