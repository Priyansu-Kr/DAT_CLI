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
STATUS_SUCCESS = "#2ecc71"
STATUS_ERROR = "#ff5c5c"

# Typography
FONT_INTERFACE_FAMILY = "Inter"
FONT_INTERFACE_FALLBACK = "Segoe UI"
FONT_DOCUMENT_FAMILY = "Arial"

FONT_SIZE_LABEL = 13
FONT_SIZE_BODY = 13
FONT_SIZE_HEADING = 16
FONT_SIZE_DOC_TITLE = 24
FONT_SIZE_DOC_HEADING = 16
FONT_SIZE_DOC_BODY = 11

# Layout
LEFT_PANEL_WIDTH = 350
PADDING_LG = 32
PADDING_MD = 24
PADDING_SM = 16
TABLE_ROW_HEIGHT = 30

CORNER_RADIUS = 10


def interface_font_tuple(size: int = FONT_SIZE_BODY, weight: str = "normal") -> tuple:
    return (FONT_INTERFACE_FAMILY, size, weight)


def document_font_tuple(size: int = FONT_SIZE_DOC_BODY, weight: str = "normal") -> tuple:
    return (FONT_DOCUMENT_FAMILY, size, weight)
