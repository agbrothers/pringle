"""
Qt application shell for Pringle.

Creates the top-level QMainWindow with:
  - Left panel: CellListWidget (equation cells, live evaluation)
  - Right panel: QRenderWidget embedding the pygfx canvas
  - Horizontal QSplitter between left and right
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
from pringle.renderer import PringleRenderer, make_surface_mesh, make_line_mesh, make_scatter_mesh
from pringle.grid import GridConfig, Grid, make_grid
from pringle.evaluator import run_cell, CellResult
from pringle.style import CellStyle
from pringle.cell_list import CellListWidget


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


class PringleWindow(QMainWindow):
    """
    Top-level application window.

    Layout:
        QSplitter (horizontal)
          ├── CellListWidget   (expression cells, live evaluation)
          └── PringleViewport  (3D GPU canvas)
    """

    DEFAULT_SIZE = (1400, 900)
    LEFT_PANEL_WIDTH = 340

    def __init__(self, grid: Grid | None = None):
        super().__init__()
        self.setWindowTitle("pringle")
        self.resize(*self.DEFAULT_SIZE)
        self._grid = grid or make_grid()

        # Central splitter
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.setCentralWidget(splitter)

        # 3D viewport (created first so on_cell_result can reference it)
        self._viewport = PringleViewport(splitter)

        # Cell list — wired to viewport via on_cell_result callback
        self._cell_list = CellListWidget(
            on_cell_result=self._on_cell_result,
            grid=self._grid,
            parent=splitter,
        )

        splitter.insertWidget(0, self._cell_list)
        splitter.addWidget(self._viewport)

        # Initial split proportions
        splitter.setSizes([self.LEFT_PANEL_WIDTH, self.DEFAULT_SIZE[0] - self.LEFT_PANEL_WIDTH])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self._splitter = splitter

    # ------------------------------------------------------------------
    # Viewport update callback
    # ------------------------------------------------------------------

    def _on_cell_result(self, cell_id: str, result: CellResult, style: CellStyle) -> None:
        """
        Called by CellListWidget after each cell evaluation.
        Updates or removes the corresponding object in the 3D scene.
        """
        vp = self._viewport

        if result.render_type == "surface":
            mesh = make_surface_mesh(result.x, result.y, result.data, color=style.color)
            vp.add_object(cell_id, mesh)

        elif result.render_type == "curve":
            pts = np.column_stack([
                self._grid.x1d,
                result.data,
                np.zeros(len(result.data), dtype=np.float32),
            ])
            line = make_line_mesh(pts, color=style.color, thickness=style.line_width)
            vp.add_object(cell_id, line)

        elif result.render_type in ("scatter", "scatter_2d"):
            scatter = make_scatter_mesh(result.data, color=style.color, size=style.point_size)
            vp.add_object(cell_id, scatter)

        else:
            # No renderable output (comment, slider, error, or hidden) — clear
            vp.remove_object(cell_id)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def viewport(self) -> PringleViewport:
        return self._viewport

    @property
    def cell_list(self) -> CellListWidget:
        return self._cell_list


def launch(argv=None) -> int:
    """Start the Pringle Qt application. Returns exit code."""
    app = QApplication(argv or sys.argv)
    app.setApplicationName("pringle")

    win = PringleWindow(grid=make_grid(GridConfig(n=64)))
    win.show()

    # Seed the session with a demo cell
    win.cell_list.add_cell("z = sin(x) * cos(y)")

    return app.exec()


if __name__ == "__main__":
    sys.exit(launch())
