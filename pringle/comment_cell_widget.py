"""
CommentCellWidget — a free-text annotation cell in the equation panel.

A cell whose source starts with ``#`` is automatically morphed into this
widget.  It does not participate in expression evaluation; the DAG and
namespace builder skip it entirely.

Layout
------
  [drag handle] [# label] [auto-grow QPlainTextEdit] [✕]

The ``#`` is shown as a fixed decoration in the left margin and is NOT
included in the text area.  ``source()`` prepends ``# `` to the stored
text so that the YAML session round-trip preserves the comment prefix and
the morph trigger stays intact on reload.
"""

from __future__ import annotations

import uuid
import re

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPlainTextEdit, QPushButton, QLabel, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QTextOption

from pringle.style import CellStyle
from pringle.cell_widget import DragHandle

# Strip a leading "# " or "#" from source text so the widget text area
# only contains the comment body.
_HASH_RE = re.compile(r"^#\s?")


class CommentCellWidget(QWidget):
    """Free-text annotation — not evaluated, not rendered."""

    delete_requested = pyqtSignal(str)   # cell_id
    content_changed = pyqtSignal(str)    # cell_id
    drag_started = pyqtSignal(str)       # cell_id
    drag_moved = pyqtSignal(str, int)    # cell_id, global_y
    drag_ended = pyqtSignal(str)         # cell_id

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
        if source:
            self.set_source(source)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setStyleSheet("background: #1e1e1e;")

        outer_h = QHBoxLayout(self)
        outer_h.setContentsMargins(0, 2, 4, 2)
        outer_h.setSpacing(0)

        # Drag handle (identical pattern to other cells)
        self._drag_handle = DragHandle(self)
        self._drag_handle.drag_started.connect(lambda: self.drag_started.emit(self.cell_id))
        self._drag_handle.drag_moved.connect(lambda y: self.drag_moved.emit(self.cell_id, y))
        self._drag_handle.drag_ended.connect(lambda: self.drag_ended.emit(self.cell_id))
        outer_h.addWidget(self._drag_handle)

        # '#' decoration in place of color dot
        hash_lbl = QLabel("#")
        hash_lbl.setFixedWidth(18)
        hash_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hash_lbl.setStyleSheet(
            "color: #4a7c59; font-size: 13px; font-family: monospace; font-weight: bold;"
            "padding-top: 4px;"
        )
        outer_h.addWidget(hash_lbl)

        # Auto-grow text area
        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText("comment…")
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._edit.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self._edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._edit.setFixedHeight(30)
        self._edit.setStyleSheet(
            "QPlainTextEdit {"
            "  background: transparent;"
            "  color: #7a9e7a;"
            "  font-size: 12px;"
            "  font-family: monospace;"
            "  border: none;"
            "  padding: 2px 0;"
            "}"
        )
        self._edit.document().contentsChanged.connect(self._adjust_height)
        self._edit.document().contentsChanged.connect(
            lambda: self.content_changed.emit(self.cell_id)
        )
        outer_h.addWidget(self._edit, 1)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(22, 22)
        del_btn.setFlat(True)
        del_btn.setToolTip("Delete comment")
        del_btn.setStyleSheet(
            "QPushButton { color: #555; } QPushButton:hover { color: #ccc; }"
        )
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.cell_id))
        outer_h.addWidget(del_btn)

    def _adjust_height(self) -> None:
        doc_h = self._edit.document().size().height()
        m = self._edit.contentsMargins()
        h = int(doc_h) + m.top() + m.bottom() + 6
        self._edit.setFixedHeight(max(h, 30))

    # ------------------------------------------------------------------
    # CellWidget-compatible interface
    # ------------------------------------------------------------------

    def source(self) -> str:
        """Return the full source string including the leading '# '."""
        text = self._edit.toPlainText()
        return "# " + text if text else "#"

    def set_source(self, text: str) -> None:
        """Accept a source string with or without leading '#'; stores body only."""
        body = _HASH_RE.sub("", text, count=1)
        self._edit.setPlainText(body)

    def is_visible_cell(self) -> bool:
        return False

    def focus(self) -> None:
        self._edit.setFocus()
        cursor = self._edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._edit.setTextCursor(cursor)

    def set_error(self, msg: str | None) -> None:
        pass

    def set_warning(self, msg: str | None) -> None:
        pass

    def clear_diagnostics(self) -> None:
        pass
