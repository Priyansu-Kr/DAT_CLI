"""Visual design tokens for the DAT Control Center GUI.

Rendering is pure Tk/Tkinter (via CustomTkinter) which is always software
rasterized on the CPU - no GPU/OpenGL is ever required, so this UI runs
unmodified inside headless VMs and remote desktops.
"""

# Colors
BG_DEEP_DARK = "#111315"
SURFACE_GREY = "#1e1e1e"
SURFACE_GREY_LIGHT = "#26282b"
ACCENT_TECH_BLUE = "#007bff"
ACCENT_TECH_BLUE_HOVER = "#3395ff"
BORDER_MUTED = "#33363a"
TEXT_PRIMARY = "#f5f6f7"
TEXT_SECONDARY = "#a7adb3"
TEXT_MUTED = "#7c848c"
STATUS_ERROR = "#ff5c5c"
STATUS_WARNING = "#f0a92c"

# Template builder surfaces
BG_HEADER = "#16181a"
SURFACE_CARD = "#1c1e21"
SURFACE_CARD_HOVER = "#2a2d31"

# Typography
# These are preferred defaults; resolve_fonts() swaps them for the closest
# match actually installed on the running system (Arial/Inter are seldom
# present on Linux out of the box, unlike Windows/macOS where they ship
# with the OS).
FONT_INTERFACE_FAMILY = "Inter"
FONT_DOCUMENT_FAMILY = "Arial"
FONT_MONO_FAMILY = "Courier New"

# Preference order per role, most-faithful match first. Tk never errors on
# an unknown family (it silently substitutes a system default), so this is
# purely about visual fidelity, not correctness/crash-safety.
DOCUMENT_FONT_PREFERENCE = ["Arial", "Liberation Sans", "Nimbus Sans", "DejaVu Sans", "Helvetica"]
INTERFACE_FONT_PREFERENCE = ["Inter", "Segoe UI", "Helvetica Neue", "SF Pro Text", "Arial", "DejaVu Sans"]
# Menlo is macOS-only, Consolas Windows-only, DejaVu Sans Mono the Linux
# default - first match wins, so one list covers every platform.
MONO_FONT_PREFERENCE = ["Menlo", "Consolas", "DejaVu Sans Mono", "Liberation Mono", "Courier New", "Courier"]

FONT_SIZE_LABEL = 13
FONT_SIZE_BODY = 13
FONT_SIZE_HEADING = 16
FONT_SIZE_DOC_TITLE = 24
FONT_SIZE_DOC_HEADING = 16
FONT_SIZE_DOC_BODY = 11

# Layout
LEFT_PANEL_WIDTH = 350
BUILDER_SIDEBAR_WIDTH = 262
PADDING_LG = 32
PADDING_MD = 24
PADDING_SM = 16

CORNER_RADIUS = 10


def resolve_fonts() -> None:
    """Pick the closest available font family for each role on this system.

    Must be called after a Tk root exists (e.g. first thing in
    DATGuiApp.__init__) since enumerating installed font families requires
    an active Tk interpreter. Safe to skip/fail silently - Tk always
    substitutes *something* for an unknown family name, it just won't be
    as close a visual match to Arial/Inter as a resolved fallback would be.
    """
    global FONT_DOCUMENT_FAMILY, FONT_INTERFACE_FAMILY, FONT_MONO_FAMILY
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families())
    except Exception:
        return

    for name in DOCUMENT_FONT_PREFERENCE:
        if name in available:
            FONT_DOCUMENT_FAMILY = name
            break

    for name in INTERFACE_FONT_PREFERENCE:
        if name in available:
            FONT_INTERFACE_FAMILY = name
            break

    for name in MONO_FONT_PREFERENCE:
        if name in available:
            FONT_MONO_FAMILY = name
            break



def document_font_tuple(size: int = FONT_SIZE_DOC_BODY, weight: str = "normal") -> tuple:
    return (FONT_DOCUMENT_FAMILY, size, weight)


def mono_font_tuple(size: int = FONT_SIZE_DOC_BODY, weight: str = "normal") -> tuple:
    return (FONT_MONO_FAMILY, size, weight)
