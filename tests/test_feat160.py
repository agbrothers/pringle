"""
FEAT-160: In-cell line commenting (Cmd+/).

Cmd+/ toggles '# ' on the current line or all selected lines within a CellTextEdit.
The cell-level morph toggle was moved to Cmd+Shift+/.
For CommentCellWidget, both Cmd+/ and Cmd+Shift+/ trigger the cell-level uncomment.
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QTextCursor

from pringle.cell_widget import CellTextEdit
from pringle.comment_cell_widget import CommentCellWidget
from pringle.cell_list import CellListWidget
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def editor(qapp):
    e = CellTextEdit(allow_newline=True)
    e.show()
    return e


class TestToggleLineComment:
    def _set(self, editor, text):
        editor.setPlainText(text)
        c = editor.textCursor()
        c.movePosition(QTextCursor.MoveOperation.Start)
        editor.setTextCursor(c)

    def test_single_line_add_comment(self, qapp, editor):
        self._set(editor, "z = x**2 + y**2")
        editor._toggle_line_comment()
        assert editor.toPlainText() == "# z = x**2 + y**2"

    def test_single_line_remove_comment(self, qapp, editor):
        self._set(editor, "# z = x**2 + y**2")
        editor._toggle_line_comment()
        assert editor.toPlainText() == "z = x**2 + y**2"

    def test_multiline_all_uncommented_adds_prefix(self, qapp, editor):
        self._set(editor, "a = 1\nb = 2\nc = 3")
        # Select all
        c = editor.textCursor()
        c.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(c)
        editor._toggle_line_comment()
        assert editor.toPlainText() == "# a = 1\n# b = 2\n# c = 3"

    def test_multiline_all_commented_removes_prefix(self, qapp, editor):
        self._set(editor, "# a = 1\n# b = 2\n# c = 3")
        c = editor.textCursor()
        c.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(c)
        editor._toggle_line_comment()
        assert editor.toPlainText() == "a = 1\nb = 2\nc = 3"

    def test_multiline_mixed_adds_prefix_to_all(self, qapp, editor):
        """If not ALL lines are commented, prefix every line."""
        self._set(editor, "# a = 1\nb = 2")
        c = editor.textCursor()
        c.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(c)
        editor._toggle_line_comment()
        assert editor.toPlainText() == "# # a = 1\n# b = 2"

    def test_toggle_is_single_undo_step(self, qapp, editor):
        self._set(editor, "x = 1\ny = 2")
        c = editor.textCursor()
        c.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(c)
        editor._toggle_line_comment()
        assert editor.toPlainText() == "# x = 1\n# y = 2"
        editor.undo()
        assert editor.toPlainText() == "x = 1\ny = 2"


class TestCommentCellUncommentSignal:
    """Cmd+/ and Cmd+Shift+/ in a CommentCellWidget emit toggle_comment_requested."""

    def _make_list(self, qapp):
        return CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))

    def test_ctrl_slash_emits_toggle_signal(self, qapp):
        fired = []
        cell = CommentCellWidget(source="# hello")
        cell.toggle_comment_requested.connect(lambda cid: fired.append(cid))
        cell._edit.toggle_comment_requested.emit()
        assert fired == [cell.cell_id]

    def test_ctrl_slash_morphs_comment_to_equation(self, qapp):
        from pringle.cell_widget import CellWidget
        clist = self._make_list(qapp)
        comment = clist.add_comment_cell(source="# z = x")
        cell_id = comment.cell_id
        # Simulate Ctrl+/ keypress inside the comment edit
        comment._edit.toggle_comment_requested.emit()
        qapp.processEvents()
        new = clist._cells[clist._index_of(cell_id)]
        assert isinstance(new, CellWidget)
        assert new.source() == "z = x"
