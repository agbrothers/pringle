"""
Qt application shell for Pringle.

Creates the top-level QMainWindow with:
  - Left panel: CellListWidget (equation + data cells in one unified list)
               + ViewSettingsWidget (axis bounds, camera presets)
  - Right panel: QRenderWidget embedding the pygfx canvas
  - Horizontal QSplitter between left and right
"""

from __future__ import annotations

import os
import sys
import time as _time
import numpy as np

import PyQt6  # must be imported before rendercanvas.qt  # noqa: F401
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QLabel, QFrame, QFileDialog, QMessageBox,
    QPushButton,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut, QKeyEvent
from pathlib import Path

_ICON_PATH = Path(__file__).parent / "assets" / "icon.png"
from rendercanvas.qt import QRenderWidget
from pringle.header_bar import PringleHeaderBar

import pygfx as gfx
from pringle.renderer import (
    PringleRenderer, make_line_mesh, make_scatter_mesh, make_parametric_surface_mesh,
    _apply_colormap,
)
from pringle.grid import GridConfig, Grid, make_grid
from pringle.evaluator import run_cell, CellResult
from pringle.style import CellStyle
from pringle.cell_list import CellListWidget
from pringle.view_settings import ViewSettingsWidget


# WASD + arrow keys + Space/Shift mapped to world-space (dx, dy, dz) unit vectors
_PAN_KEYS: dict[int, tuple[float, float, float]] = {
    Qt.Key.Key_W:     ( 0,  1,  0),
    Qt.Key.Key_S:     ( 0, -1,  0),
    Qt.Key.Key_A:     (-1,  0,  0),
    Qt.Key.Key_D:     ( 1,  0,  0),
    Qt.Key.Key_Up:    ( 0,  1,  0),
    Qt.Key.Key_Down:  ( 0, -1,  0),
    Qt.Key.Key_Left:  (-1,  0,  0),
    Qt.Key.Key_Right: ( 1,  0,  0),
    Qt.Key.Key_Space: ( 0,  0,  1),
    Qt.Key.Key_Shift: ( 0,  0, -1),
}
_PAN_SPEED = 0.007  # fraction of camera-to-target distance per frame at 60 fps

_COAST_DECAY = 1.0    # angular velocity fraction retained per second (1.0 = no decay)
_COAST_STOP  = 0.005  # stop threshold in rad/s (either component)
_COAST_EL_SNAP = 0.15 # elevation snap threshold in rad/s — snaps to 0 for clean in-plane spin


