"""
CellWidget — a single expression cell in the equation panel.

Layout (horizontal):
  [ColorSwatchHandle 10px] [QFrame — expression row + sub-cells + labels]

The widget emits:
  content_changed(cell_id)  — debounced 300ms after each keystroke
  delete_requested(cell_id) — ✕ button or Backspace on empty cell
  enter_pressed(cell_id)    — Enter at end of text
"""

from __future__ import annotations

import math
import uuid
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QMenu,
    QLabel, QPlainTextEdit, QSizePolicy, QFrame,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt6.QtGui import (
    QKeyEvent, QFont, QFontMetricsF,
    QPainter, QColor, QLinearGradient, QBrush,
)

from pringle.style import CellStyle


# ---------------------------------------------------------------------------
# DragHandle — kept for SliderWidget / FolderCellWidget compatibility
# ---------------------------------------------------------------------------

class DragHandle(QLabel):
    """14-px strip; click-drag emits position signals for reordering."""

    drag_started = pyqtSignal()
    drag_moved = pyqtSignal(int)
    drag_ended = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("⠿", parent)
        self.setFixedWidth(14)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self._dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.setStyleSheet("color: #666; font-size: 14px; padding: 0;")
            self.drag_started.emit()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.drag_moved.emit(event.globalPosition().toPoint().y())
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setStyleSheet("")
            self.drag_ended.emit()
        event.accept()


# ---------------------------------------------------------------------------
# ColorSwatchHandle — 10-px colored strip; click → style popover, hold → drag
# ---------------------------------------------------------------------------

