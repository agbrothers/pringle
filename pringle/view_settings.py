"""
ViewSettingsWidget — axis bounds, grid resolution, and camera controls.

Signals
-------
bounds_changed(x_min, x_max, y_min, y_max)
    Emitted when the user clicks "Apply" after editing bounds.
resolution_changed(n: int)
    Emitted immediately as the resolution spinbox changes.
camera_preset_requested(name: str)
    "iso" | "top" | "front"
fit_all_requested()
    Camera should frame all visible objects.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QSpinBox, QPushButton, QGroupBox, QCheckBox,
)
from PyQt6.QtCore import pyqtSignal

from pringle.grid import GridConfig


class ViewSettingsWidget(QWidget):
    bounds_changed = pyqtSignal(float, float, float, float, float, float)
    resolution_changed = pyqtSignal(int)
    camera_preset_requested = pyqtSignal(str)
    fit_all_requested = pyqtSignal()
    axes_visibility_changed = pyqtSignal(bool)
    bbox_visibility_changed = pyqtSignal(bool)
    crosshair_visibility_changed = pyqtSignal(bool)
    equalize_requested = pyqtSignal()
    fit_requested = pyqtSignal()          # fit all axis bounds to rendered data
    background_changed = pyqtSignal(bool) # True = light, False = dark

    def __init__(self, config: GridConfig | None = None, parent=None):
        super().__init__(parent)
        self._config = config or GridConfig()
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 8)
        outer.setSpacing(6)

        # Axis bounds
        bounds_box = QGroupBox("Axis Bounds")
        bl = QVBoxLayout(bounds_box)
        bl.setContentsMargins(4, 4, 4, 4)
        bl.setSpacing(2)

        for axis, attr_min, attr_max in (
            ("X", "_x_min", "_x_max"),
            ("Y", "_y_min", "_y_max"),
            ("Z", "_z_min", "_z_max"),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{axis}:"))
            lo = QDoubleSpinBox()
            lo.setRange(-1e4, 1e4)
            lo.setDecimals(1)
            lo.setValue(getattr(self._config, f"{axis.lower()}_min"))
            lo.setFixedWidth(60)
            setattr(self, attr_min, lo)
            row.addWidget(lo)
            row.addWidget(QLabel("to"))
            hi = QDoubleSpinBox()
            hi.setRange(-1e4, 1e4)
            hi.setDecimals(1)
            hi.setValue(getattr(self._config, f"{axis.lower()}_max"))
            hi.setFixedWidth(60)
            setattr(self, attr_max, hi)
            row.addWidget(hi)
            row.addStretch(1)
            bl.addLayout(row)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply Bounds")
        apply_btn.setObjectName("apply_bounds_btn")
        apply_btn.setFixedHeight(24)
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)

        eq_btn = QPushButton("Equalize Axes")
        eq_btn.setObjectName("equalize_btn")
        eq_btn.setFixedHeight(24)
        eq_btn.setToolTip("Set X and Y bounds to match the current Z data range")
        eq_btn.clicked.connect(self.equalize_requested)
        btn_row.addWidget(eq_btn)

        fit_btn = QPushButton("Fit to Data")
        fit_btn.setObjectName("fit_to_data_btn")
        fit_btn.setFixedHeight(24)
        fit_btn.setToolTip("Set all axis bounds to a cube that encloses all rendered objects")
        fit_btn.clicked.connect(self.fit_requested)
        btn_row.addWidget(fit_btn)

        bl.addLayout(btn_row)

        # Overlay toggles
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(12)
        self._axes_cb = QCheckBox("Axes")
        self._axes_cb.setChecked(True)
        self._axes_cb.toggled.connect(self.axes_visibility_changed)
        toggle_row.addWidget(self._axes_cb)

        self._bbox_cb = QCheckBox("Wireframe")
        self._bbox_cb.setChecked(True)
        self._bbox_cb.toggled.connect(self.bbox_visibility_changed)
        toggle_row.addWidget(self._bbox_cb)

        self._crosshair_cb = QCheckBox("Crosshair")
        self._crosshair_cb.setChecked(True)
        self._crosshair_cb.toggled.connect(self.crosshair_visibility_changed)
        toggle_row.addWidget(self._crosshair_cb)

        self._bg_cb = QCheckBox("Light bg")
        self._bg_cb.setChecked(True)
        self._bg_cb.toggled.connect(self.background_changed)
        toggle_row.addWidget(self._bg_cb)

        toggle_row.addStretch(1)
        bl.addLayout(toggle_row)

        outer.addWidget(bounds_box)

        # Resolution
        res_row = QHBoxLayout()
        res_row.addWidget(QLabel("Resolution n:"))
        self._res_spin = QSpinBox()
        self._res_spin.setRange(8, 256)
        self._res_spin.setValue(self._config.n)
        self._res_spin.setSingleStep(8)
        self._res_spin.valueChanged.connect(self.resolution_changed)
        res_row.addWidget(self._res_spin)
        res_row.addStretch(1)
        outer.addLayout(res_row)

        # Camera presets
        cam_box = QGroupBox("Camera")
        cl = QHBoxLayout(cam_box)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.setSpacing(4)
        for name, label in [("iso", "Iso"), ("top", "Top"), ("front", "Front")]:
            btn = QPushButton(label)
            btn.setObjectName(f"preset_{name}_btn")
            btn.setFixedHeight(24)
            btn.clicked.connect(
                lambda _checked=False, n=name: self.camera_preset_requested.emit(n)
            )
            cl.addWidget(btn)
        fit_btn = QPushButton("Fit All")
        fit_btn.setObjectName("fit_all_btn")
        fit_btn.setFixedHeight(24)
        fit_btn.clicked.connect(self.fit_all_requested)
        cl.addWidget(fit_btn)
        outer.addWidget(cam_box)

    def set_bounds(
        self,
        x_min: float, x_max: float,
        y_min: float, y_max: float,
        z_min: float | None = None, z_max: float | None = None,
    ) -> None:
        """Push new bounds into the spinboxes (used by equalize and session restore)."""
        pairs = [
            (self._x_min, x_min), (self._x_max, x_max),
            (self._y_min, y_min), (self._y_max, y_max),
        ]
        if z_min is not None and z_max is not None:
            pairs += [(self._z_min, z_min), (self._z_max, z_max)]
        for spin, val in pairs:
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)

    def _on_apply(self):
        self.bounds_changed.emit(
            self._x_min.value(), self._x_max.value(),
            self._y_min.value(), self._y_max.value(),
            self._z_min.value(), self._z_max.value(),
        )

    def current_config(self) -> GridConfig:
        """Return a GridConfig reflecting the current widget state."""
        return GridConfig(
            x_min=self._x_min.value(), x_max=self._x_max.value(),
            y_min=self._y_min.value(), y_max=self._y_max.value(),
            z_min=self._z_min.value(), z_max=self._z_max.value(),
            n=self._res_spin.value(),
        )
