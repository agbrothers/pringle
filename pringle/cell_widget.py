"""
CellWidget — a single expression cell in the equation panel.

Layout (horizontal):
  [color dot] [QPlainTextEdit] [+sub] [visibility eye] [delete ✕]

Below the text edit (conditionally):
  [SubCell ...]  — indented sub-cells (constraint / condition / initial_condition / recursion)
  [error label]            — red, shown on eval error
  [warning label]          — orange, shown on shape mismatch or undefined variable

The widget emits:
  content_changed(cell_id)  — debounced 300ms after each keystroke
  delete_requested(cell_id) — when the ✕ button is clicked or Backspace
                              on an empty cell
  enter_pressed(cell_id)    — when Enter is pressed at end of text
                              (caller inserts a new cell below)
"""

from __future__ import annotations

import uuid
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QMenu,
    QLabel, QPlainTextEdit, QSizePolicy, QFrame,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QFont

from pringle.style import CellStyle


# ---------------------------------------------------------------------------
# Drag handle — left-edge strip for reordering cells
# ---------------------------------------------------------------------------

class DragHandle(QLabel):
    """14-px strip on the left of every cell. Shows ⠿ grip icon on hover;
    click-drag emits position signals for CellListWidget to reorder cells."""

    drag_started = pyqtSignal()
    drag_moved = pyqtSignal(int)   # global Y coordinate
    drag_ended = pyqtSignal()

    _IDLE   = "color: transparent; font-size: 14px; padding: 0;"
    _HOVER  = "color: #aaa; font-size: 14px; padding: 0;"
    _ACTIVE = "color: #666; font-size: 14px; padding: 0;"

    def __init__(self, parent=None):
        super().__init__("⠿", parent)
        self.setFixedWidth(14)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setStyleSheet(self._IDLE)
        self._dragging = False

    def enterEvent(self, event):
        if not self._dragging:
            self.setStyleSheet(self._HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._dragging:
            self.setStyleSheet(self._IDLE)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.setStyleSheet(self._ACTIVE)
            self.drag_started.emit()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.drag_moved.emit(event.globalPosition().toPoint().y())
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setStyleSheet(self._IDLE)
            self.drag_ended.emit()
        event.accept()


# ---------------------------------------------------------------------------
# Constraint / condition sub-cell
# ---------------------------------------------------------------------------

class SubCell(QWidget):
    """
    An indented sub-cell attached to a CellWidget.

    sub_type:
      "constraint" — boolean mask that sets z=NaN where False  (icon: ⊂)
      "condition"  — piecewise branch selector                  (icon: ≡)
    """

    content_changed = pyqtSignal()
    delete_requested = pyqtSignal()

    _ICONS = {
        "constraint":         "⊂",
        "condition":          "☰",
        "initial_condition":  "∅",
        "recursion":          "↺",
    }
    _PLACEHOLDERS = {
        "constraint":        "boolean expression (x, y, z in scope)",
        "condition":         "condition expression (x, y in scope)",
        "initial_condition": "initial condition, e.g. path[0] = array([1, 0])",
        "recursion":         "recurrence rule, e.g. path[n] = path[n-1] * 0.9",
    }

    def __init__(self, sub_type: str = "constraint", parent=None):
        super().__init__(parent)
        self._sub_type = sub_type
        self._build_ui()

    def _build_ui(self):
        row = QHBoxLayout(self)
        row.setContentsMargins(28, 1, 6, 1)
        row.setSpacing(4)

        icon = QLabel(self._ICONS.get(self._sub_type, "⊂"))
        icon.setStyleSheet("color: #888; font-size: 13px;")
        icon.setFixedWidth(16)
        row.addWidget(icon)

        self._edit = CellTextEdit(self, allow_newline=True)
        self._edit.setPlaceholderText(
            self._PLACEHOLDERS.get(self._sub_type, "expression")
        )
        self._edit.setStyleSheet(
            "QPlainTextEdit { border: 1px dashed #666; border-radius: 3px; "
            "padding: 1px 4px; font-size: 12px; color: #ddd; background: transparent; }"
        )
        self._edit.textChanged.connect(self.content_changed)
        row.addWidget(self._edit, 1)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(20, 20)
        del_btn.setFlat(True)
        del_btn.clicked.connect(self.delete_requested)
        row.addWidget(del_btn)

    def source(self) -> str:
        return self._edit.toPlainText()

    def sub_type(self) -> str:
        return self._sub_type


# ---------------------------------------------------------------------------
# Expanding text edit that emits Enter and Backspace signals
# ---------------------------------------------------------------------------

class CellTextEdit(QPlainTextEdit):
    """
    QPlainTextEdit that:
    - Expands vertically to fit content (no scrollbars)
    - Emits enter_at_end() when Enter is pressed at the end of text
    - Emits backspace_on_empty() when Backspace is pressed in an empty cell
    - Emits focus_lost() when keyboard focus leaves (used by data-mode cells)
    """
    enter_at_end = pyqtSignal()
    backspace_on_empty = pyqtSignal()
    focus_lost = pyqtSignal()

    def __init__(self, parent=None, allow_newline: bool = False):
        super().__init__(parent)
        self._allow_newline = allow_newline
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        _font = QFont()
        _font.setFamilies(['Menlo', 'Consolas', 'Courier New'])
        _font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(_font)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QPlainTextEdit { border: none; background: transparent; }")
        # documentSizeChanged fires after the layout engine has reflowed text
        # to the actual widget width — reliable for multi-line wrap.
        self.document().documentLayout().documentSizeChanged.connect(
            self._on_document_size_changed
        )
        self._adjust_height()

    def _on_document_size_changed(self, new_size) -> None:
        line_count = max(1, int(new_size.height()))
        line_h = self.fontMetrics().lineSpacing()
        dm = int(self.document().documentMargin())
        m = self.contentsMargins()
        h = line_count * line_h + 2 * dm + m.top() + m.bottom()
        self.setFixedHeight(max(h, 32))
        self.updateGeometry()

    def _adjust_height(self) -> None:
        """Initial sizing before documentSizeChanged has fired."""
        line_count = max(1, int(self.document().size().height()))
        line_h = self.fontMetrics().lineSpacing()
        dm = int(self.document().documentMargin())
        m = self.contentsMargins()
        h = line_count * line_h + 2 * dm + m.top() + m.bottom()
        self.setFixedHeight(max(h, 32))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._adjust_height()

    def focusOutEvent(self, event):
        self.focus_lost.emit()
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        mod = event.modifiers()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self._allow_newline and mod == Qt.KeyboardModifier.NoModifier:
                cursor = self.textCursor()
                at_end = cursor.atEnd()
                if at_end:
                    self.enter_at_end.emit()
                    return  # don't insert newline — move to next cell
            super().keyPressEvent(event)
            return

        if key == Qt.Key.Key_Backspace:
            if not self.toPlainText():
                self.backspace_on_empty.emit()
                return

        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Main cell widget
# ---------------------------------------------------------------------------

class CellWidget(QWidget):
    """One cell in the expression panel."""

    content_changed = pyqtSignal(str)      # cell_id
    delete_requested = pyqtSignal(str)     # cell_id
    enter_pressed = pyqtSignal(str)        # cell_id
    run_requested = pyqtSignal(str)        # cell_id (data-mode forced re-eval)
    drag_started = pyqtSignal(str)         # cell_id
    drag_moved = pyqtSignal(str, int)      # cell_id, global_y
    drag_ended = pyqtSignal(str)           # cell_id
    visibility_toggled = pyqtSignal(str, bool)  # cell_id, is_visible
    style_updated = pyqtSignal(str)        # cell_id — color/opacity/size changed, no re-eval needed

    _DEBOUNCE_MS = 300

    def __init__(self, cell_id: str | None = None, style: CellStyle | None = None, parent=None):
        super().__init__(parent)
        self.cell_id: str = cell_id or str(uuid.uuid4())
        self.style: CellStyle = style or CellStyle()
        self._visible: bool = True
        self._sub_cells: list[SubCell] = []
        self._data_mode: bool = False
        self._debounce_connected: bool = True  # textChanged → debounce connected

        self._build_ui()
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self._DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_changed)
        self._text_edit.textChanged.connect(self._on_text_changed)

    # ------------------------------------------------------------------
    # UI construction
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

        # Top row: [dot] [text] [eye] [+sub] [delete ✕]
        row = QHBoxLayout()
        row.setContentsMargins(4, 0, 6, 0)
        row.setSpacing(4)

        self._color_dot = QPushButton()
        self._color_dot.setFixedSize(18, 18)
        self._color_dot.setFlat(True)
        self._color_dot.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_color_dot()
        self._color_dot.clicked.connect(self._on_color_dot_clicked)
        row.addWidget(self._color_dot)

        self._text_edit = CellTextEdit(self)
        self._text_edit.enter_at_end.connect(lambda: self.enter_pressed.emit(self.cell_id))
        self._text_edit.backspace_on_empty.connect(lambda: self.delete_requested.emit(self.cell_id))
        row.addWidget(self._text_edit, 1)

        self._eye_btn = QPushButton("👁")
        self._eye_btn.setFixedSize(24, 24)
        self._eye_btn.setFlat(True)
        self._eye_btn.setCheckable(True)
        self._eye_btn.setChecked(True)
        self._eye_btn.setToolTip("Toggle visibility")
        self._eye_btn.clicked.connect(self._on_visibility_toggled)
        row.addWidget(self._eye_btn)

        self._add_sub_btn = QPushButton("+")
        self._add_sub_btn.setFixedSize(24, 24)
        self._add_sub_btn.setFlat(True)
        self._add_sub_btn.setToolTip("Add sub-cell")
        self._add_sub_btn.clicked.connect(self._on_add_sub_clicked)
        row.addWidget(self._add_sub_btn)

        self._delete_btn = QPushButton("✕")
        self._delete_btn.setFixedSize(24, 24)
        self._delete_btn.setFlat(True)
        self._delete_btn.setToolTip("Delete cell")
        self._delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.cell_id))
        row.addWidget(self._delete_btn)

        outer.addLayout(row)

        # Data row: run arrow + status dot (hidden until data mode is active)
        self._data_row = QWidget()
        data_rl = QHBoxLayout(self._data_row)
        data_rl.setContentsMargins(4, 0, 6, 2)
        data_rl.setSpacing(4)

        self._run_btn = QPushButton("→")
        self._run_btn.setFixedSize(28, 22)
        self._run_btn.setToolTip("Re-run cell")
        self._run_btn.clicked.connect(lambda: self.run_requested.emit(self.cell_id))
        data_rl.addWidget(self._run_btn)

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color: #bbb; font-size: 12px;")
        self._status_dot.setToolTip("Cell status")
        data_rl.addWidget(self._status_dot)
        data_rl.addStretch(1)

        self._data_row.setVisible(False)
        outer.addWidget(self._data_row)

        # Sub-cell container (empty initially)
        self._sub_container = QWidget()
        self._sub_layout = QVBoxLayout(self._sub_container)
        self._sub_layout.setContentsMargins(0, 0, 0, 0)
        self._sub_layout.setSpacing(1)
        outer.addWidget(self._sub_container)

        # Error label (hidden until needed)
        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(
            "color: #cc2222; font-size: 11px; padding: 2px 28px;"
        )
        self._error_label.setVisible(False)
        outer.addWidget(self._error_label)

        # Warning label (hidden until needed)
        self._warning_label = QLabel()
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet(
            "color: #cc7700; font-size: 11px; padding: 2px 28px;"
        )
        self._warning_label.setVisible(False)
        outer.addWidget(self._warning_label)

        # Preview row: value preview (left) + shape (right)
        preview_row = QHBoxLayout()
        preview_row.setContentsMargins(28, 0, 6, 0)
        preview_row.setSpacing(0)

        self._preview_label = QLabel()
        self._preview_label.setWordWrap(False)
        self._preview_label.setStyleSheet("color: #888; font-size: 11px;")
        self._preview_label.setVisible(False)
        preview_row.addWidget(self._preview_label, 1)

        self._shape_label = QLabel()
        self._shape_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._shape_label.setStyleSheet("color: #888; font-size: 11px;")
        self._shape_label.setVisible(False)
        preview_row.addWidget(self._shape_label)

        outer.addLayout(preview_row)

        # Thin separator line below
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #2a2a2a;")
        outer.addWidget(line)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def source(self) -> str:
        return self._text_edit.toPlainText()

    def set_source(self, text: str) -> None:
        self._text_edit.setPlainText(text)

    _DATA_DOT = {
        "idle":  "color: #bbb; font-size: 12px;",
        "ok":    "color: #2a8a2a; font-size: 12px; font-weight: bold;",
        "stale": "color: #cc7700; font-size: 12px;",
        "error": "color: #cc2222; font-size: 12px; font-weight: bold;",
    }

    def _set_data_status(self, state: str) -> None:
        if self._data_mode:
            self._status_dot.setStyleSheet(self._DATA_DOT.get(state, self._DATA_DOT["idle"]))

    def _mark_data_stale(self) -> None:
        self._set_data_status("stale")

    def set_error(self, msg: str | None) -> None:
        if msg:
            self._error_label.setText(f"⚠ {msg}")
            self._error_label.setVisible(True)
            self._set_data_status("error")
        else:
            self._error_label.setVisible(False)

    def set_warning(self, msg: str | None) -> None:
        if msg:
            self._warning_label.setText(f"⚠ {msg}")
            self._warning_label.setVisible(True)
            self._set_data_status("stale")
        else:
            self._warning_label.setVisible(False)

    def set_preview(self, value: str | None, shape: str | None = None) -> None:
        """Show value preview (left) and/or shape (right) in gray below the cell."""
        if value:
            self._preview_label.setText(value)
            self._preview_label.setVisible(True)
        else:
            self._preview_label.setVisible(False)
        if shape:
            self._shape_label.setText(shape)
            self._shape_label.setVisible(True)
        else:
            self._shape_label.setVisible(False)

    def clear_diagnostics(self) -> None:
        self.set_error(None)
        self.set_warning(None)
        self.set_preview(None, None)
        self._set_data_status("ok")

    def add_sub_cell(self, sub_type: str = "constraint") -> SubCell:
        """Append a constraint or condition sub-cell below this cell."""
        sub = SubCell(sub_type=sub_type, parent=self)
        sub.content_changed.connect(self._on_text_changed)
        sub.delete_requested.connect(lambda: self._remove_sub_cell(sub))
        self._sub_cells.append(sub)
        self._sub_layout.addWidget(sub)
        self._debounce.start()
        return sub

    def _remove_sub_cell(self, sub: SubCell) -> None:
        if sub in self._sub_cells:
            self._sub_cells.remove(sub)
        self._sub_layout.removeWidget(sub)
        sub.deleteLater()
        self._debounce.start()

    def constraint_exprs(self) -> list[str]:
        return [s.source() for s in self._sub_cells if s.sub_type() == "constraint" and s.source().strip()]

    def condition_exprs(self) -> list[str]:
        return [s.source() for s in self._sub_cells if s.sub_type() == "condition" and s.source().strip()]

    def recurrence_expr(self) -> str | None:
        for s in self._sub_cells:
            if s.sub_type() == "recursion" and s.source().strip():
                return s.source().strip()
        return None

    def initial_condition_exprs(self) -> list[str]:
        return [s.source() for s in self._sub_cells
                if s.sub_type() == "initial_condition" and s.source().strip()]

    def set_data_mode(self, enabled: bool, force: bool = False) -> None:
        """Switch cell between expression mode (auto-eval) and data-array mode (manual re-run).

        force=True: prompt user before removing incompatible sub-cells (explicit user action).
        force=False: silently remove incompatible sub-cells (passive inference from eval result).
        """
        if self._data_mode == enabled:
            return

        # Identify sub-cells incompatible with the target mode
        if enabled:
            incompatible = [s for s in self._sub_cells if s.sub_type() in ("constraint", "condition")]
        else:
            incompatible = [s for s in self._sub_cells if s.sub_type() in ("recursion", "initial_condition")]

        if incompatible:
            if force:
                from PyQt6.QtWidgets import QMessageBox
                mode_label = "data array" if enabled else "spatial expression"
                reply = QMessageBox.question(
                    self,
                    "Clear sub-cells?",
                    f"This cell now returns a {mode_label}. "
                    f"{len(incompatible)} sub-cell(s) of the wrong type will be removed. Continue?",
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            for sub in incompatible[:]:
                self._remove_sub_cell(sub)

        self._data_mode = enabled
        self._data_row.setVisible(enabled)

        if enabled and self._debounce_connected:
            self._text_edit.textChanged.disconnect(self._on_text_changed)
            self._text_edit.textChanged.connect(self._mark_data_stale)
            self._text_edit.focus_lost.connect(self._emit_changed)
            self._debounce_connected = False
        elif not enabled and not self._debounce_connected:
            self._text_edit.textChanged.disconnect(self._mark_data_stale)
            self._text_edit.textChanged.connect(self._on_text_changed)
            self._text_edit.focus_lost.disconnect(self._emit_changed)
            self._debounce_connected = True
            self._status_dot.setStyleSheet("color: #bbb; font-size: 12px;")

    def is_data_mode(self) -> bool:
        return self._data_mode

    def set_style(self, style: CellStyle) -> None:
        self.style = style
        self._update_color_dot()

    def is_visible_cell(self) -> bool:
        return self._visible

    def focus(self) -> None:
        self._text_edit.setFocus()
        cur = self._text_edit.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        self._text_edit.setTextCursor(cur)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_color_dot(self):
        if not self._visible:
            bg = "#333333"
        elif self.style.colormap:
            import matplotlib
            cmap = matplotlib.colormaps[self.style.colormap]
            if self.style.colormap_reversed:
                cmap = cmap.reversed()
            stops = ", ".join(
                f"stop:{i/5:.2f} #{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
                for i, (r, g, b, _) in ((i, cmap(i / 5)) for i in range(6))
            )
            bg = f"qlineargradient(x1:0, y1:0, x2:1, y2:0, {stops})"
        else:
            r, g, b, _ = self.style.color
            bg = "#{:02x}{:02x}{:02x}".format(int(r*255), int(g*255), int(b*255))
        self._color_dot.setStyleSheet(
            f"QPushButton {{ background: {bg}; "
            f"border-radius: 9px; border: 1px solid rgba(0,0,0,0.15); }}"
            f"QPushButton:hover {{ border: 1px solid rgba(0,0,0,0.35); }}"
        )

    def _on_add_sub_clicked(self):
        menu = QMenu(self)
        if self._data_mode:
            menu.addAction("Add Recursion Rule", lambda: self.add_sub_cell("recursion"))
            menu.addAction("Add Initial Condition", lambda: self.add_sub_cell("initial_condition"))
        else:
            menu.addAction("Add Constraint (filter surface)", lambda: self.add_sub_cell("constraint"))
            menu.addAction("Add Condition (piecewise branch)", lambda: self.add_sub_cell("condition"))
        menu.exec(self._add_sub_btn.mapToGlobal(
            self._add_sub_btn.rect().bottomLeft()
        ))

    def _on_text_changed(self):
        self._debounce.start()

    def _emit_changed(self):
        self.content_changed.emit(self.cell_id)

    def _on_visibility_toggled(self, checked: bool):
        self._visible = checked
        opacity = "1.0" if checked else "0.4"
        self._text_edit.setStyleSheet(f"opacity: {opacity};")
        self._update_color_dot()
        self.visibility_toggled.emit(self.cell_id, checked)

    def _on_color_dot_clicked(self):
        from pringle.style_popover import StylePopoverWidget
        popover = StylePopoverWidget(self.style, parent=self, show_render_mode=self._data_mode)
        popover.style_changed.connect(self._on_style_changed)
        pos = self._color_dot.mapToGlobal(self._color_dot.rect().bottomLeft())
        popover.move(pos)
        popover.show()

    def _on_style_changed(self, new_style):
        from dataclasses import replace
        self.style = replace(new_style)
        self._update_color_dot()
        self.style_updated.emit(self.cell_id)
