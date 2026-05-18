"""
CellStyle dataclass and color palette.

Style is stored as rendering metadata per-cell, separate from the
expression string.  Changing a style property never re-evaluates the
expression; it only updates the pygfx material.
"""

from __future__ import annotations
from dataclasses import dataclass, field

# Default color palette — cycles as cells are added (Desmos-style)
PALETTE: list[tuple[float, float, float, float]] = [
    (0.22, 0.40, 0.88, 1.0),   # Desmos blue
    (0.85, 0.22, 0.22, 1.0),   # red
    (0.20, 0.70, 0.30, 1.0),   # green
    (0.85, 0.55, 0.05, 1.0),   # orange
    (0.60, 0.20, 0.80, 1.0),   # purple
    (0.10, 0.65, 0.75, 1.0),   # teal
    (0.90, 0.30, 0.65, 1.0),   # pink
    (0.50, 0.35, 0.20, 1.0),   # brown
]


def palette_color(index: int) -> tuple[float, float, float, float]:
    return PALETTE[index % len(PALETTE)]


@dataclass
class CellStyle:
    color: tuple[float, float, float, float] = (0.22, 0.40, 0.88, 1.0)
    opacity: float = 1.0
    line_width: float = 0.05   # world units (~2–3 px at default view distance)
    point_size: float = 0.1    # world units (~5 px at default view distance)
    line_style: str = "solid"         # "solid" | "dashed" | "dotted"
    display_mode: str = "filled"      # "filled" | "wireframe" | "both"
    show_label: bool = True
    scatter_as_line: bool = False     # render (N,2)/(N,3) arrays as connected line

    def color_hex(self) -> str:
        r, g, b, _ = self.color
        return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

    def color_qss(self) -> str:
        """Return a CSS background-color string for use in Qt stylesheets."""
        r, g, b, _ = self.color
        return f"rgb({int(r*255)},{int(g*255)},{int(b*255)})"
