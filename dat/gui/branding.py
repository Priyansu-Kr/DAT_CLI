"""Window, taskbar and dock branding for DAT's Tk windows.

Three OSes take the icon three different ways:

* **Linux** window managers read `_NET_WM_ICON`, which is what Tk's
  `wm iconphoto` sets - so the taskbar picks it up from the running process
  with no desktop-entry file involved.
* **Windows** shows the taskbar icon from the window class; Tk's
  `iconbitmap(default=...)` with a real multi-size `.ico` is what gets the
  small sizes crisp, since Windows selects a size from inside the file
  instead of resampling one image.
* **macOS** ignores `wm iconphoto` for the dock entirely: the dock icon
  belongs to the *application bundle* that owns the process, which for a
  pip-installed CLI is the Python framework's own `Python.app` - hence the
  rocket. Setting `NSApplication.applicationIconImage` replaces it at
  runtime, so DAT does that when PyObjC happens to be importable, and
  otherwise leaves the rocket alone. PyObjC is deliberately not a
  dependency: it is a large macOS-only build, and a wrong dock icon is a
  cosmetic issue, not a broken tool.

Everything here is best-effort by design. An icon that cannot be loaded -
missing asset, no Pillow/ImageTk, a Tk build that refuses the call - must
never be the reason the GUI fails to open, so every path is guarded and
falls back to the un-branded window.
"""
import os
import sys
import tkinter as tk
from typing import List, Optional

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
ASSETS_DIR = os.path.normpath(ASSETS_DIR)

WORDMARK_PATH = os.path.join(ASSETS_DIR, "dat_wordmark.png")
ICON_PATH = os.path.join(ASSETS_DIR, "dat_icon.png")
ICON_ICO_PATH = os.path.join(ASSETS_DIR, "dat_icon.ico")

# Sizes a window manager actually asks for: taskbar/titlebar at the small
# end, alt-tab and window-switcher previews at the large end. Tk hands the
# WM every size it is given and lets it choose.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

# Tk drops an image the moment the last Python reference to it goes away,
# and an icon dropped mid-session leaves a blank taskbar entry - so these
# outlive the call that created them.
_icon_photos: List[tk.PhotoImage] = []
_wordmark_cache = {}
_dock_icon_done = False


def _load_icon_photos(window) -> List[tk.PhotoImage]:
    """One Tk image per icon size, or a single native-read PNG as fallback."""
    global _icon_photos
    if _icon_photos:
        return _icon_photos

    if not os.path.isfile(ICON_PATH):
        return []

    try:
        from PIL import Image, ImageTk

        master = Image.open(ICON_PATH)
        photos = []
        for size in ICON_SIZES:
            resized = master.resize((size, size), Image.LANCZOS)
            photos.append(ImageTk.PhotoImage(resized, master=window))
        _icon_photos = photos
        return _icon_photos
    except Exception:
        # No Pillow, or no ImageTk bridge (Debian splits it into
        # python3-pil.imagetk). Tk 8.6 reads PNG by itself, so a single
        # 256px image still brands the window - the WM scales it down.
        try:
            _icon_photos = [tk.PhotoImage(file=ICON_PATH, master=window)]
        except tk.TclError:
            _icon_photos = []
        return _icon_photos


def apply(window) -> None:
    """Brand `window` and, where the OS allows it, the whole application."""
    photos = _load_icon_photos(window)
    if photos:
        try:
            # default=True so Toplevels opened later (the Template Builder)
            # inherit the icon instead of each having to ask for it.
            window.iconphoto(True, *photos)
        except tk.TclError:
            pass

    if os.name == "nt" and os.path.isfile(ICON_ICO_PATH):
        try:
            window.iconbitmap(default=ICON_ICO_PATH)
        except tk.TclError:
            pass

    if sys.platform == "darwin":
        _apply_macos_dock_icon()


def _apply_macos_dock_icon() -> bool:
    """Replace the Python rocket in the dock, if PyObjC is available."""
    global _dock_icon_done
    if _dock_icon_done or not os.path.isfile(ICON_PATH):
        return _dock_icon_done

    try:
        from AppKit import NSApplication, NSImage  # PyObjC: optional, macOS only
    except Exception:
        return False

    try:
        image = NSImage.alloc().initWithContentsOfFile_(ICON_PATH)
        if image is None:
            return False
        NSApplication.sharedApplication().setApplicationIconImage_(image)
    except Exception:
        return False

    _dock_icon_done = True
    return True


def wordmark_image(height: int = 24):
    """The wordmark as a CTkImage sized to `height`, or None if unavailable.

    This is the backdrop-free wordmark, so it sits on the panel surface
    rather than pasting the artwork's own coloured rectangle onto it. It is
    a different asset from the taskbar icon on purpose: the full name is
    legible at 22px in a panel and illegible at 16px in a taskbar.
    """
    if height in _wordmark_cache:
        return _wordmark_cache[height]

    path = WORDMARK_PATH
    if not os.path.isfile(path):
        return None

    try:
        import customtkinter as ctk
        from PIL import Image
    except ImportError:
        return None

    try:
        image = Image.open(path)
        width = max(1, round(image.width * (height / image.height)))
        # CTkImage rather than a plain PhotoImage: it re-renders from the
        # source at the display's scaling factor, so the mark stays sharp on
        # a HiDPI screen instead of being a scaled-up bitmap.
        ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=(width, height))
    except Exception:
        return None

    _wordmark_cache[height] = ctk_image
    return ctk_image