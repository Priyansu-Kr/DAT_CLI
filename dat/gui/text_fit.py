"""Fitting long text into a fixed space.

Two flavours, both returning text ending in an ellipsis when they had to
cut something:

* :func:`truncate_to_width` measures in pixels, for labels that must not
  push a neighbouring widget out of the way.
* :func:`truncate_to_length` counts characters, for compact list rows where
  a rough cap is enough.

Measurement is injected, so the pixel logic is unit-testable without Tk.
"""
from typing import Callable

ELLIPSIS = "…"


def truncate_to_width(
    text: str,
    measure: Callable[[str], int],
    max_width: int,
    ellipsis: str = ELLIPSIS,
) -> str:
    """Longest prefix of ``text`` that renders within ``max_width`` pixels.

    ``measure`` returns the rendered width of a string (Tk's
    ``font.measure``). Returns ``text`` unchanged when it already fits.
    """
    if not text:
        return ""
    if max_width <= 0:
        return text
    if measure(text) <= max_width:
        return text
    if measure(ellipsis) > max_width:
        # Not even the ellipsis fits; nothing sensible to show.
        return ""

    # Binary search the longest prefix that still fits with the ellipsis.
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if measure(text[:middle].rstrip() + ellipsis) <= max_width:
            low = middle
        else:
            high = middle - 1

    return text[:low].rstrip() + ellipsis if low else ellipsis


def truncate_to_length(text: str, limit: int, ellipsis: str = ELLIPSIS) -> str:
    """Cap ``text`` at ``limit`` characters, ellipsis included."""
    text = (text or "").strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(ellipsis):
        return ellipsis[:limit]
    return text[: limit - len(ellipsis)].rstrip() + ellipsis
