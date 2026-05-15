"""
Qt application shell for Pringle.

Creates the top-level QMainWindow with:
  - Left panel (expression + data cells) — placeholder QWidget for now
  - Right panel: QRenderWidget embedding the pygfx canvas
  - Horizontal QSplitter between left and right

This is Phase 3: proves that the Qt event loop and the wgpu rendering
loop coexist correctly, and that mouse orbit works inside the Qt widget.
"""

from __future__ import annotations

import sys
import numpy as np

import PyQt6  # must be imported before rendercanvas.qt  # noqa: F401
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QLabel, QFrame,
)
from PyQt6.QtCore import Qt, QTimer
from rendercanvas.qt import QRenderWidget

import pygfx as gfx
from pringle.renderer import PringleRenderer, make_surface_mesh
from pringle.grid import GridConfig, make_grid
from pringle.evaluator import run_cell


class PringleViewport(QRenderWidget):
    """
    The 3D GPU viewport — a QWidget that owns its own pygfx renderer.

    Embeds PringleRenderer (scene + camera + orbit controller) into the
    Qt widget tree.  The wgpu render loop fires on request_draw() which
    QRenderWidget triggers automatically on resize and on explicit calls.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pr = PringleRenderer(self)
        self._draw_timer = QTimer(self)
        self._draw_timer.setInterval(16)  # ~60fps cap
        self._draw_timer.timeout.connect(self.request_draw)
        self._draw_timer.start()

    @property
    def renderer(self) -> PringleRenderer:
        return self._pr

    def add_object(self, cell_id: str, obj: gfx.WorldObject) -> None:
        self._pr.add_object(cell_id, obj)
        self._pr.fit_camera()

    def remove_object(self, cell_id: str) -> None:
        self._pr.remove_object(cell_id)

    def set_visible(self, cell_id: str, visible: bool) -> None:
        self._pr.set_visible(cell_id, visible)


class LeftPanelPlaceholder(QFrame):
    """
    Temporary placeholder for the expression/data panel.
    Replaced in Phase 4 with real cell widgets.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        label = QLabel("Expression Panel\n(Phase 4)")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #888; font-size: 14px;")
        layout.addWidget(label)
        layout.addStretch()


class PringleWindow(QMainWindow):
    """
    Top-level application window.

    Layout:
        QSplitter (horizontal)
          ├── LeftPanelPlaceholder   (expression + data cells)
          └── PringleViewport        (3D GPU canvas)
    """

    DEFAULT_SIZE = (1400, 900)
    LEFT_PANEL_WIDTH = 320

    def __init__(self):
        super().__init__()
        self.setWindowTitle("pringle")
        self.resize(*self.DEFAULT_SIZE)

        # Central splitter
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.setCentralWidget(splitter)

        # Left panel
        self._left_panel = LeftPanelPlaceholder(splitter)
        splitter.addWidget(self._left_panel)

        # 3D viewport
        self._viewport = PringleViewport(splitter)
        splitter.addWidget(self._viewport)

        # Initial split proportions
        splitter.setSizes([self.LEFT_PANEL_WIDTH, self.DEFAULT_SIZE[0] - self.LEFT_PANEL_WIDTH])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self._splitter = splitter

    @property
    def viewport(self) -> PringleViewport:
        return self._viewport


def launch(argv=None) -> int:
    """Start the Pringle Qt application. Returns exit code."""
    app = QApplication(argv or sys.argv)
    app.setApplicationName("pringle")

    win = PringleWindow()
    win.show()

    # Demo: load a sin(x)*cos(y) surface via the evaluator
    grid = make_grid(GridConfig(n=64))
    result = run_cell("z = sin(x) * cos(y)", {}, grid)
    if result.render_type == "surface":
        mesh = make_surface_mesh(result.x, result.y, result.data)
        win.viewport.add_object("demo-surface", mesh)

    return app.exec()


if __name__ == "__main__":
    sys.exit(launch())
