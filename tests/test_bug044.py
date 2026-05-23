"""
BUG-044 — Constant values outside default slider range do not morph to slider.

Negative literals like `a = -3` were represented in the AST as
UnaryOp(USub, Constant(3)) rather than Constant(-3), so is_slider_cell
returned False and the morph was silently skipped.
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.cell_list import CellListWidget
from pringle.slider_widget import SliderWidget
from pringle.grid import make_grid, GridConfig
from pringle.preprocess import is_slider_cell


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=32))


class TestIsSliderCellNegative:
    def test_positive_literal(self):
        ok, name, val = is_slider_cell("a = 15")
        assert ok and name == "a" and val == pytest.approx(15.0)

    def test_negative_literal(self):
        ok, name, val = is_slider_cell("a = -3")
        assert ok and name == "a" and val == pytest.approx(-3.0)

    def test_negative_float(self):
        ok, name, val = is_slider_cell("k = -0.5")
        assert ok and name == "k" and val == pytest.approx(-0.5)

    def test_zero(self):
        ok, name, val = is_slider_cell("c = 0")
        assert ok and name == "c" and val == pytest.approx(0.0)

    def test_expression_not_slider(self):
        ok, _, _ = is_slider_cell("a = -x")
        assert not ok


class TestSliderMorphOutOfRange:
    def _make_list(self, qapp, grid):
        return CellListWidget(on_cell_result=lambda *a: None, grid=grid)

    def test_above_default_max_morphs(self, qapp, grid):
        clist = self._make_list(qapp, grid)
        cell = clist.add_cell("a = 15")
        assert isinstance(cell, SliderWidget)
        assert cell.value == pytest.approx(15.0)
        assert cell._max >= 15.0

    def test_negative_morphs(self, qapp, grid):
        clist = self._make_list(qapp, grid)
        cell = clist.add_cell("b = -3")
        assert isinstance(cell, SliderWidget)
        assert cell.value == pytest.approx(-3.0)
        assert cell._min <= -3.0

    def test_zero_uses_default_range(self, qapp, grid):
        clist = self._make_list(qapp, grid)
        cell = clist.add_cell("c = 0")
        assert isinstance(cell, SliderWidget)
        assert cell.value == pytest.approx(0.0)
        assert cell._min == pytest.approx(0.0)
        assert cell._max == pytest.approx(10.0)

    def test_in_range_unchanged(self, qapp, grid):
        clist = self._make_list(qapp, grid)
        cell = clist.add_cell("d = 5")
        assert isinstance(cell, SliderWidget)
        assert cell.value == pytest.approx(5.0)
        assert 5.0 <= cell._max
