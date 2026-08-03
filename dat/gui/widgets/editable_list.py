"""Reusable editable list of text rows (add / edit / remove), e.g. key points or test cases."""
from typing import Callable, List

import customtkinter as ctk

from dat.gui import theme


class EditableListField(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_change: Callable[[List[str]], None],
        add_label: str = "+ Add",
        row_placeholder: str = "",
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_change = on_change
        self.row_placeholder = row_placeholder
        self._values: List[str] = []

        self.rows_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.rows_frame.pack(fill="x")

        self.add_btn = ctk.CTkButton(
            self, text=add_label, height=26,
            fg_color=theme.SURFACE_GREY_LIGHT, hover_color=theme.ACCENT_TECH_BLUE,
            text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
            command=self._add_row,
        )
        self.add_btn.pack(fill="x", pady=(4, 0))

    def set_values(self, values: List[str]) -> None:
        self._values = list(values)
        self._rebuild()

    def get_values(self) -> List[str]:
        return list(self._values)

    def _rebuild(self) -> None:
        for child in self.rows_frame.winfo_children():
            child.destroy()
        for idx, value in enumerate(self._values):
            self._build_row(idx, value)

    def _build_row(self, idx: int, value: str) -> None:
        row = ctk.CTkFrame(self.rows_frame, fg_color=theme.SURFACE_GREY_LIGHT, corner_radius=6)
        row.pack(fill="x", pady=3)

        entry = ctk.CTkEntry(
            row, fg_color="transparent", border_width=0,
            text_color=theme.TEXT_PRIMARY, placeholder_text=self.row_placeholder,
        )
        entry.insert(0, value)
        entry.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=4)
        entry.bind("<KeyRelease>", lambda _e, i=idx, w=entry: self._on_row_edit(i, w))

        remove_btn = ctk.CTkButton(
            row, text="✕", width=22, height=22, fg_color="transparent",
            hover_color=theme.STATUS_ERROR, text_color=theme.TEXT_SECONDARY,
            command=lambda i=idx: self._remove_row(i),
        )
        remove_btn.pack(side="right", padx=(4, 8))

    def _on_row_edit(self, idx: int, widget: ctk.CTkEntry) -> None:
        self._values[idx] = widget.get()
        self.on_change(list(self._values))

    def _remove_row(self, idx: int) -> None:
        del self._values[idx]
        self._rebuild()
        self.on_change(list(self._values))

    def _add_row(self) -> None:
        self._values.append("")
        self._rebuild()
        self.on_change(list(self._values))
