"""
Qt application shell for Pringle.

Creates the top-level QMainWindow with:
  - Left panel: CellListWidget (equation cells, live evaluation)
               + ViewSettingsWidget (axis bounds, camera presets)
  - Right panel: QRenderWidget embedding the pygfx canvas
  - Horizontal QSplitter between left and right
"""

from __future__ import annotations

import sys
import numpy as np

import PyQt6  # must be imported before rendercanvas.qt  # noqa: F401
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QLabel, QFrame, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from rendercanvas.qt import QRenderWidget

import pygfx as gfx
from pringle.renderer import PringleRenderer, make_surface_mesh, make_line_mesh, make_scatter_mesh
from pringle.grid import GridConfig, Grid, make_grid
from pringle.evaluator import run_cell, CellResult
from pringle.style import CellStyle
from pringle.cell_list import CellListWidget
from pringle.view_settings import ViewSettingsWidget


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
        # Register the render callback so request_draw() actually calls render.
        # Without this, request_draw() with no argument is a no-op because
        # _draw_frame is never set.
        self.request_draw(self._pr.render)
        self._draw_timer = QTimer(self)
        self._draw_timer.setInterval(16)  # ~60fps cap
        self._draw_timer.timeout.connect(self.request_draw)
        self._draw_timer.start()

    @property
    def renderer(self) -> PringleRenderer:
        return self._pr

    def add_object(self, cell_id: str, obj: gfx.WorldObject) -> None:
        is_new = self._pr.add_object(cell_id, obj)
        if is_new:
            self._pr.fit_camera()

    def remove_object(self, cell_id: str) -> None:
        self._pr.remove_object(cell_id)

    def set_visible(self, cell_id: str, visible: bool) -> None:
        self._pr.set_visible(cell_id, visible)

    def set_camera_preset(self, name: str) -> None:
        """Position the camera at a standard viewpoint."""
        cam = self._pr._camera
        positions = {
            "iso":   (6, -8, 6),
            "top":   (0, 0, 12),
            "front": (0, -12, 0),
        }
        if name in positions:
            cam.local.position = positions[name]
            cam.look_at((0, 0, 0))


