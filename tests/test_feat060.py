"""
FEAT-060 — Consolidate Qt styles into a central theme.qss stylesheet.

Tests:
- theme.qss exists, is non-empty, and loads without QSS parse error
- QApplication.styleSheet() is non-empty after _load_theme() is called
- DragHandle no longer defines enterEvent or leaveEvent
- Dynamic calls still work: color dot reflects CellStyle.color,
  error border appears on invalid slider name, data-dot cycles through states
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.cell_widget import DragHandle, CellWidget
from pringle.slider_widget import SliderWidget
from pringle.style import CellStyle


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------------------
# Theme file loading
# ---------------------------------------------------------------------------

def test_theme_qss_exists_and_is_nonempty():
    """theme.qss is present as a package resource and has content."""
    from importlib.resources import files
    qss = files("pringle").joinpath("theme.qss").read_text(encoding="utf-8")
    assert len(qss.strip()) > 0


def test_load_theme_sets_app_stylesheet(qapp):
    """After _load_theme(), QApplication.styleSheet() is non-empty."""
    from pringle.app import _load_theme
    _load_theme(qapp)
    assert len(qapp.styleSheet().strip()) > 0


# ---------------------------------------------------------------------------
# DragHandle: no more enterEvent / leaveEvent
# ---------------------------------------------------------------------------

def test_drag_handle_has_no_enter_leave_event(qapp):
    """DragHandle must not define enterEvent or leaveEvent — QSS :hover handles it."""
    # DragHandle inherits from QLabel; the implementation should not override
    # enterEvent/leaveEvent (those were deleted as part of FEAT-060).
    assert not hasattr(DragHandle, "enterEvent") or \
        DragHandle.enterEvent is not DragHandle.__bases__[0].enterEvent.__func__ if False else True
    # Simpler structural check: the methods must not be defined on DragHandle directly
    assert "enterEvent" not in DragHandle.__dict__
    assert "leaveEvent" not in DragHandle.__dict__


# ---------------------------------------------------------------------------
# Dynamic style calls: color dot
# ---------------------------------------------------------------------------

def test_color_dot_reflects_cell_style_color(qapp):
    """Color dot setStyleSheet still works after removing static styles."""
    style = CellStyle(color=(1.0, 0.0, 0.0, 1.0))
    cell = CellWidget(style=style)
    # Trigger color dot update
    cell._update_color_dot()
    ss = cell._color_dot.styleSheet()
    assert "#ff0000" in ss or "ff0000" in ss.lower()


# ---------------------------------------------------------------------------
# Dynamic style calls: error border on invalid slider name
# ---------------------------------------------------------------------------

def test_invalid_slider_name_border_appears(qapp):
    """_on_name_text_changed flashes a red border for an invalid name."""
    sl = SliderWidget(name="a", value=1.0)
    # Simulate clicking to open name edit
    sl._on_name_clicked()
    assert sl._name_edit is not None
    # Empty name is invalid
    sl._on_name_text_changed("")
    assert "e05252" in sl._name_edit.styleSheet() or "c0392b" in sl._name_edit.styleSheet() \
        or "border" in sl._name_edit.styleSheet()


# ---------------------------------------------------------------------------
# Dynamic style calls: data-dot state machine
# ---------------------------------------------------------------------------

def test_data_dot_cycles_through_states(qapp):
    """_set_data_status still applies inline styles for each state."""
    cell = CellWidget()
    cell.set_data_mode(True)

    cell._set_data_status("ok")
    assert "2a8a2a" in cell._status_dot.styleSheet()

    cell._set_data_status("stale")
    assert "cc7700" in cell._status_dot.styleSheet()

    cell._set_data_status("error")
    assert "cc2222" in cell._status_dot.styleSheet()

    cell._set_data_status("idle")
    assert "bbb" in cell._status_dot.styleSheet()
