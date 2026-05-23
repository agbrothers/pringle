"""
SliderWidget — a parameter slider cell for the equation panel.

Layout:
  Row 1: [color dot] [name]  [value ────────────────────────]  [✕]
  Row 2: [▷]  [min] [──●──────────────────────] [max]  · step [step]

Signals:
  value_changed(name, float)  — emitted whenever the slider moves
  delete_requested(cell_id)   — ✕ button clicked

Animation: play button bounces the value between min and max using the
step size set in the step box. ~60fps via QTimer.
"""

from __future__ import annotations

import uuid
from typing import Callable
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QWidget, QHBoxLayout, QLabel, QLineEdit, QSlider, QDoubleSpinBox,
    QPushButton, QFrame, QVBoxLayout, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from pringle.style import CellStyle, palette_color
from pringle.cell_widget import DragHandle
from pringle.preprocess import MAGIC_NAMES, SPATIAL_NAMES


class _ClickableLabel(QLabel):
    """QLabel that emits a clicked signal on mouse press."""
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class _SpinBox(QDoubleSpinBox):
    """QDoubleSpinBox with no step buttons and clean decimal display.

    Shows integers without a decimal point; strips trailing zeros from floats.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setDecimals(6)

    def textFromValue(self, v: float) -> str:
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return f"{v:g}"


class SliderWidget(QWidget):
    """Slider cell for a named scalar parameter."""

    value_changed = pyqtSignal(str, float)     # (name, value)
    name_changed = pyqtSignal(str, str, str)   # (old_name, new_name, cell_id)
    delete_requested = pyqtSignal(str)          # cell_id
    drag_started = pyqtSignal(str)              # cell_id
    drag_moved = pyqtSignal(str, int)           # cell_id, global_y
    drag_ended = pyqtSignal(str)                # cell_id

    _ANIM_INTERVAL_MS = 16   # ~60fps animation step

    def __init__(
        self,
        name: str,
        value: float = 1.0,
        min_val: float = 0.0,
        max_val: float = 10.0,
        step: float | None = None,
        cell_id: str | None = None,
        style: CellStyle | None = None,
        validate_name: Callable[[str], bool] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.cell_id: str = cell_id or str(uuid.uuid4())
        self.name: str = name
        self.style: CellStyle = style or CellStyle()
        self._validate_name: Callable[[str], bool] | None = validate_name
        self._name_edit: QLineEdit | None = None
        self._committing_name: bool = False

        # Expand the default range to accommodate the initial value so it
        # is never silently clipped on creation (e.g. typing `k = 15`).
        if value > max_val:
            max_val = value * 2 if value > 0 else 1.0
        elif value < min_val:
            min_val = value * 2 if value < 0 else -1.0

        self._value: float = value
        self._min: float = min_val
        self._max: float = max_val
        self._step: float = step if step is not None else max(0.001, (max_val - min_val) / 100.0)
        self._anim_dir: int = 1           # +1 or -1 for bounce
        self._anim_mode: str = "pingpong"  # "pingpong" | "loop"

        self._build_ui()

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(self._ANIM_INTERVAL_MS)
        self._anim_timer.timeout.connect(self._anim_tick)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setContentsMargins(0, 2, 0, 2)

        # Outer: drag handle strip (left) + content area (right)
        outer_h = QHBoxLayout(self)
        outer_h.setContentsMargins(0, 0, 0, 0)
        outer_h.setSpacing(0)

        self._drag_handle = DragHandle(self)
        self._drag_handle.drag_started.connect(lambda: self.drag_started.emit(self.cell_id))
        self._drag_handle.drag_moved.connect(lambda y: self.drag_moved.emit(self.cell_id, y))
        self._drag_handle.drag_ended.connect(lambda: self.drag_ended.emit(self.cell_id))
        outer_h.addWidget(self._drag_handle)

        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        outer_h.addWidget(content, 1)

        # --- Row 1: name + value spinbox (stretch) + delete ---
        row1 = QHBoxLayout()
        row1.setContentsMargins(4, 0, 6, 0)
        row1.setSpacing(6)
        self._row1 = row1

        self._name_label = _ClickableLabel(f"<b>{self.name}</b>")
        self._name_label.setFixedWidth(62)  # aligns spinbox with min_box below
        self._name_label.setCursor(Qt.CursorShape.IBeamCursor)
        self._name_label.setToolTip("Click to rename")
        self._name_label.clicked.connect(self._on_name_clicked)
        row1.addWidget(self._name_label)

        self._spinbox = _SpinBox()
        self._spinbox.setRange(self._min, self._max)
        self._spinbox.setValue(self._value)
        self._spinbox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._spinbox.valueChanged.connect(self._on_spinbox_changed)
        row1.addWidget(self._spinbox, 1)

        self._delete_btn = QPushButton("✕")
        self._delete_btn.setFixedSize(24, 24)
        self._delete_btn.setFlat(True)
        self._delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.cell_id))
        row1.addWidget(self._delete_btn)

        outer.addLayout(row1)

        # --- Row 2: play + min + slider (stretch) + max + · + step label + step ---
        row2 = QHBoxLayout()
        row2.setContentsMargins(4, 0, 6, 0)
        row2.setSpacing(6)

        self._play_btn = QPushButton("▷")
        self._play_btn.setFixedSize(28, 24)
        self._play_btn.setCheckable(True)
        self._play_btn.setToolTip("Animate")
        self._play_btn.clicked.connect(self._on_play_toggled)
        row2.addWidget(self._play_btn)

        self._mode_btn = QPushButton("↔")
        self._mode_btn.setFixedSize(28, 24)
        self._mode_btn.setToolTip("Ping-pong — click to switch to loop")
        self._mode_btn.clicked.connect(self._on_mode_toggled)
        row2.addWidget(self._mode_btn)

        self._min_box = _SpinBox()
        self._min_box.setRange(-1e6, 1e6)
        self._min_box.setValue(self._min)
        self._min_box.setFixedWidth(60)
        self._min_box.valueChanged.connect(self._on_range_changed)
        row2.addWidget(self._min_box)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setValue(self._float_to_int(self._value))
        self._slider.valueChanged.connect(self._on_slider_moved)
        row2.addWidget(self._slider, 1)

        self._max_box = _SpinBox()
        self._max_box.setRange(-1e6, 1e6)
        self._max_box.setValue(self._max)
        self._max_box.setFixedWidth(60)
        self._max_box.valueChanged.connect(self._on_range_changed)
        row2.addWidget(self._max_box)

        sep = QLabel("·")
        sep.setStyleSheet("color: #888; padding: 0 2px;")
        row2.addWidget(sep)

        step_lbl = QLabel("step")
        step_lbl.setStyleSheet("color: #888; font-size: 10px;")
        row2.addWidget(step_lbl)

        self._step_box = _SpinBox()
        self._step_box.setRange(1e-6, 1e6)
        self._step_box.setValue(self._step)
        self._step_box.setFixedWidth(60)
        row2.addWidget(self._step_box)

        outer.addLayout(row2)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #2a2a2a;")
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

    def set_name_validator(self, fn: Callable[[str], bool] | None) -> None:
        """Set a callback used to reject names already claimed by sibling sliders."""
        self._validate_name = fn

    # ------------------------------------------------------------------
    # Name editing
    # ------------------------------------------------------------------

    def _is_valid_rename(self, name: str) -> bool:
        return (
            bool(name)
            and name.isidentifier()
            and name not in MAGIC_NAMES
            and name not in SPATIAL_NAMES
            and (self._validate_name is None or self._validate_name(name))
        )

    def _on_name_clicked(self) -> None:
        if self._name_edit is not None:
            return
        self._name_edit = QLineEdit(self.name)
        self._name_edit.setFixedWidth(self._name_label.width())
        self._name_edit.selectAll()
        self._row1.replaceWidget(self._name_label, self._name_edit)
        self._name_label.hide()
        self._name_edit.textChanged.connect(self._on_name_text_changed)
        self._name_edit.editingFinished.connect(self._on_name_commit)
        self._name_edit.setFocus()

    def _on_name_text_changed(self, text: str) -> None:
        if self._name_edit is None:
            return
        valid = self._is_valid_rename(text.strip())
        self._name_edit.setStyleSheet("" if valid else "border: 1px solid #e05252;")

    def _on_name_commit(self) -> None:
        if self._committing_name or self._name_edit is None:
            return
        self._committing_name = True
        edit = self._name_edit
        self._name_edit = None
        edit.editingFinished.disconnect()

        new_name = edit.text().strip()
        self._row1.replaceWidget(edit, self._name_label)
        self._name_label.show()
        edit.deleteLater()
        self._committing_name = False

        if new_name != self.name and self._is_valid_rename(new_name):
            old_name = self.name
            self.name = new_name
            self._name_label.setText(f"<b>{new_name}</b>")
            self.name_changed.emit(old_name, new_name, self.cell_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _float_to_int(self, v: float) -> int:
        if self._max == self._min:
            return 0
        return int(round((v - self._min) / (self._max - self._min) * 1000))

    def _int_to_float(self, i: int) -> float:
        return self._min + (i / 1000.0) * (self._max - self._min)

    def _on_slider_moved(self, pos: int):
        v = self._int_to_float(pos)
        step = self._step_box.value()
        if step > 0:
            v = round(v / step) * step
        v = max(self._min, min(self._max, v))
        self._value = v
        self._spinbox.blockSignals(True)
        self._spinbox.setValue(v)
        self._spinbox.blockSignals(False)
        # Snap thumb to the quantized position
        self._slider.blockSignals(True)
        self._slider.setValue(self._float_to_int(v))
        self._slider.blockSignals(False)
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
        self._slider.blockSignals(True)
        self._slider.setValue(self._float_to_int(self._value))
        self._slider.blockSignals(False)

    def set_anim_mode(self, mode: str) -> None:
        self._anim_mode = mode if mode in ("pingpong", "loop") else "pingpong"
        if self._anim_mode == "loop":
            self._mode_btn.setText("⟳")
            self._mode_btn.setToolTip("Loop — click to switch to ping-pong")
        else:
            self._mode_btn.setText("↔")
            self._mode_btn.setToolTip("Ping-pong — click to switch to loop")

    def _on_mode_toggled(self):
        self.set_anim_mode("loop" if self._anim_mode == "pingpong" else "pingpong")

    def _on_play_toggled(self, checked: bool):
        if checked:
            self._play_btn.setText("‖")
            self._anim_dir = 1
            self._anim_timer.start()
        else:
            self._play_btn.setText("▷")
            self._anim_timer.stop()

    def _anim_tick(self):
        step = self._step_box.value()
        new_val = self._value + self._anim_dir * step
        if self._anim_mode == "loop":
            if new_val > self._max:
                new_val = self._min
            elif new_val < self._min:
                new_val = self._max
        else:  # pingpong
            if new_val >= self._max:
                new_val = self._max
                self._anim_dir = -1
            elif new_val <= self._min:
                new_val = self._min
                self._anim_dir = 1
        self.set_value(new_val)
