"""
BUG-043 — Slider morph fires eagerly on every keystroke instead of on Enter/focus loss.

The morph from CellWidget → SliderWidget must be deferred until commit (focus-out),
not fired on every keystroke via content_changed.
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from pringle.cell_list import CellListWidget
from pringle.cell_widget import CellWidget
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
    return CellListWidget(
        on_cell_result=lambda cid, r, s: None,
        grid=grid,
    )


class TestSliderMorphDeferred:
    def test_typing_scalar_does_not_morph_mid_edit(self, qapp, clist):
        """content_changed alone must not trigger the slider morph."""
        cell = clist.add_cell()
        assert isinstance(cell, CellWidget)

        # Simulate keystroke-by-keystroke: set source then fire content_changed
        cell.set_source("a = 5")
        # content_changed fires internally via the debounce path, but the morph
        # must NOT have happened yet — the cell should still be a CellWidget.
        assert isinstance(clist._cells[0], CellWidget)

    def test_focus_out_morphs_to_slider(self, qapp, clist):
        """After focus leaves (focus_lost → commit_requested), the cell morphs."""
        cell = clist.add_cell()
        assert isinstance(cell, CellWidget)

        cell.set_source("b = 7")
        # Emit focus_lost to simulate the user clicking away
        cell._text_edit.focus_lost.emit()
        qapp.processEvents()

        morphed = clist._cells[0]
        assert isinstance(morphed, SliderWidget)
        assert morphed.name == "b"
        assert morphed.value == pytest.approx(7.0)

    def test_clear_before_commit_prevents_morph(self, qapp, clist):
        """If the user clears back to a non-scalar before focus-out, no morph."""
        cell = clist.add_cell()
        assert isinstance(cell, CellWidget)

        cell.set_source("c = 3")
        cell.set_source("c = sin(x)")  # no longer a scalar
        cell._text_edit.focus_lost.emit()
        qapp.processEvents()

        # Still a plain CellWidget
        assert isinstance(clist._cells[0], CellWidget)
