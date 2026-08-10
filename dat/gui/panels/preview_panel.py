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
# The status chip's action button: never narrower than this, and this much
# room around whatever label it is given.
STATUS_ACTION_MIN_WIDTH = 96
STATUS_ACTION_PADDING = 28


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

        # Status strip: what the document's content is doing right now
        # (waiting on the AI, fell back to the Git diff, ...) with an optional
        # one-click action. Packed right-to-left before the titles for the
        # same reason as the button above, and unpacked while idle so an empty
        # chip never holds space open.
        self.status_action_btn = ctk.CTkButton(
            header, text="", width=STATUS_ACTION_MIN_WIDTH, height=30,
            fg_color=theme.SURFACE_CARD, hover_color=theme.SURFACE_CARD_HOVER,
            border_width=1, border_color=theme.BORDER_MUTED,
            text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
            command=lambda: None,
        )
        self.status_label = ctk.CTkLabel(
            header, text="", anchor="e", text_color=theme.TEXT_MUTED,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
        )

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

    def set_status(
        self,
        text: str = "",
        color: str = None,
        action_label: str = "",
        action: Callable[[], None] = None,
    ) -> None:
        """Show (or clear, with no arguments) the content-status chip beside
        the Export button, optionally offering an action such as a retry."""
        if not text:
            # Cleared, not just hidden: a stale message must not flash back
            # into view the next time the chip is shown.
            self.status_label.configure(text="")
            self.status_label.pack_forget()
            self.status_action_btn.pack_forget()
            return

        self.status_label.configure(text=text, text_color=color or theme.TEXT_MUTED)

        if action and action_label:
            # Width measured from the label rather than fixed: a CTkButton
            # clips text it can't fit, and the resolved UI font is wider on
            # macOS than on Linux for the same nominal size.
            width = max(
                STATUS_ACTION_MIN_WIDTH,
                self._subtitle_font.measure(action_label) + STATUS_ACTION_PADDING,
            )
            self.status_action_btn.configure(text=action_label, command=action, width=width)
            self.status_action_btn.pack(side="right", padx=(theme.PADDING_SM, 0))
        else:
            self.status_action_btn.pack_forget()

        # Re-packed every time so the label always sits left of the action
        # button, whichever order the two were last shown in.
        self.status_label.pack_forget()
        self.status_label.pack(side="right", padx=(theme.PADDING_SM, 0))

        # The chip just took space from the title, so re-fit it now rather than
        # waiting for a <Configure> event that a small change may not trigger -
        # the amount taken depends on the platform's font metrics.
        self._apply_header_text()

    def render(self, blocks: List[PreviewBlock]):
        self.canvas.render(blocks)
