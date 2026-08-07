"""Assets & Evidence drop zone: dashed-border drag-and-drop area for screenshots.

Each row also lets the user assign the screenshot to a specific test case
(or leave it on Auto) and drag-reorder rows to control the hierarchy/order
screenshots are exported in.
"""
import os
from typing import Callable, List, Optional

import customtkinter as ctk

from dat.gui import theme
from dat.gui.text_fit import truncate_to_length
from dat.models.screenshot_info import ScreenshotInfo

try:
    from tkinterdnd2 import DND_FILES
    _DND_AVAILABLE = True
except ImportError:
    DND_FILES = None
    _DND_AVAILABLE = False

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif")
DEFAULT_ROW_HEIGHT = 36
MAX_FILENAME_LENGTH = 12


def _parse_dnd_paths(raw: str) -> List[str]:
    """Parse the Tcl list format tkinterdnd2 hands back on drop (handles spaces via {..})."""
    paths = []
    token = ""
    in_braces = False
    for ch in raw:
        if ch == "{":
            in_braces = True
        elif ch == "}":
            in_braces = False
        elif ch == " " and not in_braces:
            if token:
                paths.append(token)
                token = ""
            continue
        else:
            token += ch
    if token:
        paths.append(token)
    return [p.strip("{}") for p in paths]