class PringleViewport(QRenderWidget):
    """
    The 3D GPU viewport — a QWidget that owns its own pygfx renderer.

    Keyboard handling is done at the Qt level (keyPressEvent / keyReleaseEvent)
    so that event.accept() suppresses the macOS press-and-hold accent popover.
    Held keys are applied each timer tick for smooth, continuous panning.
    """

    # How many frames between each printed timing report.
    _FRAME_REPORT_INTERVAL = 60

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pr = PringleRenderer(self)
        self._held_keys: set[int] = set()
        self._seen_cell_ids: set[str] = set()

        # Frame timing: set PRINGLE_FRAME_TIMING=1 to enable.
        # Wraps the render callback to record wall-clock time per frame.
        # Prints mean / P95 / fps to stderr every _FRAME_REPORT_INTERVAL frames.
        # Subtract CPU-only benchmark times to estimate GPU contribution.
        self._frame_times: list[float] = []
        if os.environ.get("PRINGLE_FRAME_TIMING"):
            self.request_draw(self._timed_render)
        else:
            self.request_draw(self._pr.render)

        self._last_tick_time: float = _time.perf_counter()
        self._draw_timer = QTimer(self)
        self._draw_timer.setInterval(16)  # ~60fps
        self._draw_timer.timeout.connect(self._tick)
        self._draw_timer.start()

    def _tick(self) -> None:
        # Skip render while a modal dialog (e.g. QColorDialog) holds the event loop —
        # mutating the wgpu scene graph concurrently with a draw causes use-after-free crashes.
        if QApplication.activeModalWidget() is not None:
            return
        now = _time.perf_counter()
        dt = now - self._last_tick_time
        self._last_tick_time = now
        if self._held_keys:
            self._apply_movement()
        self._apply_coast(dt)
        self.request_draw()

    def _apply_coast(self, dt: float) -> None:
        handler = self._pr._orbit_handler
        vel = handler._coast_velocity
        if vel is None:
            return
        if abs(vel[0]) < _COAST_STOP and abs(vel[1]) < _COAST_STOP:
            handler._coast_velocity = None
            return
        # Snap elevation to zero when it's small relative to azimuth, so a
        # nearly-horizontal flick coasts in a clean horizontal circle.
        el = 0.0 if abs(vel[1]) < _COAST_EL_SNAP else vel[1]
        handler._coast_velocity = (
            vel[0] * _COAST_DECAY ** dt,
            el    * _COAST_DECAY ** dt,
        )
        self._pr._controller.rotate((vel[0] * dt, el * dt), handler._rect())

    def _timed_render(self) -> None:
        t0 = _time.perf_counter()
        self._pr.render()
        ms = (_time.perf_counter() - t0) * 1000
        self._frame_times.append(ms)
        n = len(self._frame_times)
        if n % self._FRAME_REPORT_INTERVAL == 0:
            window = np.array(self._frame_times[-self._FRAME_REPORT_INTERVAL:])
            mean_ms = window.mean()
            p95_ms  = np.percentile(window, 95)
            fps     = 1000.0 / mean_ms if mean_ms > 0 else float("inf")
            print(
                f"[frame] frames={n:5d}  "
                f"mean={mean_ms:6.1f}ms  p95={p95_ms:6.1f}ms  fps≈{fps:4.0f}",
                file=sys.stderr, flush=True,
            )

    def _apply_movement(self) -> None:
        cam = np.array(self._pr._camera.local.position, dtype=np.float64)
        tgt = np.array(self._pr._controller.target,     dtype=np.float64)
        dist = float(np.linalg.norm(cam - tgt))
        step = max(dist * _PAN_SPEED, 0.005)

        # Horizontal forward = camera-to-target projected onto XY, normalized.
        # Used to rotate WASD key-space directions into world space so that W
        # always moves toward the scene regardless of camera azimuth.
        fwd_xy = tgt[:2] - cam[:2]
        mag = float(np.linalg.norm(fwd_xy))
        fx, fy = (fwd_xy / mag) if mag > 1e-6 else (0.0, 1.0)

        for key in self._held_keys:
            if key not in _PAN_KEYS:
                continue
            dx_k, dy_k, dz = _PAN_KEYS[key]
            # Rotate key-space XY into world XY.
            # Basis: forward=(fx,fy), right=rotate(fwd,-90°)=(fy,-fx).
            # (dx_k,dy_k) → dx=dx_k*fy+dy_k*fx, dy=-dx_k*fx+dy_k*fy
            # Space/Shift: dx_k=dy_k=0 → (0,0), dz unchanged.
            dx = dx_k * fy + dy_k * fx
            dy = -dx_k * fx + dy_k * fy
            self._pr._pan_target(dx * step, dy * step, dz * step)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not event.isAutoRepeat() and event.key() in _PAN_KEYS:
            self._held_keys.add(event.key())
            event.accept()  # suppress macOS press-and-hold accent popover
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not event.isAutoRepeat() and event.key() in _PAN_KEYS:
            self._held_keys.discard(event.key())
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        self._held_keys.clear()  # avoid stuck keys when focus leaves the viewport
        super().focusOutEvent(event)

    @property
    def renderer(self) -> PringleRenderer:
        return self._pr

    def add_object(self, cell_id: str, obj: gfx.WorldObject) -> None:
        self._pr.add_object(cell_id, obj)
        if cell_id not in self._seen_cell_ids:
            self._seen_cell_ids.add(cell_id)
            self._pr.fit_camera()

    def update_surface(
        self, cell_id: str,
        x, y, z, color, opacity,
        constraint_mask, constraint_values, z_raw,
        colormap, colormap_reversed,
    ) -> None:
        is_new = self._pr.update_surface(
            cell_id, x, y, z, color, opacity,
            constraint_mask, constraint_values, z_raw,
            colormap, colormap_reversed,
        )
        if is_new and cell_id not in self._seen_cell_ids:
            self._seen_cell_ids.add(cell_id)
            self._pr.fit_camera()

    def update_arrows(
        self, cell_id: str,
        arrows, color, opacity, normalize=False, size=0.1,
        colormap=None, colormap_reversed=False, vertex_colors=None,
    ) -> None:
        is_new = self._pr.update_arrows(cell_id, arrows, color, opacity, normalize, size,
                                        colormap=colormap, colormap_reversed=colormap_reversed,
                                        vertex_colors=vertex_colors)
        if is_new and cell_id not in self._seen_cell_ids:
            self._seen_cell_ids.add(cell_id)
            self._pr.fit_camera()

    def remove_object(self, cell_id: str) -> None:
        self._pr.remove_object(cell_id)

    def forget_cell(self, cell_id: str) -> None:
        """Remove cell_id from the seen-set so the next render for that id re-fits."""
        self._seen_cell_ids.discard(cell_id)

    def set_visible(self, cell_id: str, visible: bool) -> None:
        self._pr.set_visible(cell_id, visible)

    def set_camera_preset(self, name: str) -> None:
        """Position the camera at a standard viewpoint."""
        cam = self._pr._camera
        positions = {
            "iso":   (6, -8, 6),
            # Slight X offset on top view avoids the controller singularity that
            # occurs when the view direction is exactly parallel to world-Z and
            # the cross product used to compute the orbit axis goes to zero.
            "top":   (0.001, 0, 12),
            "front": (0, -12, 0),
        }
        if name in positions:
            cam.local.position = positions[name]
            cam.look_at((0, 0, 0))
            # Re-sync the orbit controller's internal state so that subsequent
            # orbit operations start from the new camera position rather than
            # from wherever the controller's cached spherical coords last left it.
            self._pr._controller.target = (0.0, 0.0, 0.0)


