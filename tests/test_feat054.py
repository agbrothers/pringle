"""
FEAT-051 (design-doc) — Auto-scroll cell list to follow keyboard navigation focus.

QScrollArea.ensureWidgetVisible is called after every focus-moving operation:
arrow-key navigation, Enter (new cell), Backspace (delete cell), and morph.
"""

import sys
from unittest.mock import patch
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


# ---------------------------------------------------------------------------
# Arrow-key navigation
# ---------------------------------------------------------------------------

def test_navigate_down_calls_ensure_visible(clist):
    c0 = clist.add_cell("x = 1")
    c1 = clist.add_cell("y = 2", after_id=c0.cell_id)

    with patch.object(clist._scroll, "ensureWidgetVisible") as mock_ewv:
        clist._on_navigate_down(c0.cell_id)
        mock_ewv.assert_called_once()
        assert mock_ewv.call_args[0][0] is c1.primary_focus_widget()


def test_navigate_up_calls_ensure_visible(clist):
    c0 = clist.add_cell("a = 10")
    c1 = clist.add_cell("b = 20", after_id=c0.cell_id)

    with patch.object(clist._scroll, "ensureWidgetVisible") as mock_ewv:
        clist._on_navigate_up(c1.cell_id)
        mock_ewv.assert_called_once()
        assert mock_ewv.call_args[0][0] is c0.primary_focus_widget()


def test_navigate_down_at_last_cell_no_call(clist):
    cl = CellListWidget(on_cell_result=lambda cid, r, s: None)
    c = cl.add_cell("z = 99")
    with patch.object(cl._scroll, "ensureWidgetVisible") as mock_ewv:
        cl._on_navigate_down(c.cell_id)
        mock_ewv.assert_not_called()


def test_navigate_up_at_first_cell_no_call(clist):
    cl = CellListWidget(on_cell_result=lambda cid, r, s: None)
    c = cl.add_cell("w = 1")
    with patch.object(cl._scroll, "ensureWidgetVisible") as mock_ewv:
        cl._on_navigate_up(c.cell_id)
        mock_ewv.assert_not_called()


# ---------------------------------------------------------------------------
# New cell creation (Enter path)
# ---------------------------------------------------------------------------

def test_add_cell_calls_ensure_visible(qapp, clist):
    # ensureWidgetVisible is deferred via QTimer.singleShot — must processEvents first
    c0 = clist.add_cell("p = 5")
    qapp.processEvents()  # drain c0's own deferred scroll
    with patch.object(clist._scroll, "ensureWidgetVisible") as mock_ewv:
        c1 = clist.add_cell(after_id=c0.cell_id)
        mock_ewv.assert_not_called()   # not synchronous
        qapp.processEvents()
        mock_ewv.assert_called_once_with(c1)


def test_add_comment_cell_calls_ensure_visible(qapp, clist):
    c0 = clist.add_cell("q = 7")
    qapp.processEvents()
    with patch.object(clist._scroll, "ensureWidgetVisible") as mock_ewv:
        cc = clist.add_comment_cell(after_id=c0.cell_id)
        mock_ewv.assert_not_called()
        qapp.processEvents()
        mock_ewv.assert_called_once_with(cc)


# ---------------------------------------------------------------------------
# Delete cell (Backspace path)
# ---------------------------------------------------------------------------

def test_remove_cell_calls_ensure_visible(clist):
    c0 = clist.add_cell("r = 1")
    c1 = clist.add_cell("s = 2", after_id=c0.cell_id)

    with patch.object(clist._scroll, "ensureWidgetVisible") as mock_ewv:
        clist.remove_cell(c1.cell_id)
        mock_ewv.assert_called_once_with(c0)
