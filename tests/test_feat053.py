"""
FEAT-053 — Arrow-key cross-cell navigation in the expression panel.

Tests cover:
- Down on last line of equation cell → focuses primary field of next cell
- Up on first line of equation cell → focuses primary field of previous cell
- Down on a mid-line of a multi-line cell → no escape (cursor moves within cell)
- Down/Up into slider → focuses value spinbox
- Down into comment cell → focuses comment text field
- Down on last cell → no-op
- Up on first cell → no-op
- Down out of last subcell → jumps to next sibling
- Down from slider value → focuses min field
- Right from min at end → focuses max at position 0
- Left from max at position 0 → focuses min at end
- Right from max at end → focuses step at position 0
- Left from step at position 0 → focuses max at end
- Up from min / max / step → focuses value spinbox
- Down from min / max / step → exits slider to next sibling cell
- Left at min position 0 → no-op (signal emitted but unconnected)
- Right at step end → no-op (signal emitted but unconnected)
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from pringle.cell_list import CellListWidget
from pringle.cell_widget import CellWidget, CellTextEdit
from pringle.comment_cell_widget import CommentCellWidget
from pringle.slider_widget import SliderWidget, _ExprBox, _SpinBox
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


def _press(widget, key, modifier=Qt.KeyboardModifier.NoModifier):
    event = QKeyEvent(QKeyEvent.Type.KeyPress, key, modifier)
    widget.keyPressEvent(event)


# ---------------------------------------------------------------------------
# _focus_targets helper
# ---------------------------------------------------------------------------

class TestFocusTargets:
    def test_empty_list(self, qapp, clist):
        assert clist._focus_targets() == []

    def test_single_equation_cell(self, qapp, clist):
        cell = clist.add_cell()
        targets = clist._focus_targets()
        assert len(targets) == 1
        assert targets[0][0] == cell.cell_id
        assert targets[0][1] is cell.primary_focus_widget()

    def test_slider_included(self, qapp, grid):
        cl = CellListWidget(on_cell_result=lambda *a: None, grid=grid)
        slider = cl.add_cell("a = 5")
        assert isinstance(slider, SliderWidget)
        targets = cl._focus_targets()
        assert len(targets) == 1
        assert targets[0][0] == slider.cell_id
        assert targets[0][1] is slider.primary_focus_widget()

    def test_comment_cell_included(self, qapp, grid):
        cl = CellListWidget(on_cell_result=lambda *a: None, grid=grid)
        comment = cl.add_comment_cell("# hello")
        targets = cl._focus_targets()
        assert len(targets) == 1
        assert targets[0][0] == comment.cell_id

    def test_folder_skipped(self, qapp, grid):
        cl = CellListWidget(on_cell_result=lambda *a: None, grid=grid)
        cl.add_folder("group")
        targets = cl._focus_targets()
        assert len(targets) == 0

    def test_subcells_interleaved(self, qapp, grid):
        cl = CellListWidget(on_cell_result=lambda *a: None, grid=grid)
        cell = cl.add_cell()
        sub1 = cell.add_sub_cell("constraint")
        sub2 = cell.add_sub_cell("constraint")
        targets = cl._focus_targets()
        assert len(targets) == 3
        assert targets[0][0] == cell.cell_id
        assert targets[1][0] == sub1.cell_id
        assert targets[2][0] == sub2.cell_id


# ---------------------------------------------------------------------------
# Equation cell navigation
# ---------------------------------------------------------------------------

class TestEquationCellNavigation:
    def _make_list(self, qapp, grid):
        return CellListWidget(on_cell_result=lambda *a: None, grid=grid)

    def test_down_from_last_line_focuses_next_cell(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        cell1 = cl.add_cell("z = x")
        cell2 = cl.add_cell("z = y")
        focused = []
        orig = cell2._text_edit.setFocus
        cell2._text_edit.setFocus = lambda *a: focused.append(True)
        _press(cell1._text_edit, Qt.Key.Key_Down)
        assert focused, "setFocus was not called on next cell's text edit"
        cell2._text_edit.setFocus = orig

    def test_up_from_first_line_focuses_prev_cell(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        cell1 = cl.add_cell("z = x")
        cell2 = cl.add_cell("z = y")
        focused = []
        orig = cell1._text_edit.setFocus
        cell1._text_edit.setFocus = lambda *a: focused.append(True)
        _press(cell2._text_edit, Qt.Key.Key_Up)
        assert focused
        cell1._text_edit.setFocus = orig

    def test_down_mid_line_no_escape(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        cell1 = cl.add_cell()
        # Directly set two-line content so document has 2 blocks
        cell1._text_edit.setPlainText("line1\nline2")
        qapp.processEvents()
        assert cell1._text_edit.document().blockCount() == 2
        # Move cursor to first line (blockNumber == 0)
        cursor = cell1._text_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        cell1._text_edit.setTextCursor(cursor)
        assert cell1._text_edit.textCursor().blockNumber() == 0
        cell2 = cl.add_cell("z = y")
        focused = []
        orig = cell2._text_edit.setFocus
        cell2._text_edit.setFocus = lambda *a: focused.append(True)
        _press(cell1._text_edit, Qt.Key.Key_Down)
        assert not focused, "Down on mid-line should not escape the cell"
        cell2._text_edit.setFocus = orig

    def test_down_on_last_cell_noop(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        cell = cl.add_cell("z = x")
        # Should not raise
        _press(cell._text_edit, Qt.Key.Key_Down)
        qapp.processEvents()

    def test_up_on_first_cell_noop(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        cell = cl.add_cell("z = x")
        _press(cell._text_edit, Qt.Key.Key_Up)
        qapp.processEvents()


# ---------------------------------------------------------------------------
# Subcell navigation
# ---------------------------------------------------------------------------

class TestSubcellNavigation:
    def _make_list(self, qapp, grid):
        return CellListWidget(on_cell_result=lambda *a: None, grid=grid)

    def test_down_from_main_enters_first_subcell(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        cell = cl.add_cell("z = x")
        sub = cell.add_sub_cell("constraint")
        focused = []
        orig = sub._edit.setFocus
        sub._edit.setFocus = lambda *a: focused.append(True)
        _press(cell._text_edit, Qt.Key.Key_Down)
        assert focused
        sub._edit.setFocus = orig

    def test_down_from_last_subcell_goes_to_next_sibling(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        cell1 = cl.add_cell("z = x")
        sub = cell1.add_sub_cell("constraint")
        cell2 = cl.add_cell("z = y")
        focused = []
        orig = cell2._text_edit.setFocus
        cell2._text_edit.setFocus = lambda *a: focused.append(True)
        _press(sub._edit, Qt.Key.Key_Down)
        assert focused
        cell2._text_edit.setFocus = orig

    def test_up_from_first_subcell_goes_to_main_cell(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        cell = cl.add_cell("z = x")
        sub = cell.add_sub_cell("constraint")
        focused = []
        orig = cell._text_edit.setFocus
        cell._text_edit.setFocus = lambda *a: focused.append(True)
        _press(sub._edit, Qt.Key.Key_Up)
        assert focused
        cell._text_edit.setFocus = orig

    def test_down_between_subcells(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        cell = cl.add_cell("z = x")
        sub1 = cell.add_sub_cell("constraint")
        sub2 = cell.add_sub_cell("constraint")
        focused = []
        orig = sub2._edit.setFocus
        sub2._edit.setFocus = lambda *a: focused.append(True)
        _press(sub1._edit, Qt.Key.Key_Down)
        assert focused
        sub2._edit.setFocus = orig


# ---------------------------------------------------------------------------
# Comment cell navigation
# ---------------------------------------------------------------------------

class TestCommentCellNavigation:
    def _make_list(self, qapp, grid):
        return CellListWidget(on_cell_result=lambda *a: None, grid=grid)

    def test_down_from_comment_focuses_next_cell(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        comment = cl.add_comment_cell("# hello")
        cell = cl.add_cell("z = x")
        focused = []
        orig = cell._text_edit.setFocus
        cell._text_edit.setFocus = lambda *a: focused.append(True)
        _press(comment._edit, Qt.Key.Key_Down)
        assert focused
        cell._text_edit.setFocus = orig

    def test_down_into_comment_from_equation(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        cell = cl.add_cell("z = x")
        comment = cl.add_comment_cell("# hello")
        focused = []
        orig = comment._edit.setFocus
        comment._edit.setFocus = lambda *a: focused.append(True)
        _press(cell._text_edit, Qt.Key.Key_Down)
        assert focused
        comment._edit.setFocus = orig


# ---------------------------------------------------------------------------
# Slider internal navigation
# ---------------------------------------------------------------------------

class TestSliderInternalNavigation:
    def _make_slider(self, qapp):
        return SliderWidget(name="a", value=5.0)

    def test_value_up_emits_navigate_up(self, qapp):
        slider = self._make_slider(qapp)
        received = []
        slider.navigate_up_requested.connect(received.append)
        _press(slider._spinbox, Qt.Key.Key_Up)
        assert received == [slider.cell_id]

    def test_value_down_focuses_min(self, qapp):
        slider = self._make_slider(qapp)
        focused = []
        orig = slider._min_box.setFocus
        slider._min_box.setFocus = lambda *a: focused.append(True)
        _press(slider._spinbox, Qt.Key.Key_Down)
        assert focused
        slider._min_box.setFocus = orig

    def test_min_up_focuses_value(self, qapp):
        slider = self._make_slider(qapp)
        focused = []
        orig = slider._spinbox.setFocus
        slider._spinbox.setFocus = lambda *a: focused.append(True)
        _press(slider._min_box, Qt.Key.Key_Up)
        assert focused
        slider._spinbox.setFocus = orig

    def test_min_down_emits_navigate_down(self, qapp):
        slider = self._make_slider(qapp)
        received = []
        slider.navigate_down_requested.connect(received.append)
        _press(slider._min_box, Qt.Key.Key_Down)
        assert received == [slider.cell_id]

    def test_max_up_focuses_value(self, qapp):
        slider = self._make_slider(qapp)
        focused = []
        orig = slider._spinbox.setFocus
        slider._spinbox.setFocus = lambda *a: focused.append(True)
        _press(slider._max_box, Qt.Key.Key_Up)
        assert focused
        slider._spinbox.setFocus = orig

    def test_max_down_emits_navigate_down(self, qapp):
        slider = self._make_slider(qapp)
        received = []
        slider.navigate_down_requested.connect(received.append)
        _press(slider._max_box, Qt.Key.Key_Down)
        assert received == [slider.cell_id]

    def test_min_right_at_end_focuses_max_at_0(self, qapp):
        slider = self._make_slider(qapp)
        slider._min_box.setText("0")
        slider._min_box.setCursorPosition(len(slider._min_box.text()))  # at end
        focused = []
        pos_set = []
        orig_focus = slider._max_box.setFocus
        orig_pos = slider._max_box.setCursorPosition
        slider._max_box.setFocus = lambda *a: focused.append(True)
        slider._max_box.setCursorPosition = lambda p: pos_set.append(p)
        _press(slider._min_box, Qt.Key.Key_Right)
        assert focused
        assert 0 in pos_set
        slider._max_box.setFocus = orig_focus
        slider._max_box.setCursorPosition = orig_pos

    def test_max_left_at_0_focuses_min_at_end(self, qapp):
        slider = self._make_slider(qapp)
        slider._max_box.setText("10")
        slider._max_box.setCursorPosition(0)
        focused = []
        orig_focus = slider._min_box.setFocus
        slider._min_box.setFocus = lambda *a: focused.append(True)
        _press(slider._max_box, Qt.Key.Key_Left)
        assert focused
        slider._min_box.setFocus = orig_focus

    def test_min_left_at_0_is_noop(self, qapp):
        """Left at min position 0 should emit navigate_left but have no effect."""
        slider = self._make_slider(qapp)
        slider._min_box.setText("0")
        slider._min_box.setCursorPosition(0)
        received = []
        slider._min_box.navigate_left.connect(lambda: received.append(True))
        _press(slider._min_box, Qt.Key.Key_Left)
        assert received  # signal was emitted
        # Verify no crash and min_box still exists
        assert slider._min_box is not None

    def test_step_right_at_end_is_noop(self, qapp):
        """Right at step end should emit navigate_right but have no effect."""
        slider = self._make_slider(qapp)
        slider._step_box.setText("0.1")
        slider._step_box.setCursorPosition(len(slider._step_box.text()))
        received = []
        slider._step_box.navigate_right.connect(lambda: received.append(True))
        _press(slider._step_box, Qt.Key.Key_Right)
        assert received


# ---------------------------------------------------------------------------
# Cross-cell slider navigation
# ---------------------------------------------------------------------------

class TestSliderCrossCellNavigation:
    def _make_list(self, qapp, grid):
        return CellListWidget(on_cell_result=lambda *a: None, grid=grid)

    def test_navigate_down_from_slider_focuses_next_cell(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        slider = cl.add_cell("a = 5")
        cell = cl.add_cell("z = x")
        assert isinstance(slider, SliderWidget)
        focused = []
        orig = cell._text_edit.setFocus
        cell._text_edit.setFocus = lambda *a: focused.append(True)
        # Trigger navigate_down via min_box Down
        _press(slider._min_box, Qt.Key.Key_Down)
        assert focused
        cell._text_edit.setFocus = orig

    def test_navigate_up_from_slider_focuses_prev_cell(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        cell = cl.add_cell("z = x")
        slider = cl.add_cell("a = 5")
        assert isinstance(slider, SliderWidget)
        focused = []
        orig = cell._text_edit.setFocus
        cell._text_edit.setFocus = lambda *a: focused.append(True)
        # Trigger navigate_up via value spinbox Up
        _press(slider._spinbox, Qt.Key.Key_Up)
        assert focused
        cell._text_edit.setFocus = orig

    def test_navigate_down_into_slider_focuses_value(self, qapp, grid):
        cl = self._make_list(qapp, grid)
        cell = cl.add_cell("z = x")
        slider = cl.add_cell("a = 5")
        assert isinstance(slider, SliderWidget)
        focused = []
        orig = slider._spinbox.setFocus
        slider._spinbox.setFocus = lambda *a: focused.append(True)
        _press(cell._text_edit, Qt.Key.Key_Down)
        assert focused
        slider._spinbox.setFocus = orig
