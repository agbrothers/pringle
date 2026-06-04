"""
BUG-075: Commenting then uncommenting a slider cell crashes with RuntimeError.

When _morph_comment_to_equation is called on a cell that becomes a SliderWidget via
_maybe_morph_to_slider, the intermediate CellWidget is deleteLater()'d while
_active_cell still points to it. The next focus change then calls _mark_active on
the deleted C++ object.

Fix: clear _active_cell in _maybe_morph_to_slider before deleteLater(), and guard
_set_active_cell with try/except RuntimeError.
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.cell_list import CellListWidget
from pringle.slider_widget import SliderWidget
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


class TestSliderCommentRoundTrip:
    def _make_list(self, qapp):
        return CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))

    def test_comment_then_uncomment_slider_does_not_crash(self, qapp):
        """Comment a slider cell then uncomment it; must not raise RuntimeError."""
        clist = self._make_list(qapp)
        slider = clist.add_cell(source="k = 5")
        qapp.processEvents()
        cell_id = slider.cell_id
        assert isinstance(clist._cells[clist._index_of(cell_id)], SliderWidget)

        # Simulate the active-cell state being on the slider
        clist._active_cell = clist._cells[clist._index_of(cell_id)]

        # Comment → uncomment via the morph helpers
        clist._morph_equation_to_comment(cell_id)
        qapp.processEvents()
        clist._morph_comment_to_equation(cell_id)
        qapp.processEvents()  # runs deleteLater; must not crash

        new = clist._cells[clist._index_of(cell_id)]
        assert isinstance(new, SliderWidget)

    def test_active_cell_cleared_on_slider_morph(self, qapp):
        """_active_cell must not point to the deleted CellWidget after slider morph."""
        clist = self._make_list(qapp)
        comment = clist.add_comment_cell(source="# k = 3")
        cell_id = comment.cell_id

        clist._morph_comment_to_equation(cell_id)
        qapp.processEvents()

        # _active_cell should not be the intermediate CellWidget (deleted by slider morph)
        if clist._active_cell is not None:
            # Verify it's still accessible (not a deleted C++ object)
            try:
                clist._active_cell.objectName()
            except RuntimeError:
                pytest.fail("_active_cell points to a deleted C++ widget")
