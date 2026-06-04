"""
BUG-073: Comment cell pops out of folder when created by typing # in a new cell.

_maybe_morph_to_comment (the type-# path) must call _assign_folder on the new
CommentCellWidget so it inherits the same indent and collapsed-visibility as the
CellWidget it replaced.
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.cell_list import CellListWidget
from pringle.comment_cell_widget import CommentCellWidget
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def clist(qapp):
    return CellListWidget(
        on_cell_result=lambda cid, r, s: None,
        grid=make_grid(GridConfig(n=32)),
    )


class TestTypingHashInFolder:
    def test_comment_stays_in_folder(self, qapp, clist):
        """After type-# morph, _cell_folder still maps cell_id to the folder."""
        folder = clist.add_folder(name="FolderA")
        folder_id = folder.cell_id
        cell = clist.add_cell(source="z = x**2", after_id=folder_id)
        cell_id = cell.cell_id
        clist._assign_folder(cell, folder_id)
        assert clist._cell_folder.get(cell_id) == folder_id

        # Simulate typing '#' at the start of the cell
        cell._text_edit.setPlainText("# z = x**2")
        clist._on_cell_changed(cell_id)
        qapp.processEvents()

        new = clist._cells[clist._index_of(cell_id)]
        assert isinstance(new, CommentCellWidget)
        assert clist._cell_folder.get(cell_id) == folder_id

    def test_comment_inherits_indent(self, qapp, clist):
        """After type-# morph, the CommentCellWidget has the same indent as the original cell."""
        folder = clist.add_folder(name="FolderB")
        folder_id = folder.cell_id
        cell = clist.add_cell(source="z = y**2", after_id=folder_id)
        cell_id = cell.cell_id
        clist._assign_folder(cell, folder_id)
        indent_before = cell.contentsMargins().left()

        cell._text_edit.setPlainText("# z = y**2")
        clist._on_cell_changed(cell_id)
        qapp.processEvents()

        new = clist._cells[clist._index_of(cell_id)]
        assert isinstance(new, CommentCellWidget)
        assert new.contentsMargins().left() == indent_before

    def test_comment_outside_folder_unaffected(self, qapp, clist):
        """Type-# on a cell not in any folder must still work (folder_id=None is safe)."""
        cell = clist.add_cell(source="z = x + y")
        cell_id = cell.cell_id
        assert clist._cell_folder.get(cell_id) is None

        cell._text_edit.setPlainText("# z = x + y")
        clist._on_cell_changed(cell_id)
        qapp.processEvents()

        new = clist._cells[clist._index_of(cell_id)]
        assert isinstance(new, CommentCellWidget)
        assert clist._cell_folder.get(cell_id) is None
