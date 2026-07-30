"""Right panel: Live Preview - a high-fidelity, reactive representation of the .docx file."""
import tkinter as tk
from typing import Callable, List, Optional

import customtkinter as ctk
from PIL import Image

from dat.gui import theme
from dat.gui.state import PreviewBlock

PAGE_BG = "#ffffff"
PAGE_TEXT = "#000000"
PAGE_BORDER = "#d0d0d0"

THUMB_MAX_WIDTH = 220


class PreviewPanel(ctk.CTkFrame):
    def __init__(self, master, on_export: Callable[[], None], **kwargs):
        super().__init__(master, fg_color=theme.BG_DEEP_DARK, corner_radius=0, **kwargs)
        self._image_refs = []

        self._build_header(on_export)
        self._build_page()

    def _build_header(self, on_export: Callable[[], None]):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.PADDING_LG, pady=(theme.PADDING_LG, theme.PADDING_SM))

        self.title_label = ctk.CTkLabel(
            header, text="Untitled Feature", anchor="w", text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_HEADING, "bold"),
        )
        self.title_label.pack(side="left", fill="x", expand=True)

        export_btn = ctk.CTkButton(
            header, text="Export DOCX", width=140, height=36,
            fg_color=theme.ACCENT_TECH_BLUE, hover_color=theme.ACCENT_TECH_BLUE_HOVER,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
            command=on_export,
        )
        export_btn.pack(side="right")

    def _build_page(self):
        outer = ctk.CTkScrollableFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=theme.PADDING_LG, pady=(0, theme.PADDING_LG))

        self.page = ctk.CTkFrame(outer, fg_color=PAGE_BG, corner_radius=4)
        self.page.pack(fill="both", expand=True)

    def set_title(self, title: str):
        self.title_label.configure(text=title or "Untitled Feature")

    def render(self, blocks: List[PreviewBlock]):
        for child in self.page.winfo_children():
            child.destroy()
        self._image_refs.clear()

        if not blocks:
            empty = ctk.CTkLabel(
                self.page, text="Nothing to preview - enable a section on the left.",
                text_color="#888888", font=theme.document_font_tuple(),
            )
            empty.pack(padx=theme.PADDING_MD, pady=theme.PADDING_MD)
            return

        for block in blocks:
            self._render_block(block)

    def _render_block(self, block: PreviewBlock):
        renderer = getattr(self, f"_render_{block.kind}", None)
        if renderer:
            renderer(block)

    def _heading(self, text: str, size: int = theme.FONT_SIZE_DOC_HEADING):
        lbl = tk.Label(
            self.page, text=text, bg=PAGE_BG, fg=PAGE_TEXT,
            font=(theme.FONT_DOCUMENT_FAMILY, size, "bold"), anchor="w",
        )
        lbl.pack(fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_SM, 4))

    def _render_title(self, block: PreviewBlock):
        lbl = tk.Label(
            self.page, text=block.text or "", bg=PAGE_BG, fg=PAGE_TEXT,
            font=(theme.FONT_DOCUMENT_FAMILY, theme.FONT_SIZE_DOC_TITLE, "bold"),
            anchor="w", wraplength=560, justify="left",
        )
        lbl.pack(fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_MD, theme.PADDING_SM))

    def _render_metadata_table(self, block: PreviewBlock):
        self._heading(block.heading or "Task Detail")
        self._build_table(block.table_rows, col_weights=(1, 2))

    def _render_changes_done(self, block: PreviewBlock):
        self._heading(block.heading or "Changes Done")
        if block.text:
            lbl = tk.Label(
                self.page, text=block.text, bg=PAGE_BG, fg=PAGE_TEXT,
                font=theme.document_font_tuple(weight="bold"), anchor="w",
            )
            lbl.pack(fill="x", padx=theme.PADDING_MD, pady=(0, 4))
        for point in block.bullets:
            bullet = tk.Label(
                self.page, text=f"•  {point}", bg=PAGE_BG, fg=PAGE_TEXT,
                font=theme.document_font_tuple(), anchor="w", justify="left", wraplength=540,
            )
            bullet.pack(fill="x", padx=(theme.PADDING_MD + 10, theme.PADDING_MD), pady=1)
        tk.Label(self.page, text="", bg=PAGE_BG).pack(pady=4)

    def _render_test_cases_table(self, block: PreviewBlock):
        self._heading(block.heading or "Test Cases")
        self._build_table(block.table_rows, headers=block.table_headers, col_weights=(1, 5, 1))

    def _render_screenshots(self, block: PreviewBlock):
        self._heading(block.heading or "Screenshots")
        for _case_idx, label, shots in block.screenshot_groups:
            sub = tk.Label(
                self.page, text=label, bg=PAGE_BG, fg=PAGE_TEXT,
                font=(theme.FONT_DOCUMENT_FAMILY, 13), anchor="w",
            )
            sub.pack(fill="x", padx=theme.PADDING_MD, pady=(theme.PADDING_SM, 4))

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
                self._add_thumbnail(cell, shot.file_path)
                col = (col + 1) % 2

    def _add_thumbnail(self, parent, file_path: Optional[str]):
        try:
            img = Image.open(file_path)
            ratio = THUMB_MAX_WIDTH / float(img.width)
            size = (THUMB_MAX_WIDTH, max(1, int(img.height * ratio)))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=size)
            self._image_refs.append(ctk_img)
            lbl = ctk.CTkLabel(parent, image=ctk_img, text="")
            lbl.pack()
        except Exception:
            lbl = tk.Label(
                parent, text="[image unavailable]", bg=PAGE_BG, fg="#999999",
                font=theme.document_font_tuple(),
            )
            lbl.pack()

    def _build_table(self, rows: List[List[str]], headers: Optional[List[str]] = None, col_weights=None):
        wrap = tk.Frame(self.page, bg=PAGE_BORDER)
        wrap.pack(fill="x", padx=theme.PADDING_MD, pady=(0, theme.PADDING_SM))

        col_weights = col_weights or tuple(1 for _ in (headers or rows[0] if rows else []))
        for c, weight in enumerate(col_weights):
            wrap.columnconfigure(c, weight=weight)

        r = 0
        if headers:
            for c, text in enumerate(headers):
                cell = tk.Label(
                    wrap, text=text, bg="#f2f2f2", fg=PAGE_TEXT,
                    font=theme.document_font_tuple(weight="bold"),
                    anchor="w", padx=8, pady=6,
                )
                cell.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
            r += 1

        for row in rows:
            for c, text in enumerate(row):
                cell = tk.Label(
                    wrap, text=text, bg=PAGE_BG, fg=PAGE_TEXT,
                    font=theme.document_font_tuple(), anchor="w", padx=8, pady=6,
                    height=1,
                )
                cell.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
            r += 1
