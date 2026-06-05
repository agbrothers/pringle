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
import numpy as np
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QApplication, QWidget, QHBoxLayout, QLabel, QLineEdit, QSlider,
    QDoubleSpinBox, QPushButton, QFrame, QVBoxLayout, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from pringle.style import CellStyle, palette_color
from pringle.cell_widget import DragHandle, ColorSwatchHandle
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
    new_cell_requested = pyqtSignal()
    folder_requested = pyqtSignal()
    navigate_up = pyqtSignal()
    navigate_down = pyqtSignal()
    navigate_left = pyqtSignal()        # Left at pos 0 → name field
    navigate_cell_down = pyqtSignal()   # Cmd+Down → skip row 2, exit cell below
    indent_at = pyqtSignal()
    outdent_at = pyqtSignal()
    move_up_at = pyqtSignal()
    move_down_at = pyqtSignal()
    toggle_comment_requested = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setDecimals(6)
        # QDoubleSpinBox defaults to WheelFocus, which means a scroll event gives
        # it focus before wheelEvent runs, making hasFocus() always True.
        # StrongFocus restricts focus acquisition to click/tab only.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def textFromValue(self, v: float) -> str:
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return f"{v:g}"

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mod = event.modifiers()
        ctrl  = Qt.KeyboardModifier.ControlModifier
        shift = Qt.KeyboardModifier.ShiftModifier
        alt   = Qt.KeyboardModifier.AltModifier
        if mod == ctrl:
            if key == Qt.Key.Key_Slash:
                self.toggle_comment_requested.emit()
                return
            if key == Qt.Key.Key_Up:
                self.navigate_up.emit()
                return
            if key == Qt.Key.Key_Down:
                self.navigate_cell_down.emit()
                return
        if mod == (ctrl | shift):
            if key == Qt.Key.Key_BracketRight:
                self.indent_at.emit()
                return
            if key == Qt.Key.Key_BracketLeft:
                self.outdent_at.emit()
                return
        if mod & alt:
            if key == Qt.Key.Key_Up:
                if mod & shift:
                    self.move_up_at.emit()
                return
            if key == Qt.Key.Key_Down:
                if mod & shift:
                    self.move_down_at.emit()
                return
        if key == Qt.Key.Key_Up:
            self.navigate_up.emit()
            return
        if key == Qt.Key.Key_Down:
            self.navigate_down.emit()
            return
        if key == Qt.Key.Key_Left and self.lineEdit().cursorPosition() == 0:
            self.navigate_left.emit()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mod == Qt.KeyboardModifier.ControlModifier:
                self.folder_requested.emit()
                return
            super().keyPressEvent(event)  # commits value via editingFinished
            if mod == Qt.KeyboardModifier.ShiftModifier:
                self.new_cell_requested.emit()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class _Slider(QSlider):
    """QSlider that only responds to wheel events when it has keyboard focus."""

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


def _fmt(v: float) -> str:
    """Format a float cleanly: integers without decimal point, others with %g."""
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:g}"