class PringleWindow(QMainWindow):
    """
    Top-level application window.

    Layout:
        QSplitter (horizontal)
          ├── Left panel (QWidget)
          │     ├── CellListWidget   (equation cells, live evaluation)
          │     └── ViewSettingsWidget (axis bounds, camera presets)
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

        # 3D viewport
        self._viewport = PringleViewport(splitter)

        # Left panel: cell list + view settings stacked vertically
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self._cell_list = CellListWidget(
            on_cell_result=self._on_cell_result,
            grid=self._grid,
        )
        left_layout.addWidget(self._cell_list, 1)

        self._view_settings = ViewSettingsWidget(config=self._grid.config)
        self._view_settings.bounds_changed.connect(self._on_bounds_changed)
        self._view_settings.resolution_changed.connect(self._on_resolution_changed)
        self._view_settings.camera_preset_requested.connect(self._viewport.set_camera_preset)
        self._view_settings.fit_all_requested.connect(self._viewport.renderer.fit_camera)
        left_layout.addWidget(self._view_settings)

        splitter.insertWidget(0, left)
        splitter.addWidget(self._viewport)

        # Initial split proportions
        splitter.setSizes([self.LEFT_PANEL_WIDTH, self.DEFAULT_SIZE[0] - self.LEFT_PANEL_WIDTH])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self._splitter = splitter

        # Session state
        self._session_path: str | None = None
        self._modified = False

        self._setup_shortcuts()

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def _setup_shortcuts(self) -> None:
        for keys, slot in [
            (QKeySequence.StandardKey.New,    self._on_new),
            (QKeySequence.StandardKey.Open,   self._on_open),
            (QKeySequence.StandardKey.Save,   self._on_save),
            (QKeySequence("Ctrl+Shift+S"),    self._on_save_as),
            (QKeySequence.StandardKey.Undo,   self._on_undo),
            (QKeySequence.StandardKey.Redo,   self._on_redo),
            (QKeySequence.StandardKey.Copy,   self._on_copy),
            (QKeySequence.StandardKey.Paste,  self._on_paste),
        ]:
            sc = QShortcut(keys, self)
            sc.activated.connect(slot)

    def _mark_modified(self) -> None:
        if not self._modified:
            self._modified = True
            self._update_title()

    def _update_title(self) -> None:
        name = (
            self._session_path.rsplit("/", 1)[-1]
            if self._session_path else "untitled"
        )
        prefix = "* " if self._modified else ""
        self.setWindowTitle(f"{prefix}pringle — {name}")

    def _confirm_discard(self) -> bool:
        """Return True if it's safe to discard the current session."""
        if not self._modified:
            return True
        btn = QMessageBox.question(
            self, "Unsaved changes",
            "You have unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return btn == QMessageBox.StandardButton.Discard

    def _on_new(self) -> None:
        if not self._confirm_discard():
            return
        for cell in list(self._cell_list._cells):
            self._cell_list.remove_cell(cell.cell_id)
        self._session_path = None
        self._modified = False
        self._update_title()

    def _on_open(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open session", "", "Pringle session (*.pringle);;YAML (*.yaml *.yml)"
        )
        if not path:
            return
        from pringle.session import load_session, restore_cell_list
        try:
            data = load_session(path)
        except Exception as exc:
            QMessageBox.critical(self, "Load error", str(exc))
            return
        restore_cell_list(self._cell_list, data.get("cells", []))
        if data.get("grid"):
            from pringle.session import grid_config_from_dict
            cfg = grid_config_from_dict(data["grid"])
            self._grid = make_grid(cfg)
            self._cell_list.update_grid(self._grid)
        self._session_path = path
        self._modified = False
        self._update_title()

    def _on_save(self) -> None:
        if self._session_path:
            self._write_session(self._session_path)
        else:
            self._on_save_as()

    def _on_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save session", "", "Pringle session (*.pringle);;YAML (*.yaml *.yml)"
        )
        if path:
            self._write_session(path)

    def _on_undo(self) -> None:
        from PyQt6.QtWidgets import QPlainTextEdit, QLineEdit
        fw = QApplication.focusWidget()
        if isinstance(fw, (QPlainTextEdit, QLineEdit)):
            fw.undo()
        else:
            self._cell_list.undo()

    def _on_redo(self) -> None:
        from PyQt6.QtWidgets import QPlainTextEdit, QLineEdit
        fw = QApplication.focusWidget()
        if isinstance(fw, (QPlainTextEdit, QLineEdit)):
            fw.redo()
        else:
            self._cell_list.redo()

    def _on_copy(self) -> None:
        from PyQt6.QtWidgets import QPlainTextEdit, QLineEdit
        fw = QApplication.focusWidget()
        if isinstance(fw, (QPlainTextEdit, QLineEdit)):
            fw.copy()
        else:
            self._cell_list.copy_focused_cell()

    def _on_paste(self) -> None:
        from PyQt6.QtWidgets import QPlainTextEdit, QLineEdit
        fw = QApplication.focusWidget()
        if isinstance(fw, (QPlainTextEdit, QLineEdit)):
            fw.paste()
        else:
            self._cell_list.paste_cell()

    def _write_session(self, path: str) -> None:
        from pringle.session import save_session
        try:
            save_session(path, self._cell_list, self._grid.config)
        except Exception as exc:
            QMessageBox.critical(self, "Save error", str(exc))
            return
        self._session_path = path
        self._modified = False
        self._update_title()

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
            mesh = make_surface_mesh(
                result.x, result.y, result.data, color=style.color,
                constraint_mask=result.constraint_mask,
                z_raw=result.data_unmasked,
            )
            vp.add_object(cell_id, mesh)

        elif result.render_type == "surface_y":
            # y = f(x,y) assigned a 2D array — render as a height surface
            mesh = make_surface_mesh(
                self._grid.x, self._grid.y, result.data, color=style.color
            )
            vp.add_object(cell_id, mesh)

        elif result.render_type == "curve":
            pts = np.column_stack([
                self._grid.x1d,
                result.data,
                np.zeros(len(result.data), dtype=np.float32),
            ])
            line = make_line_mesh(pts, color=style.color, thickness=style.line_width)
            vp.add_object(cell_id, line)

        elif result.render_type == "curve_x":
            pts = np.column_stack([
                result.data,
                self._grid.y1d,
                np.zeros(len(result.data), dtype=np.float32),
            ])
            line = make_line_mesh(pts, color=style.color, thickness=style.line_width)
            vp.add_object(cell_id, line)

        elif result.render_type == "parametric":
            pts = np.asarray(result.data, dtype=np.float32)
            if pts.ndim == 2 and pts.shape[1] in (2, 3):
                scatter = make_scatter_mesh(pts, color=style.color, size=style.point_size)
                vp.add_object(cell_id, scatter)
            else:
                vp.remove_object(cell_id)

        elif result.render_type in ("scatter", "scatter_2d"):
            scatter = make_scatter_mesh(result.data, color=style.color, size=style.point_size)
            vp.add_object(cell_id, scatter)

        else:
            # No renderable output (comment, slider, error, or hidden) — clear
            vp.remove_object(cell_id)

    # ------------------------------------------------------------------
    # View settings handlers
    # ------------------------------------------------------------------

    def _on_bounds_changed(self, x_min: float, x_max: float, y_min: float, y_max: float) -> None:
        config = GridConfig(
            x_min=x_min, x_max=x_max,
            y_min=y_min, y_max=y_max,
            n=self._grid.config.n,
        )
        self._grid = make_grid(config)
        self._cell_list.update_grid(self._grid)

    def _on_resolution_changed(self, n: int) -> None:
        config = GridConfig(
            x_min=self._grid.config.x_min, x_max=self._grid.config.x_max,
            y_min=self._grid.config.y_min, y_max=self._grid.config.y_max,
            n=n,
        )
        self._grid = make_grid(config)
        self._cell_list.update_grid(self._grid)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def viewport(self) -> PringleViewport:
        return self._viewport

    @property
    def cell_list(self) -> CellListWidget:
        return self._cell_list

    @property
    def view_settings(self) -> ViewSettingsWidget:
        return self._view_settings


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
