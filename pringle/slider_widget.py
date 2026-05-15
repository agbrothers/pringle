"""
SliderWidget — a parameter slider cell for the equation panel.

Renders a named parameter with:
  [color dot] [name]  ──●────────────  [value]  [min]..[max]  [▷/‖]

Signals:
  value_changed(name, float)  — emitted whenever the slider moves
  delete_requested(cell_id)   — ✕ button clicked

Animation modes: static (no auto-play), loop, bounce, once.
The animation is driven by a QTimer internal to this widget.
"""

from __future__ import annotations

import uuid
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QSlider, QDoubleSpinBox,
    QPushButton, QFrame, QVBoxLayout, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from pringle.style import CellStyle, palette_color


class SliderWidget(QWidget):
    """Slider cell for a named scalar parameter."""

    value_changed = pyqtSignal(str, float)     # (name, value)
    delete_requested = pyqtSignal(str)          # cell_id

    _ANIM_INTERVAL_MS = 16   # ~60fps animation step

    def __init__(
        self,
        name: str,
        value: float = 1.0,
        min_val: float = 0.0,
        max_val: float = 10.0,
        cell_id: str | None = None,
        style: CellStyle | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.cell_id: str = cell_id or str(uuid.uuid4())
        self.name: str = name
        self.style: CellStyle = style or CellStyle()

        self._value: float = value
        self._min: float = min_val
        self._max: float = max_val
        self._anim_mode: str = "static"   # "static" | "loop" | "bounce"
        self._anim_dir: int = 1           # +1 or -1 for bounce

        self._build_ui()

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(self._ANIM_INTERVAL_MS)
        self._anim_timer.timeout.connect(self._anim_tick)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setContentsMargins(0, 2, 0, 2)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(6)

        # Color dot
        self._color_dot = QPushButton()
        self._color_dot.setFixedSize(18, 18)
        self._color_dot.setFlat(True)
        self._update_color_dot()
        row.addWidget(self._color_dot)

        # Name label
        self._name_label = QLabel(f"<b>{self.name}</b>")
        self._name_label.setFixedWidth(50)
        row.addWidget(self._name_label)

        # Slider (integer-quantized; mapped to float range)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setValue(self._float_to_int(self._value))
        self._slider.valueChanged.connect(self._on_slider_moved)
        row.addWidget(self._slider, 1)

        # Value spinbox
        self._spinbox = QDoubleSpinBox()
        self._spinbox.setDecimals(3)
        self._spinbox.setRange(self._min, self._max)
        self._spinbox.setValue(self._value)
        self._spinbox.setFixedWidth(80)
        self._spinbox.valueChanged.connect(self._on_spinbox_changed)
        row.addWidget(self._spinbox)

        # Min/max bounds
        self._min_box = QDoubleSpinBox()
        self._min_box.setDecimals(1)
        self._min_box.setRange(-1e6, 1e6)
        self._min_box.setValue(self._min)
        self._min_box.setFixedWidth(56)
        self._min_box.setPrefix("")
        self._min_box.valueChanged.connect(self._on_range_changed)
        row.addWidget(self._min_box)

        self._range_label = QLabel("–")
        row.addWidget(self._range_label)

        self._max_box = QDoubleSpinBox()
        self._max_box.setDecimals(1)
        self._max_box.setRange(-1e6, 1e6)
        self._max_box.setValue(self._max)
        self._max_box.setFixedWidth(56)
        self._max_box.valueChanged.connect(self._on_range_changed)
        row.addWidget(self._max_box)

        # Play / pause button
        self._play_btn = QPushButton("▷")
        self._play_btn.setFixedSize(28, 24)
        self._play_btn.setCheckable(True)
        self._play_btn.setToolTip("Animate (loop)")
        self._play_btn.clicked.connect(self._on_play_toggled)
        row.addWidget(self._play_btn)

        # Delete button
        self._delete_btn = QPushButton("✕")
        self._delete_btn.setFixedSize(24, 24)
        self._delete_btn.setFlat(True)
        self._delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.cell_id))
        row.addWidget(self._delete_btn)

        outer.addLayout(row)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #ddd;")
        outer.addWidget(line)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def value(self) -> float:
        return self._value

    def source(self) -> str:
        return f"{self.name} = {self._value}"

    def is_visible_cell(self) -> bool:
        return True

    def focus(self) -> None:
        pass

    def set_error(self, msg: str | None) -> None:
        pass

    def set_warning(self, msg: str | None) -> None:
        pass

    def clear_diagnostics(self) -> None:
        pass

    def set_value(self, v: float, emit: bool = True) -> None:
        v = max(self._min, min(self._max, v))
        self._value = v
        self._spinbox.blockSignals(True)
        self._slider.blockSignals(True)
        self._spinbox.setValue(v)
        self._slider.setValue(self._float_to_int(v))
        self._spinbox.blockSignals(False)
        self._slider.blockSignals(False)
        if emit:
            self.value_changed.emit(self.name, v)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _float_to_int(self, v: float) -> int:
        if self._max == self._min:
            return 0
        return int(round((v - self._min) / (self._max - self._min) * 1000))

    def _int_to_float(self, i: int) -> float:
        return self._min + (i / 1000.0) * (self._max - self._min)

    def _update_color_dot(self):
        r, g, b, _ = self.style.color
        hex_color = "#{:02x}{:02x}{:02x}".format(int(r*255), int(g*255), int(b*255))
        self._color_dot.setStyleSheet(
            f"QPushButton {{ background-color: {hex_color}; "
            f"border-radius: 9px; border: 1px solid rgba(0,0,0,0.15); }}"
        )

    def _on_slider_moved(self, pos: int):
        v = self._int_to_float(pos)
        self._value = v
        self._spinbox.blockSignals(True)
        self._spinbox.setValue(v)
        self._spinbox.blockSignals(False)
        self.value_changed.emit(self.name, v)

    def _on_spinbox_changed(self, v: float):
        self._value = v
        self._slider.blockSignals(True)
        self._slider.setValue(self._float_to_int(v))
        self._slider.blockSignals(False)
        self.value_changed.emit(self.name, v)

    def _on_range_changed(self):
        self._min = self._min_box.value()
        self._max = self._max_box.value()
        self._spinbox.setRange(self._min, self._max)
        # Reposition slider at current value
        self._slider.blockSignals(True)
        self._slider.setValue(self._float_to_int(self._value))
        self._slider.blockSignals(False)

    def _on_play_toggled(self, checked: bool):
        if checked:
            self._play_btn.setText("‖")
            self._anim_dir = 1
            self._anim_timer.start()
        else:
            self._play_btn.setText("▷")
            self._anim_timer.stop()

    def _anim_tick(self):
        step = (self._max - self._min) / 200.0  # cross full range in ~3s at 60fps
        new_val = self._value + self._anim_dir * step
        if new_val >= self._max:
            new_val = self._max
            self._anim_dir = -1   # bounce
        elif new_val <= self._min:
            new_val = self._min
            self._anim_dir = 1
        self.set_value(new_val)