class _ExprBox(QLineEdit):
    """Numeric input that also accepts expression strings resolvable to a scalar."""
    committed = pyqtSignal(float)
    new_cell_requested = pyqtSignal()
    folder_requested = pyqtSignal()
    navigate_up = pyqtSignal()
    navigate_down = pyqtSignal()
    navigate_left = pyqtSignal()   # emitted when Left is pressed at position 0
    navigate_right = pyqtSignal()  # emitted when Right is pressed at end of text
    indent_at = pyqtSignal()
    outdent_at = pyqtSignal()
    move_up_at = pyqtSignal()
    move_down_at = pyqtSignal()
    toggle_comment_requested = pyqtSignal()

    def __init__(self, value: float = 0.0, parent=None):
        super().__init__(_fmt(value), parent)
        self._raw_expr: str | None = None
        self._last_valid: float = value
        self.editingFinished.connect(self._on_commit)

    def set_resolve(self, fn: Callable[[str], float | None]) -> None:
        self._resolve = fn

    def value(self) -> float:
        return self._last_valid

    def setValue(self, v: float) -> None:
        self._last_valid = v
        self._raw_expr = None
        self.setText(_fmt(v))

    def expr(self) -> str | None:
        return self._raw_expr

    def _on_commit(self) -> None:
        text = self.text().strip()
        try:
            v = float(text)
            self._last_valid = v
            self._raw_expr = None
            self.committed.emit(v)
            return
        except ValueError:
            pass
        resolved = self._resolve(text) if hasattr(self, "_resolve") else None
        if resolved is not None and isinstance(resolved, (int, float, np.floating, np.integer)) and np.isfinite(resolved):
            self._last_valid = float(resolved)
            self._raw_expr = text
            self.setText(text)
            self.committed.emit(self._last_valid)
        else:
            self.setText(self._raw_expr if self._raw_expr else _fmt(self._last_valid))
            self._indicate_error()

    def re_resolve(self, fn: Callable[[str], float | None]) -> None:
        if self._raw_expr is None:
            return
        resolved = fn(self._raw_expr)
        if resolved is not None and isinstance(resolved, (int, float, np.floating, np.integer)) and np.isfinite(resolved):
            self._last_valid = float(resolved)
            self.committed.emit(self._last_valid)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mod = event.modifiers()
        ctrl  = Qt.KeyboardModifier.ControlModifier
        shift = Qt.KeyboardModifier.ShiftModifier
        alt   = Qt.KeyboardModifier.AltModifier
        if mod == ctrl:
            if key == Qt.Key.Key_Slash:
                self.toggle_comment_requested.emit()
                return
        if mod == (ctrl | shift):
            if key == Qt.Key.Key_BracketRight:
                self.indent_at.emit()
                return
            if key == Qt.Key.Key_BracketLeft:
                self.outdent_at.emit()
                return
        if mod & alt:
            if key == Qt.Key.Key_Up:
                if mod & shift:
                    self.move_up_at.emit()
                return
            if key == Qt.Key.Key_Down:
                if mod & shift:
                    self.move_down_at.emit()
                return
        if key == Qt.Key.Key_Up:
            self.navigate_up.emit()
            return
        if key == Qt.Key.Key_Down:
            self.navigate_down.emit()
            return
        if key == Qt.Key.Key_Left and self.cursorPosition() == 0:
            self.navigate_left.emit()
            return
        if key == Qt.Key.Key_Right and self.cursorPosition() == len(self.text()):
            self.navigate_right.emit()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mod == Qt.KeyboardModifier.ControlModifier:
                self.folder_requested.emit()
                return
            self.editingFinished.emit()   # commits value
            if mod == Qt.KeyboardModifier.ShiftModifier:
                self.new_cell_requested.emit()
            return
        super().keyPressEvent(event)

    def _indicate_error(self) -> None:
        self.setStyleSheet("border: 1px solid #c0392b;")
        QTimer.singleShot(500, lambda: self.setStyleSheet(""))


class _NameLineEdit(QLineEdit):
    """Inline name editor for SliderWidget; Enter commits then requests a new cell."""
    new_cell_requested = pyqtSignal()
    folder_requested = pyqtSignal()
    navigate_up = pyqtSignal()
    navigate_down = pyqtSignal()
    navigate_left = pyqtSignal()        # Left at pos 0 → cell above
    navigate_right = pyqtSignal()       # Right at end → spinbox
    navigate_cell_down = pyqtSignal()   # Cmd+Down → cell below
    indent_at = pyqtSignal()
    outdent_at = pyqtSignal()
    move_up_at = pyqtSignal()
    move_down_at = pyqtSignal()
    toggle_comment_requested = pyqtSignal()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mod = event.modifiers()
        ctrl  = Qt.KeyboardModifier.ControlModifier
        shift = Qt.KeyboardModifier.ShiftModifier
        alt   = Qt.KeyboardModifier.AltModifier
        if mod == ctrl:
            if key == Qt.Key.Key_Slash:
                self.toggle_comment_requested.emit()
                return
        if mod == (ctrl | shift):
            if key == Qt.Key.Key_BracketRight:
                self.indent_at.emit()
                return
            if key == Qt.Key.Key_BracketLeft:
                self.outdent_at.emit()
                return
        if mod == ctrl:
            if key == Qt.Key.Key_Up:
                self.navigate_up.emit()
                return
            if key == Qt.Key.Key_Down:
                self.navigate_cell_down.emit()
                return
        if mod & alt:
            if key == Qt.Key.Key_Up:
                if mod & shift:
                    self.move_up_at.emit()
                return
            if key == Qt.Key.Key_Down:
                if mod & shift:
                    self.move_down_at.emit()
                return
        if key == Qt.Key.Key_Up:
            self.navigate_up.emit()
            return
        if key == Qt.Key.Key_Down:
            self.navigate_down.emit()
            return
        if key == Qt.Key.Key_Left and self.cursorPosition() == 0:
            self.navigate_left.emit()
            return
        if key == Qt.Key.Key_Right and self.cursorPosition() == len(self.text()):
            self.navigate_right.emit()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mod == Qt.KeyboardModifier.ControlModifier:
                self.folder_requested.emit()
                return
            self.editingFinished.emit()   # commits the name
            if mod == Qt.KeyboardModifier.ShiftModifier:
                self.new_cell_requested.emit()
            return
        super().keyPressEvent(event)


