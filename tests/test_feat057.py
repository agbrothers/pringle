"""
FEAT-057 tests: cfg axis bounds object in the expression namespace.

Tests validate:
- cfg.x_min/x_max etc. read back the current grid config values
- cfg.x_max = 5 causes bounds_override to emit the correct floats
- Slider-driven cfg write (a = 2; cfg.x_max = a) fires bounds_override on value change
- If no cell writes to cfg, bounds_override is NOT emitted
- Read-only use (z = sin(cfg.x_max * x)) evaluates without an "Undefined" warning
- cfg.__class__ in a cell raises SecurityError
- get_cfg_writes returns correct attribute sets
"""

import sys
import pytest
import numpy as np

from PyQt6.QtWidgets import QApplication

from pringle.grid import GridConfig, make_grid
from pringle.safety import SecurityError, check_ast, get_cfg_writes


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
    return CellListWidget(on_cell_result=_noop_result, grid=grid)


# ---------------------------------------------------------------------------
# get_cfg_writes unit tests
# ---------------------------------------------------------------------------

class TestGetCfgWrites:
    def test_single_write(self):
        assert get_cfg_writes("cfg.x_max = t") == {"x_max"}

    def test_multiple_writes(self):
        src = "cfg.x_min = -a\ncfg.x_max = a"
        result = get_cfg_writes(src)
        assert result == {"x_min", "x_max"}

    def test_read_only_returns_empty(self):
        assert get_cfg_writes("z = sin(cfg.x_max * x)") == set()

    def test_plain_cfg_reference_returns_empty(self):
        assert get_cfg_writes("v = cfg.x_max") == set()

    def test_invalid_syntax_returns_empty(self):
        assert get_cfg_writes("cfg.x_max =") == set()

    def test_augmented_assign_not_included(self):
        # cfg.x_max += 1 is an AugAssign, not a plain Assign — out of scope
        assert get_cfg_writes("cfg.x_max += 1") == set()


# ---------------------------------------------------------------------------
# Safety checker: cfg dunder access raises SecurityError
# ---------------------------------------------------------------------------

class TestCfgDunderBlocked:
    def test_cfg_dunder_class_raises(self):
        with pytest.raises(SecurityError):
            check_ast("x = cfg.__class__")

    def test_cfg_plain_attribute_passes(self):
        # Should not raise
        check_ast("z = sin(cfg.x_max * x)")

    def test_cfg_write_passes(self):
        check_ast("cfg.x_max = t")


# ---------------------------------------------------------------------------
# AxisConfig injection — cfg values match grid config
# ---------------------------------------------------------------------------

class TestCfgValues:
    def test_cfg_reads_grid_bounds(self, cell_list):
        """cfg.x_min/x_max values match the grid config at eval time."""
        emitted = []
        cell_list.bounds_override.connect(lambda *a: emitted.append(a))

        # A cell that exports the cfg values so we can inspect them
        cell_list.add_cell("x_min_val = cfg.x_min")
        cell_list.add_cell("x_max_val = cfg.x_max")

        assert cell_list._shared_ns.get("x_min_val") == pytest.approx(-3.0)
        assert cell_list._shared_ns.get("x_max_val") == pytest.approx(3.0)
        # Read-only usage must NOT emit bounds_override
        assert emitted == []

    def test_cfg_no_undefined_warning_for_read(self, qapp, grid):
        """A cell reading cfg.x_max should not produce an 'Undefined' warning."""
        from pringle.cell_list import CellListWidget
        warnings_seen = []

        def capture(cid, result, style):
            if result.warning:
                warnings_seen.append(result.warning)

        cl = CellListWidget(on_cell_result=capture, grid=grid)
        cl.add_cell("v = cfg.x_max + 1")

        assert not any("Undefined" in w for w in warnings_seen)


# ---------------------------------------------------------------------------
# Write direction — bounds_override emitted
# ---------------------------------------------------------------------------

class TestCfgWrite:
    def test_cfg_write_emits_bounds_override(self, qapp, grid):
        """cfg.x_max = 5 causes bounds_override to fire with correct x_max."""
        from pringle.cell_list import CellListWidget
        emitted = []
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.bounds_override.connect(lambda *a: emitted.append(a))

        cl.add_cell("cfg.x_max = 5.0")

        assert len(emitted) == 1
        # emitted[0] = (x_min, x_max, y_min, y_max, z_min, z_max)
        assert emitted[0][1] == pytest.approx(5.0)   # x_max
        assert emitted[0][0] == pytest.approx(-3.0)  # x_min unchanged

    def test_no_emission_when_cfg_not_written(self, qapp, grid):
        """Pure read usage must not emit bounds_override."""
        from pringle.cell_list import CellListWidget
        emitted = []
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.bounds_override.connect(lambda *a: emitted.append(a))

        cl.add_cell("v = cfg.x_max * 2")

        assert emitted == []

    def test_slider_driven_cfg_write(self, qapp, grid):
        """Slider a connected via cfg.x_max = a fires bounds_override on value change."""
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget
        emitted = []
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid, eval_threaded=False)
        cl.bounds_override.connect(lambda *a: emitted.append(a))

        cl.add_cell("a = 1.0")  # becomes slider
        cl.add_cell("cfg.x_max = a")

        # Initial eval should have fired bounds_override
        assert len(emitted) >= 1
        assert emitted[-1][1] == pytest.approx(1.0)

        # Change slider value
        emitted.clear()
        slider = next(c for c in cl._cells if isinstance(c, SliderWidget) and c.name == "a")
        slider.set_value(7.0)

        assert len(emitted) >= 1
        assert emitted[-1][1] == pytest.approx(7.0)

    def test_write_all_six_bounds(self, qapp, grid):
        """A cell writing all six cfg attributes emits all six correctly."""
        from pringle.cell_list import CellListWidget
        emitted = []
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.bounds_override.connect(lambda *a: emitted.append(a))

        src = "\n".join([
            "cfg.x_min = -1.0",
            "cfg.x_max = 1.0",
            "cfg.y_min = -2.0",
            "cfg.y_max = 2.0",
            "cfg.z_min = -4.0",
            "cfg.z_max = 4.0",
        ])
        cl.add_cell(src)

        assert len(emitted) == 1
        assert emitted[0] == pytest.approx((-1.0, 1.0, -2.0, 2.0, -4.0, 4.0))
