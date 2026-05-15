"""
CellWidget — a single expression cell in the equation panel.

Layout (horizontal):
  [color dot] [QPlainTextEdit] [+sub] [visibility eye] [delete ✕]

Below the text edit (conditionally):
  [ConstraintSubCell ...]  — indented sub-cells (constraint / condition)
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
    QLabel, QPlainTextEdit, QLineEdit, QSizePolicy, QFrame,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QColor, QPalette

from pringle.style import CellStyle, palette_color


# ---------------------------------------------------------------------------
# Constraint / condition sub-cell
# ---------------------------------------------------------------------------

class ConstraintSubCell(QWidget):
    """
    An indented sub-cell attached to a CellWidget.

    sub_type:
      "constraint" — boolean mask that sets z=NaN where False  (icon: ⊂)
      "condition"  — piecewise branch selector                  (icon: ≡)
    """

    content_changed = pyqtSignal()
    delete_requested = pyqtSignal()

    _ICONS = {"constraint": "⊂", "condition": "≡"}

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

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(
            "boolean expression (x, y, z in scope)"
            if self._sub_type == "constraint"
            else "condition expression (x, y in scope)"
        )
        self._edit.setStyleSheet(
            "QLineEdit { border: 1px dashed #bbb; border-radius: 3px; "
            "padding: 1px 4px; font-size: 12px; background: #fafafa; }"
        )
        self._edit.textChanged.connect(self.content_changed)
        row.addWidget(self._edit, 1)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(20, 20)
        del_btn.setFlat(True)
        del_btn.clicked.connect(self.delete_requested)
        row.addWidget(del_btn)

    def source(self) -> str:
        return self._edit.text()

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
    """
    enter_at_end = pyqtSignal()
    backspace_on_empty = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.document().contentsChanged.connect(self._adjust_height)
        self._adjust_height()

    def _adjust_height(self):
        doc_height = int(self.document().size().height())
        margins = self.contentsMargins()
        h = doc_height + margins.top() + margins.bottom() + 6
        self.setFixedHeight(max(h, 32))

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        mod = event.modifiers()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mod == Qt.KeyboardModifier.NoModifier:
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

    _DEBOUNCE_MS = 300

    def __init__(self, cell_id: str | None = None, style: CellStyle | None = None, parent=None):
        super().__init__(parent)
        self.cell_id: str = cell_id or str(uuid.uuid4())
        self.style: CellStyle = style or CellStyle()
        self._visible: bool = True
        self._sub_cells: list[ConstraintSubCell] = []

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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        # Top row: [dot] [text] [eye] [x]
        row = QHBoxLayout()
        row.setContentsMargins(6, 0, 6, 0)
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

        self._add_sub_btn = QPushButton("⊂")
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

        # Thin separator line below
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #ddd;")
        outer.addWidget(line)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def source(self) -> str:
        return self._text_edit.toPlainText()

    def set_source(self, text: str) -> None:
        self._text_edit.setPlainText(text)

    def set_error(self, msg: str | None) -> None:
        if msg:
            self._error_label.setText(f"⚠ {msg}")
            self._error_label.setVisible(True)
        else:
            self._error_label.setVisible(False)

    def set_warning(self, msg: str | None) -> None:
        if msg:
            self._warning_label.setText(f"⚠ {msg}")
            self._warning_label.setVisible(True)
        else:
            self._warning_label.setVisible(False)

    def clear_diagnostics(self) -> None:
        self.set_error(None)
        self.set_warning(None)

    def add_sub_cell(self, sub_type: str = "constraint") -> ConstraintSubCell:
        """Append a constraint or condition sub-cell below this cell."""
        sub = ConstraintSubCell(sub_type=sub_type, parent=self)
        sub.content_changed.connect(self._on_text_changed)
        sub.delete_requested.connect(lambda: self._remove_sub_cell(sub))
        self._sub_cells.append(sub)
        self._sub_layout.addWidget(sub)
        self._debounce.start()
        return sub

    def _remove_sub_cell(self, sub: ConstraintSubCell) -> None:
        if sub in self._sub_cells:
            self._sub_cells.remove(sub)
        self._sub_layout.removeWidget(sub)
        sub.deleteLater()
        self._debounce.start()

    def constraint_exprs(self) -> list[str]:
        return [s.source() for s in self._sub_cells if s.sub_type() == "constraint" and s.source().strip()]

    def condition_exprs(self) -> list[str]:
        return [s.source() for s in self._sub_cells if s.sub_type() == "condition" and s.source().strip()]

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
        r, g, b, _ = self.style.color
        hex_color = "#{:02x}{:02x}{:02x}".format(int(r*255), int(g*255), int(b*255))
        self._color_dot.setStyleSheet(
            f"QPushButton {{ background-color: {hex_color}; "
            f"border-radius: 9px; border: 1px solid rgba(0,0,0,0.15); }}"
            f"QPushButton:hover {{ border: 1px solid rgba(0,0,0,0.35); }}"
        )

    def _on_add_sub_clicked(self):
        menu = QMenu(self)
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
        self.content_changed.emit(self.cell_id)  # re-render with new visibility

    def _on_color_dot_clicked(self):
        from PyQt6.QtWidgets import QColorDialog
        r, g, b, a = self.style.color
        initial = QColor(int(r*255), int(g*255), int(b*255))
        color = QColorDialog.getColor(initial, self, "Choose color")
        if color.isValid():
            self.style.color = (
                color.red() / 255,
                color.green() / 255,
                color.blue() / 255,
                1.0,
            )
            self._update_color_dot()
            self.content_changed.emit(self.cell_id)  # update material color