class SliderWidget(QWidget):
    """Slider cell for a named scalar parameter."""

    value_changed = pyqtSignal(str, float)     # (name, value)
    name_changed = pyqtSignal(str, str, str)   # (old_name, new_name, cell_id)
    enter_pressed = pyqtSignal(str)            # cell_id — Shift+Enter → new cell below
    new_folder_requested = pyqtSignal(str)     # cell_id — Ctrl+Enter → new folder below
    delete_requested = pyqtSignal(str)          # cell_id
    drag_started = pyqtSignal(str)              # cell_id
    drag_moved = pyqtSignal(str, int)           # cell_id, global_y
    drag_ended = pyqtSignal(str)                # cell_id
    navigate_up_requested = pyqtSignal(str)     # cell_id — exit slider upward
    navigate_down_requested = pyqtSignal(str)   # cell_id — exit slider downward
    indent_requested = pyqtSignal(str)          # cell_id — Cmd+] / Cmd+Right
    outdent_requested = pyqtSignal(str)         # cell_id — Cmd+[ / Cmd+Left
    move_up_requested = pyqtSignal(str)         # cell_id — Cmd+Up
    move_down_requested = pyqtSignal(str)       # cell_id — Cmd+Down
    toggle_comment_requested = pyqtSignal(str)  # cell_id — Cmd+/

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
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)  # FEAT-148
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
        self._anim_dir: int = 1                # +1 or -1 for bounce
        self._anim_mode: str = "pingpong"       # "pingpong" | "loop"
        self._anim_speed_multiplier: float = 1.0  # 0.5, 1.0, or 2.0

        self._build_ui()

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(self._ANIM_INTERVAL_MS)
        self._anim_timer.timeout.connect(self._anim_tick)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setContentsMargins(0, 0, 0, 0)

        top_v = QVBoxLayout(self)
        top_v.setContentsMargins(0, 0, 0, 0)
        top_v.setSpacing(0)

        # Outer: colored swatch strip (left) + content area (right)
        outer_h = QHBoxLayout()
        outer_h.setContentsMargins(0, 0, 0, 0)
        outer_h.setSpacing(0)
        top_v.addLayout(outer_h)

        self._swatch = ColorSwatchHandle(self.style, self)
        self._swatch.drag_started.connect(lambda: self.drag_started.emit(self.cell_id))
        self._swatch.drag_moved.connect(lambda y: self.drag_moved.emit(self.cell_id, y))
        self._swatch.drag_ended.connect(lambda: self.drag_ended.emit(self.cell_id))
        # Slider swatch click: open style popover
        self._swatch.style_requested.connect(self._on_style_requested)
        outer_h.addWidget(self._swatch)

        content = QWidget()
        content.setObjectName("cell_content")  # active-cell band target (FEAT-148)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        outer_h.addWidget(content, 1)

        # --- Row 1: name + value spinbox (stretch) + delete ---
        row1 = QHBoxLayout()
        row1.setContentsMargins(10, 0, 6, 0)
        row1.setSpacing(6)
        self._row1 = row1

        self._name_label = _ClickableLabel(f"<b>{self.name}</b>")
        self._name_label.setFixedWidth(62)  # aligns spinbox with min_box below
        self._name_label.setCursor(Qt.CursorShape.IBeamCursor)
        self._name_label.setToolTip("Click to rename")
        self._name_label.clicked.connect(self._on_name_clicked)
        row1.addWidget(self._name_label)

        self._spinbox = _SpinBox()
        self._spinbox.setRange(-1e12, 1e12)  # wide range — bounds are advisory, not clamping
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

        # --- Row 2: play + min + slider (stretch) + max + ↺ ---
        # play_wrap is fixed-width 62 to align min_box left with spinbox above
        row2 = QHBoxLayout()
        row2.setContentsMargins(6, 0, 6, 0)
        row2.setSpacing(6)

        play_wrap = QWidget()
        play_wrap.setFixedWidth(62)
        play_inner = QHBoxLayout(play_wrap)
        play_inner.setContentsMargins(0, 0, 0, 0)
        play_inner.setSpacing(0)
        self._play_btn = QPushButton("▷")
        self._play_btn.setFixedSize(28, 24)
        self._play_btn.setCheckable(True)
        self._play_btn.setToolTip("Animate")
        self._play_btn.clicked.connect(self._on_play_toggled)
        play_inner.addWidget(self._play_btn)
        play_inner.addStretch()
        row2.addWidget(play_wrap)

        self._min_box = _ExprBox(self._min)
        self._min_box.setFixedWidth(60)
        self._min_box.committed.connect(lambda _: self._on_range_changed())
        row2.addWidget(self._min_box)

        self._slider = _Slider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setValue(self._float_to_int(self._value))
        self._slider.valueChanged.connect(self._on_slider_moved)
        row2.addWidget(self._slider, 1)

        self._max_box = _ExprBox(self._max)
        self._max_box.setFixedWidth(60)
        self._max_box.committed.connect(lambda _: self._on_range_changed())
        row2.addWidget(self._max_box)

        self._controls_btn = QPushButton("↺")
        self._controls_btn.setObjectName("slider_controls_btn")
        self._controls_btn.setFixedSize(24, 24)
        self._controls_btn.setFlat(True)
        self._controls_btn.setToolTip("Step / speed / direction")
        self._controls_btn.clicked.connect(self._on_controls_clicked)
        row2.addWidget(self._controls_btn)

        outer.addLayout(row2)

        # _step_box, _mode_btn kept as attributes for session.py access, not in layout
        self._step_box = _ExprBox(self._step)
        self._mode_btn = QPushButton("↔")  # kept for anim_mode API compatibility

        # Arrow-key cross-cell navigation
        self._spinbox.navigate_up.connect(lambda: self.navigate_up_requested.emit(self.cell_id))
        self._spinbox.navigate_down.connect(lambda: self._min_box.setFocus())
        self._spinbox.navigate_left.connect(self._focus_name_edit_at_end)
        self._spinbox.navigate_cell_down.connect(lambda: self.navigate_down_requested.emit(self.cell_id))
        self._min_box.navigate_up.connect(lambda: self._spinbox.setFocus())
        self._min_box.navigate_down.connect(lambda: self.navigate_down_requested.emit(self.cell_id))
        self._min_box.navigate_right.connect(
            lambda: (self._max_box.setFocus(), self._max_box.setCursorPosition(0))
        )
        self._max_box.navigate_up.connect(lambda: self._spinbox.setFocus())
        self._max_box.navigate_down.connect(lambda: self.navigate_down_requested.emit(self.cell_id))
        self._max_box.navigate_left.connect(
            lambda: (self._min_box.setFocus(),
                     self._min_box.setCursorPosition(len(self._min_box.text())))
        )

        # Cell movement / creation from any focused field
        for _field in (self._spinbox, self._min_box, self._max_box):
            _field.indent_at.connect(lambda: self.indent_requested.emit(self.cell_id))
            _field.outdent_at.connect(lambda: self.outdent_requested.emit(self.cell_id))
            _field.move_up_at.connect(lambda: self.move_up_requested.emit(self.cell_id))
            _field.move_down_at.connect(lambda: self.move_down_requested.emit(self.cell_id))
            _field.toggle_comment_requested.connect(lambda: self.toggle_comment_requested.emit(self.cell_id))
            _field.new_cell_requested.connect(lambda: self.enter_pressed.emit(self.cell_id))
            _field.folder_requested.connect(lambda: self.new_folder_requested.emit(self.cell_id))

        # Separator outside outer_h so the swatch doesn't cover it
        line = QFrame()
        line.setObjectName("separator")
        line.setFrameShape(QFrame.Shape.HLine)
        top_v.addWidget(line)

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
        self._spinbox.setFocus()

    def primary_focus_widget(self) -> "_SpinBox":
        return self._spinbox

    def set_error(self, msg: str | None) -> None:
        pass

    def set_warning(self, msg: str | None) -> None:
        pass

    def clear_diagnostics(self) -> None:
        pass

    def set_value(self, v: float, emit: bool = True) -> None:
        self._value = v
        self._spinbox.blockSignals(True)
        self._slider.blockSignals(True)
        self._spinbox.setValue(v)
        self._slider.setValue(self._float_to_int(v))  # QSlider clamps handle to track
        self._spinbox.blockSignals(False)
        self._slider.blockSignals(False)
        self._validate_bounds()
        if emit:
            self.value_changed.emit(self.name, v)

    def set_name_validator(self, fn: Callable[[str], bool] | None) -> None:
        """Set a callback used to reject names already claimed by sibling sliders."""
        self._validate_name = fn

    def refresh_swatch(self) -> None:
        self._swatch.set_style(self.style)

    def _on_style_requested(self) -> None:
        from pringle.style_popover import StylePopoverWidget
        popover = StylePopoverWidget(self.style, parent=self)
        popover.style_changed.connect(self._on_style_changed)
        popover.color_picker_requested.connect(self._open_color_picker)
        pos = self._swatch.mapToGlobal(self._swatch.rect().bottomLeft())
        hint_h = popover.sizeHint().height()
        if pos.y() + hint_h > self._swatch.screen().availableGeometry().bottom():
            pos = self._swatch.mapToGlobal(self._swatch.rect().topLeft())
            pos.setY(pos.y() - hint_h)
        popover.move(pos)
        popover.show()

    def _on_style_changed(self, new_style) -> None:
        from dataclasses import replace
        self.style = replace(new_style)
        self.refresh_swatch()

    def _open_color_picker(self) -> None:
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor
        from dataclasses import replace
        original_color = self.style.color
        r, g, b, _ = original_color
        dlg = QColorDialog(QColor.fromRgbF(r, g, b), self)

        def _apply(qcolor: QColor) -> None:
            self._on_style_changed(replace(self.style, color=(
                qcolor.redF(), qcolor.greenF(), qcolor.blueF(), self.style.color[3],
            )))

        dlg.currentColorChanged.connect(_apply)
        if not dlg.exec():
            self._on_style_changed(replace(self.style, color=original_color))

    def set_resolver(self, fn: Callable[[str], float | None]) -> None:
        """Inject namespace resolver into all bound boxes."""
        self._min_box.set_resolve(fn)
        self._max_box.set_resolve(fn)
        self._step_box.set_resolve(fn)

    def re_resolve(self, fn: Callable[[str], float | None]) -> None:
        """Re-evaluate stored expression strings against a fresh namespace."""
        self._min_box.re_resolve(fn)
        self._max_box.re_resolve(fn)
        self._step_box.re_resolve(fn)

    def min_expr(self) -> str | None:
        return self._min_box.expr()

    def max_expr(self) -> str | None:
        return self._max_box.expr()

    def step_expr(self) -> str | None:
        return self._step_box.expr()

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

    def _focus_name_edit_at_end(self) -> None:
        """Focus the name field (creating it if needed) with cursor at end of text."""
        if self._name_edit is None:
            self._on_name_clicked()
        self._name_edit.setFocus()
        self._name_edit.setCursorPosition(len(self._name_edit.text()))

    def _on_name_clicked(self) -> None:
        if self._name_edit is not None:
            return
        self._name_edit = _NameLineEdit(self.name)
        self._name_edit.setFixedWidth(self._name_label.width())
        self._name_edit.selectAll()
        self._row1.replaceWidget(self._name_label, self._name_edit)
        self._name_label.hide()
        self._name_edit.textChanged.connect(self._on_name_text_changed)
        self._name_edit.editingFinished.connect(self._on_name_commit)
        self._name_edit.new_cell_requested.connect(lambda: self.enter_pressed.emit(self.cell_id))
        self._name_edit.folder_requested.connect(lambda: self.new_folder_requested.emit(self.cell_id))
        self._name_edit.indent_at.connect(lambda: self.indent_requested.emit(self.cell_id))
        self._name_edit.outdent_at.connect(lambda: self.outdent_requested.emit(self.cell_id))
        self._name_edit.move_up_at.connect(lambda: self.move_up_requested.emit(self.cell_id))
        self._name_edit.move_down_at.connect(lambda: self.move_down_requested.emit(self.cell_id))
        self._name_edit.toggle_comment_requested.connect(lambda: self.toggle_comment_requested.emit(self.cell_id))
        self._name_edit.navigate_up.connect(lambda: self.navigate_up_requested.emit(self.cell_id))
        self._name_edit.navigate_left.connect(lambda: self.navigate_up_requested.emit(self.cell_id))
        self._name_edit.navigate_down.connect(lambda: self._min_box.setFocus())
        self._name_edit.navigate_right.connect(
            lambda: (self._spinbox.setFocus(),
                     self._spinbox.lineEdit().setCursorPosition(0))
        )
        self._name_edit.navigate_cell_down.connect(
            lambda: self.navigate_down_requested.emit(self.cell_id)
        )
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
        self._validate_bounds()
        self.value_changed.emit(self.name, v)

    def _on_range_changed(self):
        self._min = self._min_box.value()
        self._max = self._max_box.value()
        self._slider.blockSignals(True)
        self._slider.setValue(self._float_to_int(self._value))
        self._slider.blockSignals(False)
        self._validate_bounds()

    def _validate_bounds(self) -> None:
        """Flag min/max fields red when they conflict with the current value."""
        red = "border: 1px solid #c0392b;"
        self._min_box.setStyleSheet(red if self._value < self._min else "")
        self._max_box.setStyleSheet(red if self._value > self._max else "")

    def _on_controls_clicked(self) -> None:
        from pringle.slider_controls_popover import SliderControlsPopover
        popover = SliderControlsPopover(self, parent=self)
        hint = popover.sizeHint()
        pos = self._controls_btn.mapToGlobal(self._controls_btn.rect().bottomRight())
        x = pos.x() - hint.width()
        if pos.y() + 4 + hint.height() > self._controls_btn.screen().availableGeometry().bottom():
            top = self._controls_btn.mapToGlobal(self._controls_btn.rect().topRight())
            y = top.y() - hint.height()
        else:
            y = pos.y() + 4
        popover.move(x, y)
        popover.show()

    def set_anim_mode(self, mode: str) -> None:
        self._anim_mode = mode if mode in ("pingpong", "loop") else "pingpong"

    def set_anim_speed_multiplier(self, multiplier: float) -> None:
        _VALID = {0.5, 1.0, 2.0}
        self._anim_speed_multiplier = multiplier if multiplier in _VALID else 1.0
        # Apply new interval if currently animating
        interval_ms = int(self._ANIM_INTERVAL_MS / self._anim_speed_multiplier)
        self._anim_timer.setInterval(interval_ms)

    def _on_mode_toggled(self):
        self.set_anim_mode("loop" if self._anim_mode == "pingpong" else "pingpong")

    def _on_play_toggled(self, checked: bool):
        if checked:
            self._play_btn.setText("‖")
            self._anim_dir = 1
            interval_ms = int(self._ANIM_INTERVAL_MS / self._anim_speed_multiplier)
            self._anim_timer.setInterval(interval_ms)
            self._anim_timer.start()
        else:
            self._play_btn.setText("▷")
            self._anim_timer.stop()

    def _anim_tick(self):
        # Skip animation step while a modal dialog holds the event loop (BUG-074).
        if QApplication.activeModalWidget() is not None:
            return
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
