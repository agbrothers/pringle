"""
BUG-072: Commenting/uncommenting a cell by typing scrolls the expression panel to top.

The three morph helpers (_maybe_morph_to_comment, _morph_equation_to_comment,
_morph_comment_to_equation) must defer ensureWidgetVisible via QTimer.singleShot
so that the layout pass completes first and the scroll position is preserved.
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from pringle.cell_list import CellListWidget
from pringle.cell_widget import CellWidget
from pringle.comment_cell_widget import CommentCellWidget
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _make_list(qapp):
    return CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))


def _fill_and_scroll(qapp, clist, n_cells=20):
    """Add n_cells and scroll so the last cell is visible; return the middle cell_id."""
    cells = [clist.add_cell(source=f"z = x**2 + {i}") for i in range(n_cells)]
    qapp.processEvents()
    mid = cells[n_cells // 2]
    clist._scroll.ensureWidgetVisible(mid)
    qapp.processEvents()
    return mid.cell_id


class TestScrollPreservedOnMorph:
    def test_type_hash_does_not_reset_scroll(self, qapp):
        """Typing '#' to comment a mid-list cell must not scroll the panel to the top."""
        clist = _make_list(qapp)
        cell_id = _fill_and_scroll(qapp, clist)
        scroll_before = clist._scroll.verticalScrollBar().value()

        # Simulate typing '#' — triggers _maybe_morph_to_comment via content_changed
        cell = clist._cells[clist._index_of(cell_id)]
        cell._text_edit.setPlainText(f"# {cell.source()}")
        clist._on_cell_changed(cell_id)
        # Process the synchronous part; do NOT yet process the deferred timer
        # (singleShot(0) fires on the next event loop iteration)
        qapp.processEvents()

        scroll_after = clist._scroll.verticalScrollBar().value()
        # Scroll must not have jumped to 0 (top) — allow small settling margin
        assert scroll_after > 0 or scroll_before == 0, (
            f"Scroll reset to top on type-# morph: was {scroll_before}, now {scroll_after}"
        )

    def test_cmd_slash_comment_does_not_reset_scroll(self, qapp):
        """Cmd+/ comment morph must not reset scroll position."""
        clist = _make_list(qapp)
        cell_id = _fill_and_scroll(qapp, clist)
        scroll_before = clist._scroll.verticalScrollBar().value()

        clist._morph_equation_to_comment(cell_id)
        qapp.processEvents()

        scroll_after = clist._scroll.verticalScrollBar().value()
        assert scroll_after > 0 or scroll_before == 0, (
            f"Scroll reset to top on Cmd+/ comment: was {scroll_before}, now {scroll_after}"
        )

    def test_cmd_slash_uncomment_does_not_reset_scroll(self, qapp):
        """Cmd+/ uncomment morph must not reset scroll position."""
        clist = _make_list(qapp)
        # Fill with comments so we have a scrollable list of comment cells
        comments = [clist.add_comment_cell(source=f"# note {i}") for i in range(20)]
        qapp.processEvents()
        mid = comments[10]
        cell_id = mid.cell_id
        clist._scroll.ensureWidgetVisible(mid)
        qapp.processEvents()
        scroll_before = clist._scroll.verticalScrollBar().value()

        clist._morph_comment_to_equation(cell_id)
        qapp.processEvents()

        scroll_after = clist._scroll.verticalScrollBar().value()
        assert scroll_after > 0 or scroll_before == 0, (
            f"Scroll reset to top on Cmd+/ uncomment: was {scroll_before}, now {scroll_after}"
        )
