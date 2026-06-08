"""
FEAT-183 tests: Export session as standalone Python script.

Validates:
- Preamble contains required imports
- Sliders exported as plain variable assignments
- Equation cells emitted in topological (dependency) order
- Lambda-style cells emitted as `f = lambda ...`
- Recurrence cells include a WARNING comment
- Magic-sink variables listed in trailing comment block
- Comment and folder cells interleaved at their visual position
"""

import sys
import textwrap
import pytest
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from pringle.grid import GridConfig, make_grid


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def grid():
    return make_grid(GridConfig(x_min=-3.0, x_max=3.0, y_min=-3.0, y_max=3.0,
                                z_min=-3.0, z_max=3.0, n=8))


def _noop(cid, result, style):
    pass


@pytest.fixture
def cell_list(qapp, grid):
    from pringle.cell_list import CellListWidget
    return CellListWidget(on_cell_result=_noop, grid=grid)


def _export(cell_list, tmp_path) -> str:
    from pringle.export import export_as_script
    out = tmp_path / "out.py"
    export_as_script(out, cell_list)
    return out.read_text()


# ---------------------------------------------------------------------------
# Preamble
# ---------------------------------------------------------------------------

class TestPreamble:
    def test_always_has_numpy_and_math(self, cell_list, tmp_path):
        script = _export(cell_list, tmp_path)
        assert "import numpy as np" in script
        assert "import math" in script

    def test_numpy_names_only_when_used(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("z = sin(x) * cos(y)")
        script = _export(cl, tmp_path)
        assert "from numpy import" in script
        assert "sin" in script
        assert "cos" in script
        # Names not used should NOT appear in the import block
        assert "zeros" not in script.split("\n")[0:15]  # not in preamble

    def test_scipy_names_only_when_used(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("v = gamma(3.0)")
        script = _export(cl, tmp_path)
        assert "from scipy.special import gamma" in script

    def test_scipy_not_emitted_when_unused(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("a = 1.0")
        script = _export(cl, tmp_path)
        assert "scipy" not in script

    def test_random_import_when_used(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("pts = random.randn(100, 3)")
        script = _export(cl, tmp_path)
        assert "import numpy.random as random" in script

    def test_array_and_zeros_imported_when_used(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("path = zeros((100, 3))")
        cl.add_cell("v = array([1, 2, 3])")
        script = _export(cl, tmp_path)
        assert "from numpy import" in script
        preamble = script[:script.index("\n\n")]
        assert "zeros" in preamble
        assert "array" in preamble


# ---------------------------------------------------------------------------
# Sliders
# ---------------------------------------------------------------------------

class TestSliders:
    def test_slider_fractional_value_stays_float(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("dt = 0.01")
        slider = next(c for c in cl._cells if isinstance(c, SliderWidget))
        slider._step_box.setValue(0.01)
        slider.set_value(0.05)
        script = _export(cl, tmp_path)
        assert "dt = 0.05  # slider" in script

    def test_slider_whole_number_value_emits_int(self, qapp, grid, tmp_path):
        """Any slider whose current value is a whole number exports as int."""
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("k = 100.0")
        slider = next(c for c in cl._cells if isinstance(c, SliderWidget))
        slider.set_value(2000.0)
        script = _export(cl, tmp_path)
        assert "k = 2000  # slider" in script

    def test_slider_whole_value_with_fractional_step_is_int(self, qapp, grid, tmp_path):
        """σ = 10.0 with step=0.1 should still export as int (value-based rule)."""
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("σ = 10.0")
        slider = next(c for c in cl._cells if isinstance(c, SliderWidget))
        slider._step_box.setValue(0.1)  # fractional step
        slider.set_value(10.0)          # but whole value
        script = _export(cl, tmp_path)
        assert "σ = 10  # slider" in script

    def test_slider_before_dependent_equation(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        # Add equation first (visual order), slider second
        cl.add_cell("b = a * 2")
        cl.add_cell("a = 3.0")
        script = _export(cl, tmp_path)
        # In topo order, slider 'a' must come before 'b = a * 2'
        # (3.0 is whole → exported as int)
        assert script.index("a = 3  # slider") < script.index("b = a * 2")


# ---------------------------------------------------------------------------
# Topological order
# ---------------------------------------------------------------------------

class TestTopologicalOrder:
    def test_dependency_before_use(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("c = d + 1")   # visual order: c first
        cl.add_cell("d = 5.0")     # visual order: d second (slider, whole → int)
        script = _export(cl, tmp_path)
        assert script.index("d = 5  # slider") < script.index("c = d + 1")


# ---------------------------------------------------------------------------
# Lambda-style cells
# ---------------------------------------------------------------------------

class TestLambdaCells:
    def test_func_def_becomes_lambda(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("f(x, y) = x**2 + y**2")
        script = _export(cl, tmp_path)
        assert "f = lambda x, y: x**2 + y**2" in script

    def test_single_arg_lambda(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("g(x) = sin(x)")
        script = _export(cl, tmp_path)
        assert "g = lambda x: sin(x)" in script


# ---------------------------------------------------------------------------
# Recurrence
# ---------------------------------------------------------------------------

class TestRecurrence:
    def test_recurrence_generates_for_loop(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cell = cl.add_cell("path = zeros((100, 2))")
        cell.add_sub_cell("recursion")
        cell._sub_cells[-1]._edit.setPlainText("path[n] = path[n-1] * 0.9")
        script = _export(cl, tmp_path)
        assert "for n in range(1, len(path)):" in script
        assert "    path[n] = path[n-1] * 0.9" in script

    def test_initial_condition_emitted_before_loop(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cell = cl.add_cell("path = zeros((100, 3))")
        cell.add_sub_cell("initial_condition")
        cell._sub_cells[-1]._edit.setPlainText("path[0] = array([1, 1, 1])")
        cell.add_sub_cell("recursion")
        cell._sub_cells[-1]._edit.setPlainText("path[n] = path[n-1] + 0.1")
        script = _export(cl, tmp_path)
        assert "path[0] = array([1, 1, 1])" in script
        # Initial condition must precede the for loop
        assert script.index("path[0]") < script.index("for n in range")


# ---------------------------------------------------------------------------
# Magic variable trailing note
# ---------------------------------------------------------------------------

class TestMagicSinks:
    def test_z_listed_in_trailing_block(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("z = sin(x) * cos(y)")
        script = _export(cl, tmp_path)
        # z assignment should still be emitted
        assert "z = sin(x) * cos(y)" in script
        # And z should appear in the trailing renderer-local note
        assert "renderer-local" in script
        trailing = script[script.index("renderer-local"):]
        assert "# z" in trailing


# ---------------------------------------------------------------------------
# Comments and folders
# ---------------------------------------------------------------------------

class TestSpatialSetup:
    def test_cfg_emitted_when_referenced(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("m = cfg.n // 2")
        script = _export(cl, tmp_path)
        assert "cfg = types.SimpleNamespace(" in script
        assert "import types" in script

    def test_xy_grid_emitted_when_referenced(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("z = x**2 + y**2")
        script = _export(cl, tmp_path)
        assert "x, y = np.meshgrid" in script
        assert "indexing='xy'" in script

    def test_spatial_setup_not_emitted_when_unused(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("a = 1.0")
        script = _export(cl, tmp_path)
        assert "import types" not in script
        assert "meshgrid" not in script

    def test_xy_as_lambda_args_does_not_trigger_setup(self, qapp, grid, tmp_path):
        """f(x, y) = x**2 + y**2 binds x, y as lambda params — no grid setup needed."""
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("f(x, y) = x**2 + y**2")
        script = _export(cl, tmp_path)
        assert "meshgrid" not in script


class TestFunctionDefPadding:
    def test_blank_line_before_def(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("a = 1.0")
        cl.add_cell("def foo(x):\n    return x * 2")
        script = _export(cl, tmp_path)
        # blank line must separate the slider assignment from the def
        assert "a = 1  # slider\n\ndef foo" in script

    def test_blank_line_after_def(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("def foo(x):\n    return x")
        cl.add_cell("b = foo(2)")
        script = _export(cl, tmp_path)
        # def block must be followed by a blank line before the next statement
        assert "return x\n\nb = foo(2)" in script

    def test_no_extra_blanks_for_non_def(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_cell("a = 1.0")
        cl.add_cell("b = 2.0")
        script = _export(cl, tmp_path)
        # plain slider assignments should be consecutive with no blank lines between them
        assert "a = 1  # slider\nb = 2  # slider" in script


class TestNonEvaluableCells:
    def test_comment_cell_emitted(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_comment_cell(source="# my note")
        cl.add_cell("a = 1.0")
        script = _export(cl, tmp_path)
        assert "# my note" in script

    def test_folder_header_emitted(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_folder(name="Params")
        cl.add_cell("k = 1.0")
        script = _export(cl, tmp_path)
        assert "# --- Params ---" in script

    def test_comment_appears_before_following_equation(self, qapp, grid, tmp_path):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop, grid=grid)
        cl.add_comment_cell(source="# section header")
        cl.add_cell("v = 42.0")
        script = _export(cl, tmp_path)
        assert script.index("# section header") < script.index("v = 42.0")