class ColorSwatchHandle(QWidget):
    """
    10-px wide left-edge strip for equation cells.

    Short press (< 300 ms): emits style_requested (opens style popover).
    Long press / hold: emits drag_started / drag_moved / drag_ended for reorder.
    Color fill: solid CellStyle.color, or vertical colormap gradient when active.
    """

    drag_started   = pyqtSignal()
    drag_moved     = pyqtSignal(int)   # global Y
    drag_ended     = pyqtSignal()
    style_requested = pyqtSignal()

    _HOLD_MS = 300
    _MIN_DRAG_PX = 4

    def __init__(self, style: CellStyle, parent=None):
        super().__init__(parent)
        self._style = style
        self.setFixedWidth(10)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self._is_dragging = False
        self._press_pos: QPoint | None = None
        self._hold_timer: QTimer | None = None

    def set_style(self, style: CellStyle) -> None:
        self._style = style
        self.update()

    def set_visible(self, visible: bool) -> None:
        self._cell_visible = visible
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        rect = self.rect()

        if getattr(self, "_cell_visible", True) is False:
            painter.fillRect(rect, QColor("#222222"))
            return

        if self._style.colormap:
            import matplotlib
            import numpy as np
            cmap = matplotlib.colormaps[self._style.colormap]
            if self._style.colormap_reversed:
                cmap = cmap.reversed()
            gradient = QLinearGradient(0, 0, 0, rect.height())
            for t in np.linspace(0, 1, 8):
                r, g, b, a = cmap(float(t))
                gradient.setColorAt(float(t), QColor.fromRgbF(r, g, b, a))
            painter.fillRect(rect, QBrush(gradient))
        else:
            r, g, b, a = self._style.color
            painter.fillRect(rect, QColor.fromRgbF(r, g, b))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._is_dragging = False
            self._hold_timer = QTimer(self)
            self._hold_timer.setSingleShot(True)
            self._hold_timer.timeout.connect(self._begin_drag)
            self._hold_timer.start(self._HOLD_MS)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._hold_timer and self._hold_timer.isActive():
                self._hold_timer.stop()
                self.style_requested.emit()
            elif self._is_dragging:
                self.drag_ended.emit()
            self._is_dragging = False
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._is_dragging and self._press_pos is not None:
            cur = event.globalPosition().toPoint()
            if (cur - self._press_pos).manhattanLength() > self._MIN_DRAG_PX:
                self.drag_moved.emit(cur.y())
        event.accept()

    def _begin_drag(self) -> None:
        self._is_dragging = True
        self.drag_started.emit()


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
        self.cell_id: str = str(uuid.uuid4())
        self._sub_type = sub_type
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("SubCell { border-top: 1px dashed #444; }")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 6, 2)
        row.setSpacing(4)

        icon = QLabel(self._ICONS.get(self._sub_type, "⊂"))
        icon.setObjectName("subcell_icon")
        icon.setFixedWidth(10)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(icon)

        self._edit = CellTextEdit(self, allow_newline=True)
        self._edit.setPlaceholderText(
            self._PLACEHOLDERS.get(self._sub_type, "expression")
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

    def primary_focus_widget(self) -> "CellTextEdit":
        return self._edit


# ---------------------------------------------------------------------------
# Expanding text edit that emits Enter and Backspace signals
# ---------------------------------------------------------------------------

_WRAP_PAIRS: dict[int, tuple[str, str]] = {
    Qt.Key.Key_ParenLeft:   ('(', ')'),
    Qt.Key.Key_BracketLeft: ('[', ']'),
    Qt.Key.Key_BraceLeft:   ('{', '}'),
    Qt.Key.Key_Apostrophe:  ("'", "'"),
    Qt.Key.Key_QuoteDbl:    ('"', '"'),
    Qt.Key.Key_QuoteLeft:   ('`', '`'),
}


class CellTextEdit(QPlainTextEdit):
    """
    QPlainTextEdit that:
    - Expands vertically to fit content (no scrollbars)
    - Emits enter_at_end() when Enter is pressed at the end of text
    - Emits backspace_on_empty() when Backspace is pressed in an empty cell
    - Emits focus_lost() when keyboard focus leaves (used by data-mode cells)
    - Emits navigate_down/up_requested() when arrow key is pressed at boundary line
    """
    enter_at_end = pyqtSignal()
    backspace_on_empty = pyqtSignal()
    focus_lost = pyqtSignal()
    folder_requested = pyqtSignal()
    navigate_down_requested = pyqtSignal()
    navigate_up_requested = pyqtSignal()
    indent_at = pyqtSignal()
    outdent_at = pyqtSignal()
    move_up_at = pyqtSignal()
    move_down_at = pyqtSignal()

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
        self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(' ') * 4)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # documentSizeChanged fires after the layout engine has reflowed text
        # to the actual widget width — reliable for multi-line wrap.
        self.document().documentLayout().documentSizeChanged.connect(
            self._on_document_size_changed
        )
        from pringle.syntax_highlighter import PringleHighlighter
        self._highlighter = PringleHighlighter(self.document())
        self._adjust_height()

    def _on_document_size_changed(self, _new_size) -> None:
        # Sum actual block heights from the layout engine — exact regardless of line count.
        # +2px: prevents ensureCursorVisible from scrolling when cursor is on the last line.
        layout = self.document().documentLayout()
        total_h = 0.0
        block = self.document().begin()
        while block.isValid():
            total_h += layout.blockBoundingRect(block).height()
            block = block.next()
        dm = int(self.document().documentMargin())
        m = self.contentsMargins()
        h = math.ceil(total_h) + 2 * dm + m.top() + m.bottom() + 2
        self.setFixedHeight(max(h, 32))
        self.updateGeometry()

    def _adjust_height(self) -> None:
        """Font-metrics estimate used before documentSizeChanged has first fired."""
        line_count = max(1, math.ceil(self.document().size().height()))
        line_h = self.fontMetrics().lineSpacing()
        dm = int(self.document().documentMargin())
        m = self.contentsMargins()
        h = line_count * line_h + 2 * dm + m.top() + m.bottom() + 2
        self.setFixedHeight(max(h, 32))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Explicitly recompute after every width change. super() runs a synchronous
        # document relayout so blockBoundingRect is accurate immediately afterward —
        # we don't need to wait for the documentSizeChanged signal, which may be
        # deferred on some Qt builds/platforms. If the signal did fire synchronously
        # inside super() and already set the correct height, this call is a no-op
        # (same blockBoundingRect values, same setFixedHeight result).
        self._on_document_size_changed(None)

    def _toggle_line_comment(self) -> None:
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        # Collect all blocks that overlap the selection (or just the cursor's block).
        doc = self.document()
        first_block = doc.findBlock(start)
        last_block = doc.findBlock(end if end > start else start)

        blocks = []
        b = first_block
        while True:
            blocks.append(b)
            if b == last_block:
                break
            b = b.next()

        all_commented = all(b.text().startswith("# ") for b in blocks)

        cursor.beginEditBlock()
        for b in blocks:
            bc = self.textCursor()
            bc.setPosition(b.position())
            if all_commented:
                bc.movePosition(bc.MoveOperation.Right, bc.MoveMode.KeepAnchor, 2)
                bc.removeSelectedText()
            else:
                bc.insertText("# ")
        cursor.endEditBlock()

    def focusOutEvent(self, event):
        self.focus_lost.emit()
        super().focusOutEvent(event)

    def wheelEvent(self, event) -> None:
        event.ignore()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        mod = event.modifiers()

        if key == Qt.Key.Key_Tab:
            self.insertPlainText("    ")
            return

        ctrl = Qt.KeyboardModifier.ControlModifier
        alt = Qt.KeyboardModifier.AltModifier
        if mod == ctrl:
            if key == Qt.Key.Key_BracketRight:
                self.indent_at.emit()
                return
            if key == Qt.Key.Key_BracketLeft:
                self.outdent_at.emit()
                return
            if key == Qt.Key.Key_Slash:
                self._toggle_line_comment()
                return
        if mod & alt:
            if key == Qt.Key.Key_Up:
                self.move_up_at.emit()
                return
            if key == Qt.Key.Key_Down:
                self.move_down_at.emit()
                return

        if key in _WRAP_PAIRS and self.textCursor().hasSelection():
            open_, close = _WRAP_PAIRS[key]
            cursor = self.textCursor()
            cursor.insertText(open_ + cursor.selectedText() + close)
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self._allow_newline:
                if mod == Qt.KeyboardModifier.ControlModifier:
                    self.folder_requested.emit()
                    return
                if mod == Qt.KeyboardModifier.NoModifier:
                    self.enter_at_end.emit()   # new cell below (any cursor position)
                    return
                # Shift+Enter falls through to super → inserts newline
            super().keyPressEvent(event)
            return

        if key == Qt.Key.Key_Backspace:
            if not self.toPlainText():
                self.backspace_on_empty.emit()
                return

        if key == Qt.Key.Key_Down:
            if self.textCursor().blockNumber() == self.document().blockCount() - 1:
                self.navigate_down_requested.emit()
                return
        elif key == Qt.Key.Key_Up:
            if self.textCursor().blockNumber() == 0:
                self.navigate_up_requested.emit()
                return

        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Main cell widget
