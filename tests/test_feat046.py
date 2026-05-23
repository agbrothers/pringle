"""
FEAT-046 — Ctrl+/ toggle cell comment.

Pressing Ctrl+/ on a focused equation/slider cell morphs it to CommentCellWidget;
pressing it again morphs the comment back to a CellWidget (or SliderWidget when
the recovered source is a scalar assignment).
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.cell_list import CellListWidget
from pringle.cell_widget import CellWidget
from pringle.slider_widget import SliderWidget
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


class TestMorphEquationToComment:
    def test_source_gets_hash_prefix(self, qapp, clist):
        cell = clist.add_cell(source="z = x**2 + y**2")
        cell_id = cell.cell_id
        clist._morph_equation_to_comment(cell_id)
        new = clist._cells[clist._index_of(cell_id)]
        assert isinstance(new, CommentCellWidget)
        assert new.source() == "# z = x**2 + y**2"

    def test_removes_from_namespace(self, qapp, clist):
        # add_cell with a scalar immediately returns a SliderWidget
        slider = clist.add_cell(source="dropped_var = 7")
        assert isinstance(slider, SliderWidget)
        cell_id = slider.cell_id
        clist._morph_equation_to_comment(cell_id)
        qapp.processEvents()
        assert "dropped_var" not in clist._shared_ns

    def test_empty_source_produces_hash_only(self, qapp, clist):
        cell = clist.add_cell(source="")
        cell_id = cell.cell_id
        clist._morph_equation_to_comment(cell_id)
        new = clist._cells[clist._index_of(cell_id)]
        assert isinstance(new, CommentCellWidget)
        # empty stripped source → just "#"
        assert new.source() in ("#", "# ")


class TestMorphCommentToEquation:
    def test_strips_hash_prefix(self, qapp, clist):
        comment = clist.add_comment_cell(source="# z = sin(x)")
        cell_id = comment.cell_id
        clist._morph_comment_to_equation(cell_id)
        new = clist._cells[clist._index_of(cell_id)]
        assert isinstance(new, CellWidget)
        assert not isinstance(new, SliderWidget)
        assert new.source() == "z = sin(x)"

    def test_scalar_source_morphs_to_slider(self, qapp, clist):
        """Comment → equation on 'a = 2.5' continues to morph into a SliderWidget."""
        comment = clist.add_comment_cell(source="# a = 2.5")
        cell_id = comment.cell_id
        clist._morph_comment_to_equation(cell_id)
        qapp.processEvents()
        new = clist._cells[clist._index_of(cell_id)]
        assert isinstance(new, SliderWidget)
        assert new.name == "a"
        assert new.value == pytest.approx(2.5)

    def test_adds_to_namespace(self, qapp, clist):
        comment = clist.add_comment_cell(source="# exported = 99")
        cell_id = comment.cell_id
        clist._morph_comment_to_equation(cell_id)
        qapp.processEvents()
        # Slider morph happens inline; namespace should contain the value
        new = clist._cells[clist._index_of(cell_id)]
        if isinstance(new, CellWidget) and not isinstance(new, SliderWidget):
            new._text_edit.focus_lost.emit()
            qapp.processEvents()
        assert "exported" in clist._shared_ns

    def test_noop_on_non_comment_cell(self, qapp, clist):
        """Calling _morph_comment_to_equation on a CellWidget does nothing."""
        cell = clist.add_cell(source="q = 1")
        cell_id = cell.cell_id
        clist._morph_comment_to_equation(cell_id)  # must not raise or change type
        cur = clist._cells[clist._index_of(cell_id)]
        assert not isinstance(cur, CommentCellWidget)


class TestToggleCommentNoop:
    def test_no_focused_cell_does_nothing(self, qapp, clist):
        """toggle_comment_focused_cell is a no-op when nothing is focused."""
        if QApplication.focusWidget():
            QApplication.focusWidget().clearFocus()
        qapp.processEvents()
        n_before = len(clist._cells)
        clist.toggle_comment_focused_cell()  # must not raise
        assert len(clist._cells) == n_before