class DropZone(ctk.CTkFrame):
    """Dashed-border container for adding, ordering, and assigning local screenshots."""

    def __init__(
        self,
        master,
        on_files_added: Callable[[List[str]], None],
        on_file_removed: Callable[[str], None],
        on_reorder: Callable[[List[str]], None],
        on_assign_test_case: Callable[[str, Optional[int]], None],
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_files_added = on_files_added
        self.on_file_removed = on_file_removed
        self.on_reorder = on_reorder
        self.on_assign_test_case = on_assign_test_case

        self._items: List[ScreenshotInfo] = []
        self._test_case_labels: List[str] = []
        self._row_frames: List[ctk.CTkFrame] = []
        self._row_height_hint = DEFAULT_ROW_HEIGHT
        self._drag_start_idx: Optional[int] = None
        self._drag_current_idx: Optional[int] = None

        self.canvas = ctk.CTkCanvas(
            self,
            height=110,
            bg=theme.SURFACE_GREY,
            highlightthickness=0,
        )
        self.canvas.pack(fill="x", expand=False)
        self.canvas.bind("<Configure>", self._draw_dashed_border)
        self.canvas.bind("<Button-1>", lambda _e: self._browse())

        # Set after registration is attempted: importing tkinterdnd2 can
        # succeed while its native tkdnd library fails to load for this
        # platform/Tcl build, and promising drag-and-drop that silently does
        # nothing is worse than pointing at the Browse button.
        self._hint = "Click to browse screenshots"

        self.browse_btn = ctk.CTkButton(
            self.canvas, text="Browse Files", width=120, height=28,
            fg_color=theme.ACCENT_TECH_BLUE, hover_color=theme.ACCENT_TECH_BLUE_HOVER,
            command=self._browse,
        )

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", height=160)
        self.list_frame.pack(fill="both", expand=True, pady=(theme.PADDING_SM, 0))

        self.drag_and_drop_active = False
        if _DND_AVAILABLE:
            try:
                self.canvas.drop_target_register(DND_FILES)
                self.canvas.dnd_bind("<<Drop>>", self._on_drop)
                self.drag_and_drop_active = True
                self._hint = "Drag & drop screenshots here"
            except Exception as e:
                print(f"[Warning] Drag-and-drop unavailable, use Browse instead: {e}")
        self._draw_dashed_border()

    def _draw_dashed_border(self, _event=None):
        self.canvas.delete("all")
        w = max(self.canvas.winfo_width(), 10)
        h = max(self.canvas.winfo_height(), 10)
        margin = 4
        self.canvas.create_rectangle(
            margin, margin, w - margin, h - margin,
            dash=(6, 4), outline=theme.BORDER_MUTED, width=2,
        )
        self.canvas.create_text(
            w / 2, h * 0.35,
            text=self._hint,
            fill=theme.TEXT_SECONDARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
        )
        self.canvas.create_window(w / 2, h * 0.72, window=self.browse_btn, anchor="center")

    def _browse(self):
        paths = ctk.filedialog.askopenfilenames(
            title="Select Screenshots",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.webp *.gif")],
            # parent= keeps the sheet attached to our window on macOS, where
            # an unparented dialog can open behind the app.
            parent=self.winfo_toplevel(),
        )
        if paths:
            self.on_files_added(list(paths))

    def _on_drop(self, event):
        paths = _parse_dnd_paths(event.data)
        image_paths = [p for p in paths if p.lower().endswith(IMAGE_EXTENSIONS)]
        if image_paths:
            self.on_files_added(image_paths)

    # --- Screenshot list: assignment + drag reorder ------------------------

    def refresh(self, screenshots: List[ScreenshotInfo], test_case_labels: List[str]):
        self._items = list(screenshots)
        self._test_case_labels = list(test_case_labels)
        self._drag_start_idx = None
        self._drag_current_idx = None
        self._rebuild_rows()

    def _rebuild_rows(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._row_frames = []
        for idx, shot in enumerate(self._items):
            self._row_frames.append(self._build_row(idx, shot))

        self.list_frame.update_idletasks()
        if self._row_frames:
            height = self._row_frames[0].winfo_height()
            if height > 0:
                self._row_height_hint = height

    def _assignment_options(self) -> List[str]:
        return ["Auto"] + [f"Test Case {i + 1}" for i in range(len(self._test_case_labels))]

    def _build_row(self, idx: int, shot: ScreenshotInfo) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self.list_frame, fg_color=theme.SURFACE_GREY_LIGHT, corner_radius=6)
        row.pack(fill="x", pady=3, padx=2)

        handle = ctk.CTkLabel(
            row, text="⠿", text_color=theme.TEXT_SECONDARY, width=16,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
        )
        handle.pack(side="left", padx=(8, 0), pady=6)

        current = "Auto" if shot.test_case_index is None else f"Test Case {shot.test_case_index + 1}"
        assign_menu = ctk.CTkOptionMenu(
            row, values=self._assignment_options(), width=118, height=24,
            fg_color=theme.SURFACE_GREY, button_color=theme.ACCENT_TECH_BLUE,
            button_hover_color=theme.ACCENT_TECH_BLUE_HOVER,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL - 1),
            command=lambda choice, p=shot.file_path: self._on_assign_change(p, choice),
        )
        assign_menu.set(current)
        assign_menu.pack(side="left", padx=4, pady=4)

        remove_btn = ctk.CTkButton(
            row, text="✕", width=24, height=24, fg_color="transparent",
            hover_color=theme.SURFACE_GREY, text_color=theme.STATUS_ERROR,
            command=lambda p=shot.file_path: self.on_file_removed(p),
        )
        remove_btn.pack(side="right", padx=(4, 10), pady=4)

        filename = truncate_to_length(os.path.basename(shot.file_path), MAX_FILENAME_LENGTH)
        label = ctk.CTkLabel(
            row, text=filename, anchor="w",
            text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_INTERFACE_FAMILY, theme.FONT_SIZE_LABEL),
        )
        label.pack(side="left", fill="x", expand=True, padx=(6, 4), pady=6)

        for widget in (handle, row, label):
            widget.bind("<ButtonPress-1>", lambda e, i=idx: self._start_drag(i))
            widget.bind("<B1-Motion>", self._on_drag_motion)
            widget.bind("<ButtonRelease-1>", self._on_drag_release)

        return row

    def _on_assign_change(self, file_path: str, choice: str):
        if choice == "Auto":
            self.on_assign_test_case(file_path, None)
        else:
            index = int(choice.replace("Test Case ", "")) - 1
            self.on_assign_test_case(file_path, index)

    def _start_drag(self, idx: int):
        self._drag_start_idx = idx
        self._drag_current_idx = idx

    def _on_drag_motion(self, event):
        if self._drag_current_idx is None or not self._items:
            return
        rel_y = event.y_root - self.list_frame.winfo_rooty()
        row_height = max(self._row_height_hint, 1)
        target = int(rel_y // row_height)
        target = max(0, min(len(self._items) - 1, target))
        if target != self._drag_current_idx:
            item = self._items.pop(self._drag_current_idx)
            self._items.insert(target, item)
            self._drag_current_idx = target
            self._rebuild_rows()

    def _on_drag_release(self, _event):
        if self._drag_start_idx is not None:
            self.on_reorder([s.file_path for s in self._items])
        self._drag_start_idx = None
        self._drag_current_idx = None
