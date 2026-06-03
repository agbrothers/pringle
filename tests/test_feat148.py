"""
FEAT-148 tests: highlight the active (focused) cell with a #222222 background.

The CellListWidget tracks app-wide focus and toggles a dynamic ``active``
property on the cell that owns the focus widget, so theme.qss can paint it.

Tests validate:
- Focusing a cell's field marks that cell active (and only that cell).
- Moving focus to another cell moves the highlight (one active at a time).
- Clearing focus / leaving the panel clears the highlight (clear-on-blur).
- Focus inside a pop-up parented to a cell keeps that cell active (sticky
  while the cell's own style popover / colour picker is open).
- All four cell types (equation, slider, comment, folder) participate.
- Removing the active cell clears the reference without poking a dead widget.
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt

from pringle.grid import GridConfig, make_grid


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(x_min=-3.0, x_max=3.0, y_min=-3.0, y_max=3.0,
                                z_min=-3.0, z_max=3.0, n=8))


def _noop_result(cid, result, style):
    pass


@pytest.fixture
def cell_list(qapp, grid):
    from pringle.cell_list import CellListWidget
    cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
    cl._set_active_cell(None)  # normalize any focus side effects from setup
    yield cl


# ---------------------------------------------------------------------------
# Core focus-follow behavior
# ---------------------------------------------------------------------------

def test_focus_activates_owning_cell(cell_list):
    cell = cell_list.add_cell("z = x")
    cell_list._on_focus_changed(None, cell.primary_focus_widget())
    assert cell_list._active_cell is cell
    assert cell.property("active") is True


def test_only_one_active_at_a_time(cell_list):
    a = cell_list.add_cell("z = x")
    b = cell_list.add_cell("w = y")
    cell_list._on_focus_changed(None, a.primary_focus_widget())
    cell_list._on_focus_changed(a.primary_focus_widget(), b.primary_focus_widget())
    assert cell_list._active_cell is b
    assert b.property("active") is True
    assert a.property("active") is False


def test_clear_on_blur(cell_list):
    cell = cell_list.add_cell("z = x")
    cell_list._on_focus_changed(None, cell.primary_focus_widget())
    # Focus leaves the panel (no pop-up open) → highlight clears.
    cell_list._on_focus_changed(cell.primary_focus_widget(), None)
    assert cell_list._active_cell is None
    assert cell.property("active") is False


def test_owning_cell_resolves_nested_and_unrelated(cell_list):
    cell = cell_list.add_cell("z = x")
    # A child field resolves up to its cell...
    assert cell_list._owning_cell(cell.primary_focus_widget()) is cell
    # ...an unrelated widget resolves to None.
    assert cell_list._owning_cell(QWidget()) is None
    assert cell_list._owning_cell(None) is None


# ---------------------------------------------------------------------------
# Sticky-while-popover behavior
# ---------------------------------------------------------------------------

def test_sticky_while_popover_open(cell_list):
    cell = cell_list.add_cell("z = x")
    # A pop-up parented to the cell (mirrors the style popover / colour picker).
    popup = QWidget(cell)
    popup.setWindowFlags(Qt.WindowType.Popup)
    # Focus has left the cell's own fields (focus_widget=None) but the cell's
    # pop-up is the active pop-up → the cell stays active.
    assert cell_list._active_cell_for(None, popup) is cell


def test_no_popup_clears(cell_list):
    cell_list.add_cell("z = x")
    assert cell_list._active_cell_for(None, None) is None


# ---------------------------------------------------------------------------
# All cell types
# ---------------------------------------------------------------------------

def test_equation_cell_highlights(cell_list):
    cell = cell_list.add_cell("z = x")
    cell_list._on_focus_changed(None, cell.primary_focus_widget())
    assert cell.property("active") is True


def test_slider_cell_highlights(cell_list):
    cell = cell_list.add_cell("k = 3")  # name = number → SliderWidget
    from pringle.slider_widget import SliderWidget
    assert isinstance(cell, SliderWidget)
    cell_list._on_focus_changed(None, cell.primary_focus_widget())
    assert cell.property("active") is True


def test_comment_cell_highlights(cell_list):
    cell = cell_list.add_comment_cell("# note")
    cell_list._on_focus_changed(None, cell.primary_focus_widget())
    assert cell.property("active") is True


def test_folder_cell_highlights(cell_list):
    folder = cell_list.add_folder()
    header = folder.findChild(QWidget, "folder_header")
    cell_list._on_focus_changed(None, header)
    assert cell_list._active_cell is folder
    assert folder.property("active") is True


# ---------------------------------------------------------------------------
# Lifetime
# ---------------------------------------------------------------------------

def test_remove_active_cell_clears_reference(cell_list):
    cell = cell_list.add_cell("z = x")
    cell_list._on_focus_changed(None, cell.primary_focus_widget())
    assert cell_list._active_cell is cell
    cell_list.remove_cell(cell.cell_id)
    assert cell_list._active_cell is None


# ---------------------------------------------------------------------------
# Render regression: the body subtree must actually repaint #222222, not just
# carry the property. The descendant rule (CellWidget[active] #cell_content ...)
# only repaints if the whole subtree is re-polished — guards against that bug.
# ---------------------------------------------------------------------------

def _body_pixel(cell):
    """Background colour painted in the cell's content (text) area."""
    cell.resize(360, max(60, cell.sizeHint().height()))
    cell.ensurePolished()
    img = cell.grab().toImage()
    return img.pixelColor(img.width() - 30, img.height() // 2).name()


def test_active_cell_body_actually_repaints(qapp, grid):
    from pathlib import Path
    import pringle
    from pringle.cell_list import CellListWidget

    prev_qss = qapp.styleSheet()
    qapp.setStyleSheet((Path(pringle.__file__).parent / "theme.qss").read_text())
    try:
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("z = x")
        cl._set_active_cell(None)
        assert _body_pixel(cell) == "#111111"
        cl._on_focus_changed(None, cell.primary_focus_widget())
        assert _body_pixel(cell) == "#222222"
    finally:
        qapp.setStyleSheet(prev_qss)  # don't pollute the shared QApplication


def test_indented_active_cell_does_not_bleed(qapp, grid):
    """An active cell inside a folder keeps its 16px indent strip panel-coloured;
    the #222222 band must start at the swatch, not the panel's left edge."""
    from pathlib import Path
    import pringle
    from pringle.cell_list import CellListWidget

    prev_qss = qapp.styleSheet()
    qapp.setStyleSheet((Path(pringle.__file__).parent / "theme.qss").read_text())
    try:
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("z = x")
        cl._apply_indent(cell, True)
        cl._on_focus_changed(None, cell.primary_focus_widget())
        cell.resize(360, max(60, cell.sizeHint().height()))
        cell.ensurePolished()
        img = cell.grab().toImage()
        ymid = img.height() // 2
        assert img.pixelColor(4, ymid).name() == "#111111"          # indent strip
        assert img.pixelColor(img.width() - 30, ymid).name() == "#222222"  # body band
    finally:
        qapp.setStyleSheet(prev_qss)