class _ViewportContainer(QWidget):
    """Wraps PringleViewport with no overlay buttons (settings moved to header bar)."""

    def __init__(self, viewport: PringleViewport, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(viewport)


class AxisSettingsPopover(QFrame):
    """
    Frameless floating panel for axis / view settings.

    Same visual language as StylePopoverWidget and SliderControlsPopover:
    dark background, single-pixel border, no title bar, stays open until
    the wrench button is toggled off (Tool window — does not auto-dismiss
    on outside clicks, which would be disruptive while editing bounds).
    """

    hidden = pyqtSignal()

    def __init__(self, view_settings, parent=None):
        super().__init__(parent)
        self.setObjectName("AxisSettingsPopover")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(view_settings)
        self.adjustSize()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.hidden.emit()


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
    LEFT_PANEL_WIDTH = 480

    def __init__(self, grid: Grid | None = None):
        super().__init__()
        self.setWindowTitle("pringle")
        self.setWindowIcon(QIcon(str(_ICON_PATH)))
        self.resize(*self.DEFAULT_SIZE)
        self._grid = grid or make_grid()

        # Root widget: header bar on top, horizontal splitter below
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        # Header bar
        self._header = PringleHeaderBar()
        self._header.new_requested.connect(self._on_new)
        self._header.open_requested.connect(self._on_open)
        self._header.save_requested.connect(self._on_save)
        self._header.screenshot_requested.connect(self._save_image)
        self._header.settings_toggled.connect(self._on_settings_toggled)
        root_layout.addWidget(self._header)

        # Horizontal splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter, 1)

        # 3D viewport
        self._viewport = PringleViewport()
        cfg = self._grid.config
        z_half = max(abs(cfg.x_min), abs(cfg.x_max), abs(cfg.y_min), abs(cfg.y_max))
        self._viewport.renderer.set_overlay_bounds(
            cfg.x_min, cfg.x_max, cfg.y_min, cfg.y_max, -z_half, z_half
        )
        self._vp_container = _ViewportContainer(self._viewport)

        # Floating axis settings dialog (non-modal Qt.Tool window)
        self._view_settings = ViewSettingsWidget(config=self._grid.config)
        self._view_settings.bounds_changed.connect(self._on_bounds_changed)
        self._view_settings.resolution_changed.connect(self._on_resolution_changed)
        self._view_settings.camera_preset_requested.connect(self._viewport.set_camera_preset)
        self._view_settings.fit_all_requested.connect(self._viewport.renderer.fit_camera)
        self._view_settings.axes_visibility_changed.connect(
            self._viewport.renderer.set_axes_visible
        )
        self._view_settings.bbox_visibility_changed.connect(
            self._viewport.renderer.set_bbox_visible
        )
        self._view_settings.crosshair_visibility_changed.connect(
            self._viewport.renderer.set_crosshair_visible
        )
        self._view_settings.background_changed.connect(self._on_background_changed)
        self._view_settings.equalize_requested.connect(self._on_equalize)
        self._view_settings.fit_requested.connect(self._on_fit_to_data)
        self._view_settings.shadow_visibility_changed.connect(
            self._viewport.renderer.set_shadow_visible
        )
        self._view_settings.shadow_opacity_changed.connect(
            self._viewport.renderer.set_shadow_opacity
        )

        self._settings_dialog = AxisSettingsPopover(self._view_settings, parent=self)
        self._settings_dialog.hidden.connect(
            lambda: self._header.set_wrench_checked(False)
        )

        # Left panel: cell list only (view settings moved to floating dialog)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(15, 0, 0, 0)
        left_layout.setSpacing(0)

        self._cell_list = CellListWidget(
            on_cell_result=self._on_cell_result,
            on_cell_deleted=self._viewport.forget_cell,
            grid=self._grid,
            eval_threaded=True,
        )
        self._cell_list.namespace_rebuilt.connect(self._on_namespace_rebuilt)
        self._cell_list.session_dirtied.connect(self._mark_modified)
        self._cell_list.bounds_override.connect(self._on_bounds_override)
        left_layout.addWidget(self._cell_list, 1)

        splitter.insertWidget(0, left)
        splitter.addWidget(self._vp_container)

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
            (QKeySequence("Ctrl+P"),          self._on_open),
            (QKeySequence.StandardKey.Save,   self._on_save),
            (QKeySequence("Ctrl+Shift+S"),    self._on_save_as),
            (QKeySequence.StandardKey.Undo,   self._on_undo),
            (QKeySequence.StandardKey.Redo,   self._on_redo),
            (QKeySequence.StandardKey.Copy,   self._on_copy),
            (QKeySequence.StandardKey.Paste,  self._on_paste),
            (QKeySequence("Ctrl+/"),          self._cell_list.toggle_comment_focused_cell),
            (QKeySequence("Ctrl+D"),          self._cell_list.duplicate_focused_cell),
        ]:
            sc = QShortcut(keys, self)
            sc.activated.connect(slot)

    def _mark_modified(self) -> None:
        if not self._modified:
            self._modified = True
            self._update_title()

    def closeEvent(self, event) -> None:
        # Stop submitting new GPU work: no new frames, no new map_async calls.
        self._viewport._draw_timer.stop()
        # Stop the eval thread before Qt destroys widgets. Without this the
        # background thread can call results_ready.emit() after _EvalWorker's
        # C++ object is deleted, producing a "wrapped C/C++ object deleted" crash.
        self._cell_list.shutdown()
        # Drain pending GPU async callbacks (map_async completions) for up to
        # 50 ms. The wgpu-native poller fires these on the Qt main thread via
        # CallerHelper; if CallerHelper is deleted first by super().closeEvent()
        # it raises RuntimeError. A fixed iteration count misses late arrivals
        # under load, so use a time-bounded spin instead (BUG-047).
        import time as _time
        _deadline = _time.monotonic() + 0.05
        while _time.monotonic() < _deadline:
            QApplication.processEvents()
        super().closeEvent(event)

    def _update_title(self) -> None:
        name = Path(self._session_path).name if self._session_path else "untitled"
        if self._modified:
            self.setWindowTitle(f"pringle — {name}[*]")
            self.setWindowModified(True)
        else:
            self.setWindowModified(False)
            self.setWindowTitle(f"pringle — {name}")
        self._header.set_modified(self._modified)

    def _confirm_discard(self) -> bool:
        """Return True if it's safe to discard the current session."""
        if not self._modified:
            return True

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout

        dlg = QDialog(self)
        dlg.setWindowTitle("Unsaved changes")
        dlg.setWindowFlags(
            dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        vbox = QVBoxLayout(dlg)
        vbox.setSpacing(16)
        vbox.setContentsMargins(20, 16, 20, 16)
        vbox.addWidget(QLabel("You have unsaved changes."))

        hbox = QHBoxLayout()
        hbox.setSpacing(8)
        hbox.addStretch()

        _pill = (
            "QPushButton {{"
            " color: {c}; font-size: 12px; padding: 4px 12px;"
            " background: transparent; border: 1px solid {b}; border-radius: 10px;"
            "}}"
            "QPushButton:hover {{ color: #eee; border-color: #666; }}"
            "QPushButton:pressed {{ background: #222; }}"
        )

        save_btn = QPushButton("Save")
        save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(_pill.format(c="#E9A15F", b="#E9A15F"))

        discard_btn = QPushButton("Discard")
        discard_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        discard_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        discard_btn.setStyleSheet(_pill.format(c="#888", b="#333"))

        hbox.addWidget(discard_btn)
        hbox.addWidget(save_btn)
        vbox.addLayout(hbox)

        result: list[str] = []
        save_btn.clicked.connect(lambda: (result.append("save"), dlg.accept()))
        discard_btn.clicked.connect(lambda: (result.append("discard"), dlg.accept()))

        dlg.exec()

        if not result:
            return False          # dismissed / Escape → cancel
        if result[0] == "discard":
            return True
        self._on_save()
        return not self._modified  # True only if save completed (not cancelled)

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
        import importlib.resources
        examples_dir = str(importlib.resources.files("pringle") / "examples")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open session", examples_dir, "YAML (*.yaml *.yml);;Pringle session (*.pringle)"
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
            self._view_settings.set_bounds(
                cfg.x_min, cfg.x_max, cfg.y_min, cfg.y_max, cfg.z_min, cfg.z_max
            )
            self._viewport.renderer.set_overlay_bounds(
                cfg.x_min, cfg.x_max, cfg.y_min, cfg.y_max, cfg.z_min, cfg.z_max
            )
        view = data.get("view", {})
        if view:
            self._view_settings._axes_cb.setChecked(view.get("show_axes", True))
            self._view_settings._bbox_cb.setChecked(view.get("show_bbox", True))
            self._view_settings._crosshair_cb.setChecked(view.get("show_crosshair", True))
            self._view_settings._bg_cb.setChecked(view.get("show_light_bg", False))
            # Restore shadow: set opacity first so material is correct when shadows are made visible
            if "shadow_opacity" in view:
                self._view_settings._shadow_opacity_spin.setValue(view["shadow_opacity"])
            self._view_settings._shadow_cb.setChecked(view.get("show_shadow", False))
            if "camera_position" in view and "orbit_target" in view:
                cam = self._viewport._pr._camera
                tgt = view["orbit_target"]
                cam.local.position = view["camera_position"]
                cam.look_at(tgt)
                self._viewport._pr._controller.target = tuple(tgt)
            if "angular_velocity" in view:
                av = view["angular_velocity"]
                self._viewport._pr._orbit_handler._coast_velocity = (float(av[0]), float(av[1]))
            # Restore axis bound expression strings (values already set via set_bounds above)
            for key, box in [
                ("x_min_expr", self._view_settings._x_min),
                ("x_max_expr", self._view_settings._x_max),
                ("y_min_expr", self._view_settings._y_min),
                ("y_max_expr", self._view_settings._y_max),
                ("z_min_expr", self._view_settings._z_min),
                ("z_max_expr", self._view_settings._z_max),
            ]:
                if key in view:
                    box._raw_expr = view[key]
                    box.setText(view[key])

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
            self, "Save session", "", "YAML (*.yaml *.yml);;Pringle session (*.pringle)"
        )
        if path:
            self._write_session(path)

    def _save_image(self) -> None:
        from PIL import Image
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Image", "pringle_screenshot.png", "PNG Images (*.png)"
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        rgba = self._viewport.renderer.snapshot()
        Image.fromarray(rgba, "RGBA").save(path)

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
        pr = self._viewport._pr
        cam_pos = pr._camera.local.position
        tgt = pr._controller.target
        view = {
            "show_axes":       self._view_settings._axes_cb.isChecked(),
            "show_bbox":       self._view_settings._bbox_cb.isChecked(),
            "show_crosshair":  self._view_settings._crosshair_cb.isChecked(),
            "show_light_bg":   self._view_settings._bg_cb.isChecked(),
            "show_shadow":     self._view_settings._shadow_cb.isChecked(),
            "shadow_opacity":  self._view_settings._shadow_opacity_spin.value(),
            "camera_position": [float(cam_pos[0]), float(cam_pos[1]), float(cam_pos[2])],
            "orbit_target":    [float(tgt[0]),     float(tgt[1]),     float(tgt[2])],
        }
        vel = self._viewport._pr._orbit_handler._coast_velocity
        if vel is not None:
            view["angular_velocity"] = [float(vel[0]), float(vel[1])]
        for key, box in [
            ("x_min_expr", self._view_settings._x_min),
            ("x_max_expr", self._view_settings._x_max),
            ("y_min_expr", self._view_settings._y_min),
            ("y_max_expr", self._view_settings._y_max),
            ("z_min_expr", self._view_settings._z_min),
            ("z_max_expr", self._view_settings._z_max),
        ]:
            if box.expr():
                view[key] = box.expr()
        try:
            save_session(path, self._cell_list, self._grid.config, view=view)
        except Exception as exc:
            QMessageBox.critical(self, "Save error", str(exc))
            return
        self._session_path = path
        self._modified = False
        self._update_title()

    def _on_namespace_rebuilt(self) -> None:
        from pringle.cell_list import _make_resolver
        self._view_settings.set_resolver(_make_resolver(self._cell_list._shared_ns))

    # ------------------------------------------------------------------
    # Viewport update callback
    # ------------------------------------------------------------------

    def _on_cell_result(self, cell_id: str, result: CellResult, style: CellStyle) -> None:
        """
        Called by CellListWidget after each cell evaluation.
        Updates or removes the corresponding object in the 3D scene.
        """
        vp = self._viewport

        cmap      = style.colormap
        cmap_rev  = style.colormap_reversed

        if result.render_type == "surface":
            vp.update_surface(
                cell_id,
                result.x, result.y, result.data,
                color=style.color, opacity=style.opacity,
                constraint_mask=result.constraint_mask,
                constraint_values=result.constraint_values,
                z_raw=result.data_unmasked,
                colormap=cmap, colormap_reversed=cmap_rev,
            )

        elif result.render_type == "surface_y":
            vp.update_surface(
                cell_id,
                self._grid.x, self._grid.y, result.data,
                color=style.color, opacity=style.opacity,
                constraint_mask=None, constraint_values=None, z_raw=None,
                colormap=cmap, colormap_reversed=cmap_rev,
            )

        elif result.render_type == "curve":
            pts = np.column_stack([
                self._grid.x1d,
                result.data,
                np.zeros(len(result.data), dtype=np.float32),
            ])
            line = make_line_mesh(pts, color=style.color, opacity=style.opacity,
                                  thickness=style.line_width,
                                  colormap=cmap, colormap_reversed=cmap_rev)
            vp.add_object(cell_id, line)

        elif result.render_type == "curve_x":
            if len(result.data) != len(self._grid.y1d):
                vp.remove_object(cell_id)
                return
            pts = np.column_stack([
                result.data,
                self._grid.y1d,
                np.zeros(len(result.data), dtype=np.float32),
            ])
            line = make_line_mesh(pts, color=style.color, opacity=style.opacity,
                                  thickness=style.line_width,
                                  colormap=cmap, colormap_reversed=cmap_rev)
            vp.add_object(cell_id, line)

        elif result.render_type == "parametric":
            pts = np.asarray(result.data, dtype=np.float32)
            if pts.ndim == 3 and pts.shape[0] == 3:
                mesh = make_parametric_surface_mesh(
                    pts, color=style.color, opacity=style.opacity,
                    colormap=cmap, colormap_reversed=cmap_rev,
                )
                vp.add_object(cell_id, mesh)
            elif pts.ndim == 2 and pts.shape[1] in (2, 3):
                scatter = make_scatter_mesh(pts, color=style.color, opacity=style.opacity,
                                            size=style.point_size,
                                            as_spheres=(style.scatter_render_mode == "spheres"),
                                            colormap=cmap, colormap_reversed=cmap_rev)
                vp.add_object(cell_id, scatter)
            else:
                vp.remove_object(cell_id)

        elif result.render_type in ("scatter", "scatter_2d"):
            mode = style.scatter_render_mode
            if mode == "line":
                line = make_line_mesh(result.data, color=style.color, opacity=style.opacity,
                                      thickness=style.line_width,
                                      colormap=cmap, colormap_reversed=cmap_rev)
                vp.add_object(cell_id, line)
            elif mode == "arrows":
                # Flow mode: N−1 arrows between consecutive scatter points
                pts = result.data
                if len(pts) >= 2:
                    arrows = np.concatenate([pts[:-1], pts[1:]], axis=1)  # (N-1, 6)
                    vp.update_arrows(cell_id, arrows, color=style.color, opacity=style.opacity,
                                     normalize=style.normalize_arrows, size=style.point_size,
                                     colormap=cmap, colormap_reversed=cmap_rev)
                else:
                    vp.remove_object(cell_id)
            else:
                scatter = make_scatter_mesh(result.data, color=style.color, opacity=style.opacity,
                                            size=style.point_size,
                                            as_spheres=(mode == "spheres"),
                                            colormap=cmap, colormap_reversed=cmap_rev)
                vp.add_object(cell_id, scatter)

        elif result.render_type in ("scatter_batch", "scatter_batch_2d"):
            data = result.data  # (k, N, 2) or (k, N, 3), already float32
            k, N, cols = data.shape
            if cols == 2:
                data = np.concatenate([data, np.zeros((k, N, 1), dtype=np.float32)], axis=2)

            mode = style.scatter_render_mode
            if mode == "line":
                sep = np.full((k, 1, 3), np.nan, dtype=np.float32)
                padded = np.concatenate([data, sep], axis=1)   # (k, N+1, 3)
                pts = padded.reshape(-1, 3)[:-1]               # (k*(N+1)-1, 3)
                if cmap is not None:
                    idx_line = np.linspace(0.0, 1.0, N, dtype=np.float32)
                    line_colors = _apply_colormap(idx_line, cmap, cmap_rev)         # (N, 4)
                    tiled = np.tile(line_colors, (k, 1)).reshape(k, N, 4)           # (k, N, 4)
                    nan_row = np.zeros((k, 1, 4), dtype=np.float32)
                    vertex_colors = np.concatenate(
                        [tiled, nan_row], axis=1
                    ).reshape(-1, 4)[:-1]                                           # (k*(N+1)-1, 4)
                    line = make_line_mesh(pts, color=style.color, opacity=style.opacity,
                                         thickness=style.line_width,
                                         vertex_colors=vertex_colors)
                else:
                    line = make_line_mesh(pts, color=style.color, opacity=style.opacity,
                                         thickness=style.line_width)
                vp.add_object(cell_id, line)

            elif mode == "arrows":
                if N >= 2:
                    # Fully vectorized: build all k*(N-1) arrows without a Python loop
                    tails = data[:, :-1, :].reshape(-1, 3)
                    heads = data[:, 1:, :].reshape(-1, 3)
                    arrows = np.concatenate([tails, heads], axis=1)
                    if cmap is not None:
                        # Each of k batches of (N-1) arrows independently spans 0→1
                        idx_arrow = np.linspace(0.0, 1.0, N - 1, dtype=np.float32)
                        arrow_colors = _apply_colormap(idx_arrow, cmap, cmap_rev)  # (N-1, 4)
                        arrow_vc = np.tile(arrow_colors, (k, 1))                   # (k*(N-1), 4)
                        vp.update_arrows(cell_id, arrows, color=style.color, opacity=style.opacity,
                                         normalize=style.normalize_arrows, size=style.point_size,
                                         vertex_colors=arrow_vc)
                    else:
                        vp.update_arrows(cell_id, arrows, color=style.color, opacity=style.opacity,
                                         normalize=style.normalize_arrows, size=style.point_size)
                else:
                    vp.remove_object(cell_id)

            else:  # circles or spheres
                pts = data.reshape(-1, 3)  # (k*N, 3)
                if cmap is not None:
                    # Each of k batches of N points independently spans 0→1
                    idx_line = np.linspace(0.0, 1.0, N, dtype=np.float32)
                    line_colors = _apply_colormap(idx_line, cmap, cmap_rev)  # (N, 4)
                    batch_vc = np.tile(line_colors, (k, 1))                  # (k*N, 4)
                    scatter = make_scatter_mesh(pts, color=style.color, opacity=style.opacity,
                                               size=style.point_size,
                                               as_spheres=(mode == "spheres"),
                                               vertex_colors=batch_vc)
                else:
                    scatter = make_scatter_mesh(pts, color=style.color, opacity=style.opacity,
                                               size=style.point_size,
                                               as_spheres=(mode == "spheres"),
                                               colormap=cmap, colormap_reversed=cmap_rev)
                vp.add_object(cell_id, scatter)

        elif result.render_type in ("vectors", "vectors_2d"):
            data = result.data
            if result.render_type == "vectors_2d":
                # Promote 2D tail+head (N, 4) to 3D (N, 6) by inserting z=0 columns
                data = np.column_stack([
                    data[:, :2], np.zeros(len(data), dtype=np.float32),
                    data[:, 2:], np.zeros(len(data), dtype=np.float32),
                ])
            vp.update_arrows(cell_id, data, color=style.color, opacity=style.opacity,
                             normalize=style.normalize_arrows, size=style.point_size,
                             colormap=cmap, colormap_reversed=cmap_rev)

        else:
            # No renderable output (comment, slider, error, or hidden) — clear
            vp.remove_object(cell_id)

    # ------------------------------------------------------------------
    # View settings handlers
    # ------------------------------------------------------------------

    def _on_bounds_override(
        self,
        x_min: float, x_max: float,
        y_min: float, y_max: float,
        z_min: float, z_max: float,
    ) -> None:
        """Cell wrote to cfg — update spinboxes and rebuild the grid (FEAT-057)."""
        self._view_settings.set_bounds(x_min, x_max, y_min, y_max, z_min, z_max)
        self._on_bounds_changed(x_min, x_max, y_min, y_max, z_min, z_max)

    def _on_bounds_changed(
        self,
        x_min: float, x_max: float,
        y_min: float, y_max: float,
        z_min: float, z_max: float,
    ) -> None:
        config = GridConfig(
            x_min=x_min, x_max=x_max,
            y_min=y_min, y_max=y_max,
            z_min=z_min, z_max=z_max,
            n=self._grid.config.n,
        )
        self._grid = make_grid(config)
        self._cell_list.update_grid(self._grid)
        self._viewport.renderer.set_overlay_bounds(x_min, x_max, y_min, y_max, z_min, z_max)

    def _on_settings_toggled(self, checked: bool) -> None:
        """Show or hide the floating axis settings dialog."""
        if checked:
            self._settings_dialog.adjustSize()
            # Position below the header wrench button, right-aligned
            btn = self._header._wrench_btn
            btn_br = btn.mapToGlobal(btn.rect().bottomRight())
            dlg_x = btn_br.x() - self._settings_dialog.width()
            dlg_y = btn_br.y() + 4
            self._settings_dialog.move(dlg_x, dlg_y)
            self._settings_dialog.show()
            self._settings_dialog.raise_()
        else:
            self._settings_dialog.hide()

    _LIGHT_BG = (0.95, 0.95, 0.95, 1.0)
    _DARK_BG  = (0.067, 0.067, 0.067, 1.0)

    def _on_background_changed(self, light: bool) -> None:
        self._viewport.renderer.set_background_color(
            self._LIGHT_BG if light else self._DARK_BG
        )
        self._viewport.renderer.set_shadow_color_for_bg(light)

    def _on_equalize(self) -> None:
        """Set x/y span equal to the current z span, centered at zero."""
        z_min = self._view_settings._z_min.value()
        z_max = self._view_settings._z_max.value()
        z_span = z_max - z_min
        if z_span <= 0:
            return
        half = z_span / 2
        self._view_settings.set_bounds(-half, half, -half, half)
        self._on_bounds_changed(-half, half, -half, half, z_min, z_max)

    def _on_fit_to_data(self) -> None:
        """Set all three axis bounds to a cube that snugly encloses all rendered objects."""
        lo = np.full(3, np.inf)
        hi = np.full(3, -np.inf)
        for obj in self._viewport.renderer._objects.values():
            bb = obj.get_world_bounding_box()
            if bb is not None and np.all(np.isfinite(bb)):
                lo = np.minimum(lo, bb[0])
                hi = np.maximum(hi, bb[1])
        if not np.all(np.isfinite(lo)):
            return  # no renderable objects (or all have degenerate/inf bounds)
        # Uniform cube with 5% padding; minimum half-span of 0.5 guards flat/point data
        half_span = max(float(np.max((hi - lo) / 2)) * 1.05, 0.5)
        center = (lo + hi) / 2.0
        new_min = center - half_span
        new_max = center + half_span
        self._view_settings.set_bounds(
            float(new_min[0]), float(new_max[0]),
            float(new_min[1]), float(new_max[1]),
            float(new_min[2]), float(new_max[2]),
        )
        self._on_bounds_changed(
            float(new_min[0]), float(new_max[0]),
            float(new_min[1]), float(new_max[1]),
            float(new_min[2]), float(new_max[2]),
        )

    def _on_resolution_changed(self, n: int) -> None:
        cfg = self._grid.config
        config = GridConfig(
            x_min=cfg.x_min, x_max=cfg.x_max,
            y_min=cfg.y_min, y_max=cfg.y_max,
            z_min=cfg.z_min, z_max=cfg.z_max,
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


def _load_theme(app: QApplication) -> None:
    """Load theme.qss (with @var substitution) and apply it as the application stylesheet."""
    from pringle.theme import load_stylesheet
    app.setStyleSheet(load_stylesheet())


def launch(argv=None) -> int:
    """Start the Pringle Qt application. Returns exit code."""
    app = QApplication(argv or sys.argv)
    app.setApplicationName("pringle")
    app.setWindowIcon(QIcon(str(_ICON_PATH)))
    _load_theme(app)

    win = PringleWindow(grid=make_grid(GridConfig(n=64)))
    win.show()

    # Seed the session with a demo cell, then clear the modified flag so the
    # default state doesn't prompt the user to save on first open/new/quit.
    # Stop debounce timers first — add_cell arms them, and they would re-dirty
    # the session ~300 ms later if left running.
    win.cell_list.add_cell("z = sin(x) * cos(y)")
    for _cell in win.cell_list._cells:
        if hasattr(_cell, "_debounce"):
            _cell._debounce.stop()
    win._modified = False
    win._update_title()

    return app.exec()


if __name__ == "__main__":
    sys.exit(launch())
