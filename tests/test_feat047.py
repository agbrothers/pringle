"""
FEAT-047: Cmd+L / Ctrl+L selects the current line in a focused cell.

Covers:
- Ctrl+L on a single-line CellTextEdit selects full line text.
- Ctrl+L on the second line of a multi-line cell selects only that line.
- Ctrl+L works in _CommentEdit as well.
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QTextCursor

from pringle.cell_widget import CellTextEdit
from pringle.comment_cell_widget import CommentCellWidget
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _ctrl_l(widget):
    event = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_L,
        Qt.KeyboardModifier.ControlModifier,
    )
    widget.keyPressEvent(event)


class TestCellTextEditSelectLine:
    def test_single_line_selects_full_text(self, qapp):
        e = CellTextEdit(allow_newline=False)
        e.setPlainText("z = x**2 + y**2")
        _ctrl_l(e)
        assert e.textCursor().selectedText() == "z = x**2 + y**2"

    def test_second_line_selects_only_that_line(self, qapp):
        e = CellTextEdit(allow_newline=True)
        e.setPlainText("line_one\nline_two")
        # Move cursor to second line.
        cursor = e.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        e.setTextCursor(cursor)
        _ctrl_l(e)
        assert e.textCursor().selectedText() == "line_two"

    def test_first_line_of_multiline_not_selecting_whole_doc(self, qapp):
        e = CellTextEdit(allow_newline=True)
        e.setPlainText("first_line\nsecond_line")
        cursor = e.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        e.setTextCursor(cursor)
        _ctrl_l(e)
        assert e.textCursor().selectedText() == "first_line"


class TestCommentEditSelectLine:
    def test_ctrl_l_selects_line_in_comment_cell(self, qapp):
        grid = make_grid(GridConfig(n=32))
        cell = CommentCellWidget()
        cell._edit.setPlainText("this is a comment")
        _ctrl_l(cell._edit)
        assert cell._edit.textCursor().selectedText() == "this is a comment"
