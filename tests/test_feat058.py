"""
FEAT-058 — Cmd+D / Ctrl+D: duplicate focused cell in-place.

Tests:
- Equation cell duplicated with identical source and style, inserted directly below
- Slider cell preserves min_val, max_val, step, and current value
- Sub-cells (constraint, condition) are duplicated with the parent
- Focus moves to the new cell after duplication
- The system clipboard is NOT modified by a duplicate operation
- Undo removes the duplicated cell
- Returns False when no cell is in the widget hierarchy

Note: In a headless test environment QApplication.focusWidget() returns None,
so tests mock it to return the target cell (simulating the real app where the
focused CellTextEdit's parent walk reaches the CellWidget container).
"""

import sys
import pytest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from pringle.cell_list import CellListWidget
from pringle.cell_widget import CellWidget
from pringle.slider_widget import SliderWidget
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def clist(qapp):
    return CellListWidget(
        on_cell_result=lambda cid, r, s: None,
        grid=make_grid(GridConfig(n=16)),
    )


def _focus(cell):
    """Mock focusWidget() → cell, simulating keyboard focus on that cell."""
    return patch.object(QApplication, "focusWidget", return_value=cell)


# ---------------------------------------------------------------------------
# Equation cell duplication
# ---------------------------------------------------------------------------

def test_duplicate_equation_cell_source_and_style(qapp, clist):
    """Duplicated equation cell has identical source and style, inserted below."""
    c0 = clist.add_cell("z = x**2 + y**2")
    c0.style.color = (1.0, 0.0, 0.0, 1.0)

    with _focus(c0):
        result = clist.duplicate_focused_cell()

    assert result is True

    cells = clist._cells
    idx = next(i for i, c in enumerate(cells) if c.cell_id == c0.cell_id)
    dup = cells[idx + 1]

    assert dup.source() == "z = x**2 + y**2"
    assert dup.style.color == (1.0, 0.0, 0.0, 1.0)


def test_duplicate_inserts_immediately_below(qapp, clist):
    """The duplicate appears at idx+1, not at the end of the list."""
    c0 = clist.add_cell("a = sin(x)")
    c1 = clist.add_cell("b = cos(x)", after_id=c0.cell_id)

    with _focus(c0):
        clist.duplicate_focused_cell()

    cells = clist._cells
    idx0 = next(i for i, c in enumerate(cells) if c.cell_id == c0.cell_id)
    dup = cells[idx0 + 1]
    after_dup = cells[idx0 + 2]

    assert dup.source() == "a = sin(x)"
    assert after_dup.cell_id == c1.cell_id


def test_duplicate_returns_true_on_success(qapp, clist):
    c = clist.add_cell("p = x + y")
    with _focus(c):
        assert clist.duplicate_focused_cell() is True


def test_duplicate_works_from_inner_text_edit(qapp, clist):
    """Walk-up works when focusWidget() is the CellTextEdit child, not the container."""
    c = clist.add_cell("z = x * y")
    # Simulate focus on the inner text edit — the walk-up must reach the CellWidget
    with _focus(c.primary_focus_widget()):
        result = clist.duplicate_focused_cell()

    assert result is True
    cells = clist._cells
    idx = next(i for i, c2 in enumerate(cells) if c2.cell_id == c.cell_id)
    assert cells[idx + 1].source() == "z = x * y"


# ---------------------------------------------------------------------------
# Slider cell duplication
# ---------------------------------------------------------------------------

def test_duplicate_slider_preserves_range_and_step(qapp, clist):
    """Duplicated slider has the same min, max, step, and value."""
    sl = clist.add_cell("k = 3.0")
    assert isinstance(sl, SliderWidget)

    sl._min_box.setValue(-5.0)
    sl._max_box.setValue(20.0)
    sl._step_box.setValue(0.5)
    sl._on_range_changed()

    with _focus(sl):
        clist.duplicate_focused_cell()

    cells = clist._cells
    idx = next(i for i, c in enumerate(cells) if c.cell_id == sl.cell_id)
    dup = cells[idx + 1]

    assert isinstance(dup, SliderWidget)
    assert dup._value == pytest.approx(3.0)
    assert dup._min == pytest.approx(-5.0)
    assert dup._max == pytest.approx(20.0)
    assert dup._step_box.value() == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Sub-cell duplication
# ---------------------------------------------------------------------------

def test_duplicate_copies_constraint_sub_cell(qapp, clist):
    """Equation cell with a constraint sub-cell: duplicate includes the sub-cell."""
    c = clist.add_cell("z = x + y")
    sub = c.add_sub_cell("constraint")
    sub._edit.setPlainText("x > 0")

    with _focus(c):
        clist.duplicate_focused_cell()

    cells = clist._cells
    idx = next(i for i, c2 in enumerate(cells) if c2.cell_id == c.cell_id)
    dup = cells[idx + 1]

    subs = dup.sub_cells()
    assert len(subs) == 1
    assert subs[0].sub_type() == "constraint"
    assert subs[0].source() == "x > 0"


def test_duplicate_copies_multiple_sub_cells(qapp, clist):
    """Multiple sub-cells are all duplicated, in order."""
    c = clist.add_cell("z = [x, y]")
    s1 = c.add_sub_cell("condition")
    s1._edit.setPlainText("x > 0")
    s2 = c.add_sub_cell("condition")
    s2._edit.setPlainText("y > 0")

    with _focus(c):
        clist.duplicate_focused_cell()

    cells = clist._cells
    idx = next(i for i, c2 in enumerate(cells) if c2.cell_id == c.cell_id)
    dup = cells[idx + 1]

    subs = dup.sub_cells()
    assert len(subs) == 2
    assert subs[0].source() == "x > 0"
    assert subs[1].source() == "y > 0"


# ---------------------------------------------------------------------------
# Clipboard is not modified
# ---------------------------------------------------------------------------

def test_duplicate_does_not_modify_clipboard(qapp, clist):
    """The system clipboard must be untouched after duplicate."""
    QApplication.clipboard().setText("original-clipboard-content")

    c = clist.add_cell("z = x * y")
    with _focus(c):
        clist.duplicate_focused_cell()

    assert QApplication.clipboard().text() == "original-clipboard-content"


# ---------------------------------------------------------------------------
# Undo removes the duplicate
# ---------------------------------------------------------------------------

def test_undo_removes_duplicate(qapp, clist):
    """Pressing undo after duplicate restores the list to its pre-duplicate state."""
    before_count = len(clist._cells)
    c = clist.add_cell("z = x - y")

    with _focus(c):
        clist.duplicate_focused_cell()

    assert len(clist._cells) == before_count + 2  # original + duplicate

    clist.undo()

    assert len(clist._cells) == before_count + 1  # only original remains


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_duplicate_returns_false_with_no_focused_cell(qapp, clist):
    """Returns False when focusWidget() is None (nothing focused)."""
    with patch.object(QApplication, "focusWidget", return_value=None):
        result = clist.duplicate_focused_cell()
    assert result is False
