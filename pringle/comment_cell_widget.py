"""
CommentCellWidget — a free-text annotation cell in the equation panel.

A cell whose source starts with ``#`` is automatically morphed into this
widget.  It does not participate in expression evaluation; the DAG and
namespace builder skip it entirely.

Layout
------
  [drag handle] [auto-grow QPlainTextEdit] [✕]

The ``# `` prefix is stored as literal text inside the edit area so the
user can see and edit it directly.  ``source()`` returns the raw text;
``set_source()`` sets it as-is.  The morph trigger and YAML round-trip
rely on the source starting with ``#``.
"""

from __future__ import annotations

import uuid
import re

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPlainTextEdit, QPushButton, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFontMetricsF, QKeyEvent, QTextOption

from pringle.style import CellStyle
from pringle.cell_widget import DragHandle

# Strip a leading "# " or "#" from source text so the widget text area
# only contains the comment body.
_HASH_RE = re.compile(r"^#\s?")


class _CommentEdit(QPlainTextEdit):
    """
    Auto-growing QPlainTextEdit for comment cells.

    QPlainTextDocumentLayout.documentSize().height() returns a visual
    line count (not pixels).  documentSizeChanged fires after layout so
    we multiply line_count × fontMetrics().lineSpacing() to get the
    correct pixel height for word-wrapped content.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(' ') * 4)
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
        self.setFixedHeight(max(h, 30))
        self.updateGeometry()

    def _adjust_height(self) -> None:
        """Initial sizing before documentSizeChanged has fired."""
        line_count = max(1, int(self.document().size().height()))
        line_h = self.fontMetrics().lineSpacing()
        dm = int(self.document().documentMargin())
        m = self.contentsMargins()
        h = line_count * line_h + 2 * dm + m.top() + m.bottom()
        self.setFixedHeight(max(h, 30))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._adjust_height()

    def wheelEvent(self, event) -> None:
        event.ignore()

    enter_at_end = pyqtSignal()    # plain Enter → new equation cell below
    folder_requested = pyqtSignal()  # Ctrl+Enter → new folder cell below
    navigate_down_requested = pyqtSignal()
    navigate_up_requested = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        mod = event.modifiers()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mod == Qt.KeyboardModifier.ControlModifier:
                self.folder_requested.emit()
                return
            if mod == Qt.KeyboardModifier.NoModifier:
                self.enter_at_end.emit()
                return
            # Shift+Enter → insert newline (fall through to super)
        elif key == Qt.Key.Key_Down:
            if self.textCursor().blockNumber() == self.document().blockCount() - 1:
                self.navigate_down_requested.emit()
                return
        elif key == Qt.Key.Key_Up:
            if self.textCursor().blockNumber() == 0:
                self.navigate_up_requested.emit()
                return
        super().keyPressEvent(event)


class CommentCellWidget(QWidget):
    """Free-text annotation — not evaluated, not rendered."""

    delete_requested = pyqtSignal(str)       # cell_id
    content_changed = pyqtSignal(str)        # cell_id
    enter_pressed = pyqtSignal(str)          # cell_id — Enter → new equation cell below
    new_folder_requested = pyqtSignal(str)   # cell_id — Ctrl+Enter → new folder cell below
    drag_started = pyqtSignal(str)           # cell_id
    drag_moved = pyqtSignal(str, int)        # cell_id, global_y
    drag_ended = pyqtSignal(str)             # cell_id
    navigate_down_requested = pyqtSignal(str)  # cell_id
    navigate_up_requested = pyqtSignal(str)    # cell_id

    def __init__(
        self,
        cell_id: str | None = None,
        source: str = "",
        style: CellStyle | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.cell_id: str = cell_id or str(uuid.uuid4())
        self.style: CellStyle = style or CellStyle()
        self._build_ui()
        self._edit.enter_at_end.connect(lambda: self.enter_pressed.emit(self.cell_id))
        self._edit.folder_requested.connect(lambda: self.new_folder_requested.emit(self.cell_id))
        self._edit.navigate_down_requested.connect(lambda: self.navigate_down_requested.emit(self.cell_id))
        self._edit.navigate_up_requested.connect(lambda: self.navigate_up_requested.emit(self.cell_id))
        if source:
            self.set_source(source)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer_h = QHBoxLayout(self)
        outer_h.setContentsMargins(0, 2, 4, 2)
        outer_h.setSpacing(0)

        # Drag handle (identical pattern to other cells)
        self._drag_handle = DragHandle(self)
        self._drag_handle.drag_started.connect(lambda: self.drag_started.emit(self.cell_id))
        self._drag_handle.drag_moved.connect(lambda y: self.drag_moved.emit(self.cell_id, y))
        self._drag_handle.drag_ended.connect(lambda: self.drag_ended.emit(self.cell_id))
        outer_h.addWidget(self._drag_handle)

        # Auto-grow text area — "# " prefix is part of the cell text
        self._edit = _CommentEdit()
        self._edit.setObjectName("comment_edit")
        self._edit.setPlaceholderText("comment…")
        self._edit.document().contentsChanged.connect(
            lambda: self.content_changed.emit(self.cell_id)
        )
        outer_h.addWidget(self._edit, 1)

        del_btn = QPushButton("✕")
        del_btn.setObjectName("comment_del")
        del_btn.setFixedSize(22, 22)
        del_btn.setFlat(True)
        del_btn.setToolTip("Delete comment")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.cell_id))
        outer_h.addWidget(del_btn)

    # ------------------------------------------------------------------
    # CellWidget-compatible interface
    # ------------------------------------------------------------------

    def source(self) -> str:
        """Return the raw text including the leading '# '."""
        return self._edit.toPlainText()

    def set_source(self, text: str) -> None:
        """Set the cell text directly; the caller is responsible for the '# ' prefix."""
        self._edit.setPlainText(text)

    def is_visible_cell(self) -> bool:
        return False

    def focus(self) -> None:
        self._edit.setFocus()
        cursor = self._edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._edit.setTextCursor(cursor)

    def primary_focus_widget(self) -> "_CommentEdit":
        return self._edit

    def set_error(self, msg: str | None) -> None:
        pass

    def set_warning(self, msg: str | None) -> None:
        pass

    def clear_diagnostics(self) -> None:
        pass
