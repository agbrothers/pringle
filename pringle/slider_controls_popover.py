"""
SliderControlsPopover — floating panel for slider step, speed, and direction.

Anchored below the ↺ button on a SliderWidget. Reads and writes back to the
parent SliderWidget directly so session.py serialization is unaffected.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QApplication,
)
from PyQt6.QtCore import Qt

from pringle.slider_widget import _ExprBox


class SliderControlsPopover(QFrame):
    """Frameless popup for step size, animation speed, and direction."""

    def __init__(self, slider, parent=None):
        super().__init__(parent)
        self._slider = slider
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setObjectName("SliderControlsPopover")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        # Step size
        step_row = QHBoxLayout()
        step_row.addWidget(QLabel("Step:"))
        self._step_box = _ExprBox(self._slider._step_box.value())
        self._step_box.setFixedWidth(80)
        if self._slider._step_box.expr():
            self._step_box._raw_expr = self._slider._step_box.expr()
            self._step_box.setText(self._slider._step_box.expr())
        self._step_box.committed.connect(self._on_step_committed)
        step_row.addWidget(self._step_box)
        step_row.addStretch()
        layout.addLayout(step_row)

        # Speed
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed:"))
        self._speed_combo = QComboBox()
        self._speed_combo.addItems(["0.5×", "1×", "2×"])
        _speed_map = {0.5: 0, 1.0: 1, 2.0: 2}
        self._speed_combo.setCurrentIndex(
            _speed_map.get(self._slider._anim_speed_multiplier, 1)
        )
        self._speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self._speed_combo)
        speed_row.addStretch()
        layout.addLayout(speed_row)

        # Direction
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Direction:"))
        self._dir_combo = QComboBox()
        self._dir_combo.addItems(["Bounce", "Loop"])
        self._dir_combo.setCurrentIndex(0 if self._slider._anim_mode == "pingpong" else 1)
        self._dir_combo.currentIndexChanged.connect(self._on_direction_changed)
        dir_row.addWidget(self._dir_combo)
        dir_row.addStretch()
        layout.addLayout(dir_row)

    # ------------------------------------------------------------------
    # Handlers — write directly back to parent slider
    # ------------------------------------------------------------------

    def _on_step_committed(self, value: float) -> None:
        self._slider._step_box.setValue(value)
        # Sync raw expr if user typed one
        if self._step_box.expr():
            self._slider._step_box._raw_expr = self._step_box.expr()
            self._slider._step_box.setText(self._step_box.expr())

    def _on_speed_changed(self, index: int) -> None:
        multipliers = [0.5, 1.0, 2.0]
        self._slider.set_anim_speed_multiplier(multipliers[index])

    def _on_direction_changed(self, index: int) -> None:
        self._slider.set_anim_mode("pingpong" if index == 0 else "loop")
