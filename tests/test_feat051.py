"""
FEAT-051 — Keyboard shortcuts: Enter adds equation cell, Shift+Enter adds newline,
Cmd+Enter adds folder cell.

Tests cover:
- Enter in equation cell creates a new CellWidget after it and focuses it
- Shift+Enter inserts a newline (no new cell)
- Ctrl+Enter (≡ Cmd on macOS) creates a new FolderCellWidget after it
- Enter on last cell appends to end
- Enter from slider value/min/max/step fields creates a new equation cell below
- Same shortcuts work identically in comment cells
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from pringle.cell_list import CellListWidget
from pringle.cell_widget import CellWidget, CellTextEdit
from pringle.slider_widget import SliderWidget
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=32))


@pytest.fixture
def clist(qapp, grid):
    return CellListWidget(on_cell_result=lambda *a: None, grid=grid)


def _press_enter(widget, modifier=Qt.KeyboardModifier.NoModifier):
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, modifier)
    widget.keyPressEvent(event)


# ---------------------------------------------------------------------------
# Equation cell — Enter / Shift+Enter / Ctrl+Enter
# ---------------------------------------------------------------------------

class TestEnterInEquationCell:
    def test_shift_enter_adds_cell_below(self, qapp, clist):
        cell = clist.add_cell()
        assert len(clist._cells) == 1
        _press_enter(cell._text_edit, Qt.KeyboardModifier.ShiftModifier)
        qapp.processEvents()
        assert len(clist._cells) == 2
        assert isinstance(clist._cells[1], CellWidget)

    def test_shift_enter_inserts_after_not_at_end(self, qapp, clist):
        """Shift+Enter from any cursor position creates a new cell, not just from end."""
        first = clist.add_cell("z = sin(x)")
        second = clist.add_cell()
        count_before = len(clist._cells)
        # Move cursor to beginning of first cell, then press Shift+Enter
        cursor = first._text_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        first._text_edit.setTextCursor(cursor)
        _press_enter(first._text_edit, Qt.KeyboardModifier.ShiftModifier)
        qapp.processEvents()
        assert len(clist._cells) == count_before + 1

    def test_enter_inserts_newline(self, qapp, clist):
        cell = clist.add_cell()
        count_before = len(clist._cells)
        _press_enter(cell._text_edit)
        qapp.processEvents()
        assert len(clist._cells) == count_before   # no new cell
        assert "\n" in cell._text_edit.toPlainText()

    def test_ctrl_enter_adds_folder_below(self, qapp, clist):
        from pringle.folder_cell_widget import FolderCellWidget
        cell = clist.add_cell()
        idx = clist._cells.index(cell)
        count_before = len(clist._cells)
        _press_enter(cell._text_edit, Qt.KeyboardModifier.ControlModifier)
        qapp.processEvents()
        assert len(clist._cells) == count_before + 1
        assert isinstance(clist._cells[idx + 1], FolderCellWidget)

    def test_shift_enter_on_last_cell_appends(self, qapp, clist):
        cell = clist.add_cell()
        count_before = len(clist._cells)
        _press_enter(cell._text_edit, Qt.KeyboardModifier.ShiftModifier)
        qapp.processEvents()
        assert len(clist._cells) == count_before + 1


# ---------------------------------------------------------------------------
# Slider enter_pressed signal wiring
# ---------------------------------------------------------------------------

class TestSliderEnterPressed:
    def _make_list(self, qapp, grid):
        return CellListWidget(on_cell_result=lambda *a: None, grid=grid)

    def test_slider_has_enter_pressed_signal(self, qapp):
        s = SliderWidget(name="a", value=5.0)
        received: list[str] = []
        s.enter_pressed.connect(received.append)
        s.enter_pressed.emit(s.cell_id)
        assert received == [s.cell_id]

    def test_morphed_slider_shift_enter_creates_cell(self, qapp, grid):
        """Slider created via focus-out morph (not add_cell) must also wire enter_pressed."""
        clist = self._make_list(qapp, grid)
        cell = clist.add_cell()
        cell.set_source("a = 5")
        cell._text_edit.focus_lost.emit()   # trigger morph
        qapp.processEvents()
        slider = clist._cells[0]
        assert isinstance(slider, SliderWidget)
        count_before = len(clist._cells)
        _press_enter(slider._spinbox, Qt.KeyboardModifier.ShiftModifier)
        qapp.processEvents()
        assert len(clist._cells) == count_before + 1

    def test_slider_value_field_shift_enter_creates_cell(self, qapp, grid):
        clist = self._make_list(qapp, grid)
        slider = clist.add_cell("a = 5")
        assert isinstance(slider, SliderWidget)
        count_before = len(clist._cells)
        _press_enter(slider._spinbox, Qt.KeyboardModifier.ShiftModifier)
        qapp.processEvents()
        assert len(clist._cells) == count_before + 1
        assert isinstance(clist._cells[clist._cells.index(slider) + 1], CellWidget)

    def test_slider_min_field_enter_does_not_create_cell(self, qapp, grid):
        clist = self._make_list(qapp, grid)
        slider = clist.add_cell("b = 3")
        count_before = len(clist._cells)
        _press_enter(slider._min_box)
        qapp.processEvents()
        assert len(clist._cells) == count_before

    def test_slider_max_field_enter_does_not_create_cell(self, qapp, grid):
        clist = self._make_list(qapp, grid)
        slider = clist.add_cell("c = 3")
        count_before = len(clist._cells)
        _press_enter(slider._max_box)
        qapp.processEvents()
        assert len(clist._cells) == count_before

    def test_slider_step_field_enter_does_not_create_cell(self, qapp, grid):
        clist = self._make_list(qapp, grid)
        slider = clist.add_cell("d = 3")
        count_before = len(clist._cells)
        _press_enter(slider._step_box)
        qapp.processEvents()
        assert len(clist._cells) == count_before

    def test_slider_min_field_enter_commits_value(self, qapp, grid):
        """Enter in _min_box commits the value (fires committed) but does not add a cell."""
        clist = self._make_list(qapp, grid)
        slider = clist.add_cell("e = 3")
        slider._min_box.setText("2")
        committed: list[float] = []
        slider._min_box.committed.connect(committed.append)
        count_before = len(clist._cells)
        _press_enter(slider._min_box)
        qapp.processEvents()
        assert committed, "committed signal should have fired"
        assert len(clist._cells) == count_before


# ---------------------------------------------------------------------------
# Comment cell — same shortcuts
# ---------------------------------------------------------------------------

class TestEnterInCommentCell:
    def _make_list(self, qapp, grid):
        return CellListWidget(on_cell_result=lambda *a: None, grid=grid)

    def test_shift_enter_adds_equation_cell_below(self, qapp, grid):
        clist = self._make_list(qapp, grid)
        comment = clist.add_comment_cell("# hello")
        count_before = len(clist._cells)
        _press_enter(comment._edit, Qt.KeyboardModifier.ShiftModifier)
        qapp.processEvents()
        assert len(clist._cells) == count_before + 1
        assert isinstance(clist._cells[1], CellWidget)

    def test_enter_inserts_newline(self, qapp, grid):
        clist = self._make_list(qapp, grid)
        comment = clist.add_comment_cell("# hello")
        count_before = len(clist._cells)
        _press_enter(comment._edit)
        qapp.processEvents()
        assert len(clist._cells) == count_before   # no new cell
        assert "\n" in comment._edit.toPlainText()

    def test_ctrl_enter_adds_folder_below(self, qapp, grid):
        from pringle.folder_cell_widget import FolderCellWidget
        clist = self._make_list(qapp, grid)
        comment = clist.add_comment_cell("# hello")
        count_before = len(clist._cells)
        _press_enter(comment._edit, Qt.KeyboardModifier.ControlModifier)
        qapp.processEvents()
        assert len(clist._cells) == count_before + 1
        assert isinstance(clist._cells[1], FolderCellWidget)
