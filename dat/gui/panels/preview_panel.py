"""Right panel: Live Preview - a high-fidelity, reactive representation of the .docx file.

Block rendering itself lives in DocumentCanvas so the template builder's
Preview mode renders identically.
"""
import tkinter.font as tkfont
from typing import Callable, List

import customtkinter as ctk

from dat.gui import theme
from dat.gui.state import PreviewBlock
from dat.gui.text_fit import truncate_to_width
from dat.gui.widgets.document_canvas import DocumentCanvas


EXPORT_BUTTON_WIDTH = 160
MIN_TITLE_WIDTH = 140
# Breathing room between the title text and the Export button.
TITLE_RIGHT_GUTTER = 16


class PreviewPanel(ctk.CTkFrame):
    def __init__(self, master, on_export: Callable[[], None], **kwargs):
        super().__init__(master, fg_color=theme.BG_DEEP_DARK, corner_radius=0, **kwargs)
        self._title = "Untitled Feature"
        self._subtitle = "Standard Document"

        self._build_header(on_export)
        self._build_page()

    def _build_header(self, on_export: Callable[[], None]):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.PADDING_LG, pady=(theme.PADDING_LG, theme.PADDING_SM))

        # Packed before the title block on purpose: pack gives space in the
        # order widgets are added, so claiming the button's width first is
        # what stops a long document name from squeezing it off-screen.
        self.export_btn = ctk.CTkButton(
            header, text="Export DOCX", width=EXPORT_BUTTON_WIDTH, height=38,
            fg_color=theme.ACCENT_TECH_BLUE, hover_color=theme.ACCENT_TECH_BLUE_HOVER,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL, "bold"),
            border_spacing=10,
            command=on_export,
        )
        self.export_btn.pack(side="right", padx=(theme.PADDING_MD, 0))

        self.titles = ctk.CTkFrame(header, fg_color="transparent")
        self.titles.pack(side="left", fill="x", expand=True)

        self.title_label = ctk.CTkLabel(
            self.titles, text="Untitled Feature", anchor="w", text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_HEADING, "bold"),
        )
        self.title_label.pack(fill="x")

        self.subtitle_label = ctk.CTkLabel(
            self.titles, text="Standard Document", anchor="w", text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
        )
        self.subtitle_label.pack(fill="x")

        # Fonts for measuring: built once, and matched to the labels above.
        self._title_font = tkfont.Font(
            family=theme.FONT_INTERFACE_FAMILY, size=theme.FONT_SIZE_HEADING, weight="bold"
        )
        self._subtitle_font = tkfont.Font(
            family=theme.FONT_INTERFACE_FAMILY, size=theme.FONT_SIZE_LABEL - 1
        )
        self._fitted_width = 0
        self.titles.bind("<Configure>", self._on_titles_resize)

    # --- Header text fitting ---------------------------------------------

    def _on_titles_resize(self, event):
        # Re-fit only on a real width change; the label's own text change
        # would otherwise bounce this back and forth.
        if abs(event.width - self._fitted_width) < 8:
            return
        self._fitted_width = event.width
        self._apply_header_text()

    def _available_title_width(self) -> int:
        width = self.titles.winfo_width()
        # Before the first layout pass winfo_width() is 1; fall back to the
        # panel's width minus the button so the first paint is already right.
        if width <= 1:
            width = max(
                MIN_TITLE_WIDTH,
                self.winfo_width() - EXPORT_BUTTON_WIDTH - 3 * theme.PADDING_LG,
            )
        return max(MIN_TITLE_WIDTH, width - TITLE_RIGHT_GUTTER)

    def _apply_header_text(self):
        width = self._available_title_width()
        self.title_label.configure(
            text=truncate_to_width(self._title, self._title_font.measure, width)
        )
        self.subtitle_label.configure(
            text=truncate_to_width(self._subtitle, self._subtitle_font.measure, width)
        )

    def _build_page(self):
        self.canvas = DocumentCanvas(self)
        self.canvas.pack(fill="both", expand=True, padx=theme.PADDING_LG, pady=(0, theme.PADDING_LG))

    def set_title(self, title: str):
        """Set the document name, shortened with an ellipsis if it is too long
        for the space left beside the Export button."""
        self._title = title or "Untitled Feature"
        self._apply_header_text()

    def set_subtitle(self, text: str):
        self._subtitle = text or ""
        self._apply_header_text()

    def render(self, blocks: List[PreviewBlock]):
        self.canvas.render(blocks)