# ---------------------------------------------------------------------------

class CellWidget(QWidget):
    """One cell in the expression panel."""

    content_changed = pyqtSignal(str)      # cell_id
    commit_requested = pyqtSignal(str)     # cell_id — fires on focus-out (deferred morph check)
    delete_requested = pyqtSignal(str)     # cell_id
    enter_pressed = pyqtSignal(str)        # cell_id
    new_folder_requested = pyqtSignal(str) # cell_id
    run_requested = pyqtSignal(str)        # cell_id (data-mode forced re-eval)
    drag_started = pyqtSignal(str)         # cell_id
    drag_moved = pyqtSignal(str, int)      # cell_id, global_y
    drag_ended = pyqtSignal(str)           # cell_id
    visibility_toggled = pyqtSignal(str, bool)  # cell_id, is_visible
    style_updated = pyqtSignal(str)        # cell_id — color/opacity/size changed, no re-eval needed
    navigate_down_requested = pyqtSignal(str)  # cell_id or subcell_id
    navigate_up_requested = pyqtSignal(str)    # cell_id or subcell_id
    indent_requested = pyqtSignal(str)         # cell_id — Cmd+] / Cmd+Right
    outdent_requested = pyqtSignal(str)        # cell_id — Cmd+[ / Cmd+Left
    move_up_requested = pyqtSignal(str)        # cell_id — Cmd+Up
    move_down_requested = pyqtSignal(str)      # cell_id — Cmd+Down

    _DEBOUNCE_MS = 300

    def __init__(self, cell_id: str | None = None, style: CellStyle | None = None, parent=None):
        super().__init__(parent)
        # Paint the stylesheet background on the root so the active-cell
        # highlight (FEAT-148) covers the whole cell band, swatch included.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.cell_id: str = cell_id or str(uuid.uuid4())
        self.style: CellStyle = style or CellStyle()
        self._visible: bool = True
        self._sub_cells: list[SubCell] = []
        self._data_mode: bool = False
        self._def_mode: bool = False
        self._is_vector_cell: bool = False
        self._debounce_connected: bool = True  # textChanged → debounce connected
        self._rng_seed: int = 0  # increments on each → press; seeds per-cell RandomState

        self._build_ui()
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self._DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_changed)
        self._text_edit.textChanged.connect(self._on_text_changed)
        self._text_edit.focus_lost.connect(lambda: self.commit_requested.emit(self.cell_id))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setContentsMargins(0, 0, 0, 0)

        top_v = QVBoxLayout(self)
        top_v.setContentsMargins(0, 0, 0, 0)
        top_v.setSpacing(0)

        # Outer: swatch strip (left) + content area (right)
        outer_h = QHBoxLayout()
        outer_h.setContentsMargins(0, 0, 0, 0)
        outer_h.setSpacing(0)
        top_v.addLayout(outer_h)

        self._swatch = ColorSwatchHandle(self.style, self)
        self._swatch.drag_started.connect(lambda: self.drag_started.emit(self.cell_id))
        self._swatch.drag_moved.connect(lambda y: self.drag_moved.emit(self.cell_id, y))
        self._swatch.drag_ended.connect(lambda: self.drag_ended.emit(self.cell_id))
        self._swatch.style_requested.connect(self._on_style_requested)
        outer_h.addWidget(self._swatch)

        content = QWidget()
        content.setObjectName("cell_content")  # active-cell band target (FEAT-148)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        outer_h.addWidget(content, 1)

        # _outer_frame: dashed border appears when sub-cells are present (Phase 4)
        self._outer_frame = QFrame()
        self._outer_frame.setObjectName("cellFrame")
        outer = QVBoxLayout(self._outer_frame)
        outer.setContentsMargins(0, 2, 0, 6)
        outer.setSpacing(2)
        content_layout.addWidget(self._outer_frame)

        # Top row: [text] [+sub] [delete ✕]
        row = QHBoxLayout()
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(4)

        self._text_edit = CellTextEdit(self)
        self._text_edit.enter_at_end.connect(lambda: self.enter_pressed.emit(self.cell_id))
        self._text_edit.folder_requested.connect(lambda: self.new_folder_requested.emit(self.cell_id))
        self._text_edit.backspace_on_empty.connect(lambda: self.delete_requested.emit(self.cell_id))
        self._text_edit.navigate_down_requested.connect(lambda: self.navigate_down_requested.emit(self.cell_id))
        self._text_edit.navigate_up_requested.connect(lambda: self.navigate_up_requested.emit(self.cell_id))
        self._text_edit.indent_at.connect(lambda: self.indent_requested.emit(self.cell_id))
        self._text_edit.outdent_at.connect(lambda: self.outdent_requested.emit(self.cell_id))
        self._text_edit.move_up_at.connect(lambda: self.move_up_requested.emit(self.cell_id))
        self._text_edit.move_down_at.connect(lambda: self.move_down_requested.emit(self.cell_id))
        row.addWidget(self._text_edit, 1)

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
        data_rl.setContentsMargins(6, 0, 6, 2)
        data_rl.setSpacing(4)

        self._run_btn = QPushButton("→")
        self._run_btn.setFixedSize(28, 22)
        self._run_btn.setToolTip("Re-run cell")
        self._run_btn.clicked.connect(lambda: self.run_requested.emit(self.cell_id))
        data_rl.addWidget(self._run_btn)

        self._status_dot = QLabel("●")
        self._status_dot.setObjectName("status_dot")
        self._status_dot.setToolTip("Cell status")
        data_rl.addWidget(self._status_dot)
        data_rl.addStretch(1)

        self._data_row.setVisible(False)
        outer.addWidget(self._data_row)

        # Sub-cell container (empty initially)
        self._sub_container = QWidget()
        self._sub_layout = QVBoxLayout(self._sub_container)
        self._sub_layout.setContentsMargins(0, 0, 0, 0)
        self._sub_layout.setSpacing(0)
        outer.addWidget(self._sub_container)

        # Error label (hidden until needed)
        self._error_label = QLabel()
        self._error_label.setObjectName("error_label")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        outer.addWidget(self._error_label)

        # Warning label (hidden until needed)
        self._warning_label = QLabel()
        self._warning_label.setObjectName("warning_label")
        self._warning_label.setWordWrap(True)
        self._warning_label.setVisible(False)
        outer.addWidget(self._warning_label)

        # Preview row: value preview (left) + shape (right)
        preview_row = QHBoxLayout()
        preview_row.setContentsMargins(6, 0, 6, 0)
        preview_row.setSpacing(0)

        self._preview_label = QLabel()
        self._preview_label.setObjectName("preview_label")
        self._preview_label.setWordWrap(False)
        self._preview_label.setVisible(False)
        preview_row.addWidget(self._preview_label, 1)

        self._shape_label = QLabel()
        self._shape_label.setObjectName("shape_label")
        self._shape_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._shape_label.setVisible(False)
        preview_row.addWidget(self._shape_label)

        outer.addLayout(preview_row)

        # Thin separator below the frame (outside outer_h so the swatch doesn't cover it)
        line = QFrame()
        line.setObjectName("separator")
        line.setFrameShape(QFrame.Shape.HLine)
        top_v.addWidget(line)

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
        if sub_type == "recursion":
            self.set_data_mode(True)
        sub = SubCell(sub_type=sub_type, parent=self)
        if self._data_mode:
            sub.content_changed.connect(self._mark_data_stale)
        else:
            sub.content_changed.connect(self._on_text_changed)
        sub.delete_requested.connect(lambda: self._remove_sub_cell(sub))
        sub._edit.navigate_down_requested.connect(
            lambda cid=sub.cell_id: self.navigate_down_requested.emit(cid)
        )
        sub._edit.navigate_up_requested.connect(
            lambda cid=sub.cell_id: self.navigate_up_requested.emit(cid)
        )
        self._sub_cells.append(sub)
        self._sub_layout.addWidget(sub)
        self._update_sub_border()
        self._debounce.start()
        return sub

    def _remove_sub_cell(self, sub: SubCell) -> None:
        if sub in self._sub_cells:
            self._sub_cells.remove(sub)
        self._sub_layout.removeWidget(sub)
        sub.deleteLater()
        self._update_sub_border()
        self._debounce.start()

    def _update_sub_border(self) -> None:
        """Show dashed border on outer frame when sub-cells are present."""
        has_subs = len(self._sub_cells) > 0
        self._outer_frame.setStyleSheet(
            "QFrame#cellFrame { border: 1px dashed #555; border-radius: 4px; margin: 1px; }"
            if has_subs else ""
        )

    def constraint_exprs(self) -> list[str]:
        return [s.source() for s in self._sub_cells if s.sub_type() == "constraint" and s.source().strip()]

    def condition_exprs(self) -> list[str]:
        return [s.source() for s in self._sub_cells if s.sub_type() == "condition" and s.source().strip()]

    def recurrence_expr(self) -> str | None:
        for s in self._sub_cells:
            if s.sub_type() == "recursion" and s.source().strip():
                return s.source().strip()
        return None

    def has_recursion_sub_cell(self) -> bool:
        """Return True if a recursion sub-cell exists (even if empty)."""
        return any(s.sub_type() == "recursion" for s in self._sub_cells)

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
            for sub in self._sub_cells:
                sub.content_changed.disconnect(self._on_text_changed)
                sub.content_changed.connect(self._mark_data_stale)
        elif not enabled and not self._debounce_connected:
            self._text_edit.textChanged.disconnect(self._mark_data_stale)
            self._text_edit.textChanged.connect(self._on_text_changed)
            self._text_edit.focus_lost.disconnect(self._emit_changed)
            self._debounce_connected = True
            self._status_dot.setStyleSheet("color: #bbb; font-size: 12px;")
            for sub in self._sub_cells:
                sub.content_changed.disconnect(self._mark_data_stale)
                sub.content_changed.connect(self._on_text_changed)

    def is_data_mode(self) -> bool:
        return self._data_mode

    def set_def_mode(self, enabled: bool) -> None:
        """Switch between deferred (focus-out) and eager (debounced) evaluation for def-function cells."""
        if self._def_mode == enabled:
            return
        self._def_mode = enabled
        if enabled:
            self._debounce.stop()
            self._text_edit.focus_lost.connect(self._emit_changed)
        else:
            self._text_edit.focus_lost.disconnect(self._emit_changed)

    def is_def_mode(self) -> bool:
        return self._def_mode

    def set_vector_cell(self, enabled: bool) -> None:
        self._is_vector_cell = enabled

    def is_vector_cell(self) -> bool:
        return self._is_vector_cell

    def set_style(self, style: CellStyle) -> None:
        self.style = style
        self.refresh_swatch()

    def refresh_swatch(self) -> None:
        self._swatch.set_style(self.style)

    def is_visible_cell(self) -> bool:
        return self._visible

    def focus(self) -> None:
        self._text_edit.setFocus()
        cur = self._text_edit.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        self._text_edit.setTextCursor(cur)

    def sub_cells(self) -> list["SubCell"]:
        return list(self._sub_cells)

    def primary_focus_widget(self) -> CellTextEdit:
        return self._text_edit

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_add_sub_clicked(self):
        menu = QMenu(self)
        menu.addAction("Add Recursion Rule", lambda: self.add_sub_cell("recursion"))
        menu.addAction("Add Initial Condition", lambda: self.add_sub_cell("initial_condition"))
        menu.addAction("Add Constraint (filter surface)", lambda: self.add_sub_cell("constraint"))
        menu.addAction("Add Condition (piecewise branch)", lambda: self.add_sub_cell("condition"))
        menu.exec(self._add_sub_btn.mapToGlobal(
            self._add_sub_btn.rect().bottomLeft()
        ))

    def _on_text_changed(self):
        should_defer = self.source().lstrip().startswith("def ")
        if should_defer != self._def_mode:
            self.set_def_mode(should_defer)
        if not self._def_mode:
            self._debounce.start()

    def _emit_changed(self):
        self.content_changed.emit(self.cell_id)

    def _on_visibility_toggled(self, checked: bool):
        self._visible = checked
        opacity = "0.4" if not checked else ""
        self._text_edit.setStyleSheet(f"opacity: {opacity};" if not checked else "")
        self._swatch.set_visible(checked)
        self.refresh_swatch()
        self.visibility_toggled.emit(self.cell_id, checked)

    def _on_style_requested(self):
        from pringle.style_popover import StylePopoverWidget
        popover = StylePopoverWidget(
            self.style, parent=self,
            show_render_mode=self._data_mode,
            show_normalize=self._is_vector_cell,
            visible=self._visible,
        )
        popover.style_changed.connect(self._on_style_changed)
        popover.color_picker_requested.connect(self._open_color_picker)
        popover.visible_toggled.connect(self._on_visibility_toggled)
        pos = self._swatch.mapToGlobal(self._swatch.rect().bottomLeft())
        hint_h = popover.sizeHint().height()
        if pos.y() + hint_h > self._swatch.screen().availableGeometry().bottom():
            pos = self._swatch.mapToGlobal(self._swatch.rect().topLeft())
            pos.setY(pos.y() - hint_h)
        popover.move(pos)
        popover.show()

    def _open_color_picker(self):
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

    def _on_style_changed(self, new_style):
        from dataclasses import replace
        self.style = replace(new_style)
        self.refresh_swatch()
        self.style_updated.emit(self.cell_id)
