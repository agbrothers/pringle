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


class TestVisibilityStash:
    def test_visibility_off_is_stashed_and_restored(self, qapp, clist):
        """Eye-button state is preserved through a comment round-trip."""
        cell = clist.add_cell(source="w = cos(x)")
        cell_id = cell.cell_id
        # Turn the eye off
        cell._eye_btn.setChecked(False)
        cell._on_visibility_toggled(False)
        assert not cell.is_visible_cell()

        # Comment it out — stash should capture is_visible=False
        clist._morph_equation_to_comment(cell_id)
        comment = clist._cells[clist._index_of(cell_id)]
        assert isinstance(comment, CommentCellWidget)
        assert comment._stashed_visible is False

        # Uncomment — eye should be restored to off
        clist._morph_comment_to_equation(cell_id)
        restored = clist._cells[clist._index_of(cell_id)]
        assert isinstance(restored, CellWidget)
        assert not restored.is_visible_cell()

    def test_visibility_on_stays_on_after_round_trip(self, qapp, clist):
        """A visible cell stays visible after comment round-trip."""
        cell = clist.add_cell(source="v = x + y")
        cell_id = cell.cell_id
        assert cell.is_visible_cell()

        clist._morph_equation_to_comment(cell_id)
        clist._morph_comment_to_equation(cell_id)
        restored = clist._cells[clist._index_of(cell_id)]
        assert restored.is_visible_cell()


class TestFolderMembership:
    def test_comment_inherits_folder_indent(self, qapp, clist):
        """After equation→comment morph, the cell remains indented in its folder."""
        folder = clist.add_folder(name="TestFolder")
        folder_id = folder.cell_id
        cell = clist.add_cell(source="u = 1", after_id=folder_id)
        cell_id = cell.cell_id
        # Manually assign to folder so the indent is applied
        clist._assign_folder(cell, folder_id)
        assert clist._cell_folder.get(cell_id) == folder_id
        indent_before = cell.contentsMargins().left()

        clist._morph_equation_to_comment(cell_id)
        comment = clist._cells[clist._index_of(cell_id)]
        assert isinstance(comment, CommentCellWidget)
        assert clist._cell_folder.get(cell_id) == folder_id
        assert comment.contentsMargins().left() == indent_before

    def test_equation_inherits_folder_indent_after_uncomment(self, qapp, clist):
        """After comment→equation morph, the cell is still indented in its folder."""
        folder = clist.add_folder(name="TestFolder2")
        folder_id = folder.cell_id
        comment = clist.add_comment_cell(source="# p = 3", after_id=folder_id)
        cell_id = comment.cell_id
        clist._assign_folder(comment, folder_id)
        indent_before = comment.contentsMargins().left()

        clist._morph_comment_to_equation(cell_id)
        qapp.processEvents()
        cur = clist._cells[clist._index_of(cell_id)]
        assert clist._cell_folder.get(cell_id) == folder_id
        assert cur.contentsMargins().left() == indent_before


class TestToggleCommentNoop:
    def test_no_focused_cell_does_nothing(self, qapp, clist):
        """toggle_comment_focused_cell is a no-op when nothing is focused."""
        if QApplication.focusWidget():
            QApplication.focusWidget().clearFocus()
        qapp.processEvents()
        n_before = len(clist._cells)
        clist.toggle_comment_focused_cell()  # must not raise
        assert len(clist._cells) == n_before
