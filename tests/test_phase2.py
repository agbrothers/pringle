"""
Phase 2 tests: expression evaluation engine.

Tests cover: namespace, safety, grid, preprocessing, and the full
run_cell() pipeline including magic variables, constraints, piecewise,
auto-plot shape inference, and error handling.
"""

import numpy as np
import pytest
import imageio.v3 as iio
from pathlib import Path

from pringle.namespace import build_equation_namespace
from pringle.ast_utils import get_free_names
from pringle.grid import GridConfig, make_grid
from pringle.preprocess import preprocess, is_comment_cell, is_slider_cell
from pringle.evaluator import run_cell, apply_constraints
from rendercanvas.offscreen import OffscreenRenderCanvas
from pringle.renderer import PringleRenderer, make_surface_mesh, make_line_mesh, make_scatter_mesh

FRAMES = Path(__file__).parent / "frames"


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=32))


# ---------------------------------------------------------------------------
# Namespace
# ---------------------------------------------------------------------------

class TestNamespace:
    def test_numpy_funcs_available(self):
        ns = build_equation_namespace()
        assert "sin" in ns and "cos" in ns and "pi" in ns

    def test_scipy_funcs_available(self):
        ns = build_equation_namespace()
        assert "gamma" in ns and "norm" in ns and "erf" in ns

    def test_np_alias_available(self):
        ns = build_equation_namespace()
        import numpy as np
        assert ns["np"] is np

    def test_math_module_available(self):
        ns = build_equation_namespace()
        import math
        assert ns["math"] is math

    def test_sin_works(self):
        ns = build_equation_namespace()
        result = ns["sin"](ns["pi"] / 2)
        assert abs(result - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Free-variable extraction
# ---------------------------------------------------------------------------

class TestFreeNames:
    def test_simple(self):
        names = get_free_names("z = sin(x) * cos(y)")
        assert "x" in names and "y" in names and "sin" in names

    def test_excludes_assigned(self):
        names = get_free_names("a = 1\nb = a + 1")
        assert "a" not in names  # a is defined before being used in b

    def test_lambda_args_not_free(self):
        names = get_free_names("f = lambda x, y: x + y")
        # x and y are lambda params — not free
        assert "x" not in names and "y" not in names

    def test_slider_ref(self):
        names = get_free_names("z = a * sin(x)")
        assert "a" in names


# ---------------------------------------------------------------------------
# Preprocessor
# ---------------------------------------------------------------------------

class TestPreprocess:
    def test_func_def(self):
        out, name = preprocess("f(x, y) = x**2 + y**2")
        assert out == "f = lambda x, y: x**2 + y**2"
        assert name == "f"

    def test_no_transform(self):
        out, name = preprocess("z = sin(x) * cos(y)")
        assert out == "z = sin(x) * cos(y)"
        assert name is None

    def test_comment_cell_hash(self):
        assert is_comment_cell("# this is a comment")
        assert is_comment_cell("# line 1\n# line 2")

    def test_comment_cell_docstring(self):
        assert is_comment_cell('"""This is a comment"""')
        assert is_comment_cell("'single quote comment'")

    def test_empty_is_comment(self):
        assert is_comment_cell("")
        assert is_comment_cell("   ")

    def test_slider_cell(self):
        ok, name, val = is_slider_cell("a = 1.5")
        assert ok and name == "a" and val == 1.5

    def test_slider_int(self):
        ok, name, val = is_slider_cell("n = 10")
        assert ok and name == "n" and val == 10.0

    def test_not_slider_magic(self):
        ok, _, _ = is_slider_cell("z = 1.0")
        assert not ok  # z is a magic name

    def test_not_slider_expr(self):
        ok, _, _ = is_slider_cell("a = sin(x)")
        assert not ok

    # FEAT-041: t is no longer a spatial name
    def test_t_is_slider(self):
        ok, name, val = is_slider_cell("t = 1")
        assert ok and name == "t" and val == 1.0

    def test_t_float_is_slider(self):
        ok, name, val = is_slider_cell("t = 3.14")
        assert ok and name == "t" and pytest.approx(val) == 3.14

    def test_t_not_in_grid_vars(self):
        from pringle.grid import make_grid, GridConfig, grid_vars
        g = make_grid(GridConfig(n=8))
        assert "t" not in grid_vars(g)

    def test_t_slider_not_shadowed_by_grid(self):
        """z = x**2 + t with slider t=2 evaluates using the slider value."""
        from pringle.grid import make_grid, GridConfig
        g = make_grid(GridConfig(n=8))
        slider_result = run_cell("t = 2", {}, g)
        shared = slider_result.exports
        surf_result = run_cell("z = x**2 + t", shared, g)
        assert surf_result.error is None
        # z at x=0 should equal t=2
        assert surf_result.data is not None
        # If t were shadowed by grid_vars (old bug), min(z) ≈ 0; with t=2 it must be > 1
        assert float(surf_result.data.min()) > 1.0


# ---------------------------------------------------------------------------
# Full pipeline: run_cell
# ---------------------------------------------------------------------------

class TestRunCell:
    def test_surface_basic(self, grid):
        result = run_cell("z = sin(x) * cos(y)", {}, grid)
        assert result.render_type == "surface"
        assert result.data.shape == grid.x.shape
        assert result.error is None

    def test_surface_with_slider(self, grid):
        shared = {"a": 2.0}
        result = run_cell("z = a * sin(x) * cos(y)", shared, grid)
        assert result.render_type == "surface"
        assert result.error is None

    def test_curve_y(self, grid):
        # y = x**3 with 2D x meshgrid produces a 2D surface-like array.
        # This is correct: y = f(x) is an extruded surface in 3D space.
        # True 1D curves use xyz parametric or are produced by 1D x evaluations.
        result = run_cell("y = x**3", {}, grid)
        assert result.render_type in ("curve", "surface_y")
        assert result.error is None

    def test_func_def_auto_render(self, grid):
        result = run_cell("f(x, y) = x**2 + y**2", {}, grid)
        assert result.render_type == "surface"
        assert result.data.shape == grid.x.shape
        # f should be exported to shared namespace
        assert "f" in result.exports

    def test_func_def_curve(self, grid):
        result = run_cell("f(x) = x**2", {}, grid)
        # f(x) auto-renders as curve; 1D because we pass x1d (1D grid)
        assert result.render_type == "curve"
        assert result.error is None

    def test_comment_cell(self, grid):
        result = run_cell("# just a comment", {}, grid)
        assert result.is_comment
        assert result.render_type is None

    def test_slider_cell(self, grid):
        result = run_cell("a = 2.5", {}, grid)
        assert result.is_slider
        assert result.slider_name == "a"
        assert result.slider_value == 2.5
        assert result.exports == {"a": 2.5}

    def test_import_allowed(self, grid):
        result = run_cell("import os\npath_sep = os.sep", {}, grid)
        assert result.error is None
        assert "path_sep" in result.exports

    def test_np_alias_works_in_cell(self, grid):
        result = run_cell("arr = np.zeros(3)", {}, grid)
        assert result.error is None
        assert "arr" in result.exports

    def test_math_module_works_in_cell(self, grid):
        result = run_cell("val = math.floor(3.7)", {}, grid)
        assert result.error is None
        assert result.exports.get("val") == 3

    def test_undefined_var_free_names(self, grid):
        result = run_cell("z = q * sin(x)", {}, grid)
        # 'q' is a free name; NameError at exec time
        assert result.error is not None
        assert "q" in result.free_names

    def test_constraint_mask(self, grid):
        result = run_cell(
            "z = x**2 + y**2",
            {},
            grid,
            constraint_exprs=["x**2 + y**2 < 4"],
        )
        assert result.render_type == "surface"
        # Points outside radius 2 should be NaN
        r2 = grid.x**2 + grid.y**2
        outside = r2 > 4
        assert np.all(np.isnan(result.data[outside]))

    def test_piecewise(self, grid):
        shared = {}
        result = run_cell(
            "z = [lambda x, y: x**2, lambda x, y: -x**2]",
            shared,
            grid,
            condition_exprs=["x > 0", "x <= 0"],
        )
        assert result.render_type == "surface"
        assert result.data.shape == grid.x.shape
        assert result.error is None

    def test_piecewise_mismatch_warns(self, grid):
        result = run_cell(
            "z = [lambda x, y: x**2, lambda x, y: -x**2]",
            {},
            grid,
            condition_exprs=["x > 0"],  # 2 pieces, 1 condition
        )
        assert result.warning is not None

    def test_nan_passthrough(self, grid):
        result = run_cell("z = sqrt(x**2 + y**2 - 10)", {}, grid)
        # sqrt of negative → nan; should not error
        assert result.error is None
        assert result.render_type == "surface"

    def test_exports(self, grid):
        result = run_cell("g(x, y) = x + y", {}, grid)
        assert "g" in result.exports
        assert callable(result.exports["g"])

    def test_magic_not_exported(self, grid):
        result = run_cell("z = sin(x)", {}, grid)
        assert "z" not in result.exports


# ---------------------------------------------------------------------------
# Integration: evaluate → render offscreen
# ---------------------------------------------------------------------------

class TestEvalAndRender:
    def _render(self, source, shared=None, constraint_exprs=None):
        grid = make_grid(GridConfig(n=64))
        result = run_cell(source, shared or {}, grid, constraint_exprs=constraint_exprs)
        assert result.error is None, f"Eval error: {result.error}"

        canvas = OffscreenRenderCanvas(size=(600, 400))
        pr = PringleRenderer(canvas)

        if result.render_type == "surface":
            pr.add_object("cell", make_surface_mesh(result.x, result.y, result.data))
        elif result.render_type == "curve":
            pts = np.column_stack([grid.x1d, result.data, np.zeros(len(result.data))])
            pr.add_object("cell", make_line_mesh(pts))
        elif result.render_type in ("scatter", "scatter_2d"):
            pr.add_object("cell", make_scatter_mesh(result.data))

        pr.fit_camera()
        return pr.snapshot()

    def test_render_surface(self):
        img = self._render("z = sin(x) * cos(y)")
        assert img[..., :3].std() > 5
        iio.imwrite(FRAMES / "phase2_surface.png", img)

    def test_render_curve(self):
        # Use f(x) = x**2 which auto-renders as a proper 1D curve
        img = self._render("f(x) = x**2")
        assert img[..., :3].std() > 3
        iio.imwrite(FRAMES / "phase2_curve.png", img)

    def test_render_constrained_surface(self):
        img = self._render("z = x**2 + y**2", constraint_exprs=["x**2 + y**2 < 9"])
        assert img[..., :3].std() > 5
        iio.imwrite(FRAMES / "phase2_constrained.png", img)

    def test_render_slider_updates_surface(self):
        grid = make_grid(GridConfig(n=48))
        # Simulate slider a=2 → evaluate → render
        slider_result = run_cell("a = 2.0", {}, grid)
        shared = slider_result.exports.copy()
        surf_result = run_cell("z = a * sin(x) * cos(y)", shared, grid)
        assert surf_result.render_type == "surface"
        assert not np.allclose(surf_result.data, 0), "a=2 should scale the surface"
        iio.imwrite(FRAMES / "phase2_slider_a2.png", self._render("z = 2.0 * sin(x) * cos(y)"))


# ---------------------------------------------------------------------------
# Session trust gate
# ---------------------------------------------------------------------------

class TestSessionTrust:
    def _make_cell_list(self, grid):
        import sys
        from PyQt6.QtWidgets import QApplication
        QApplication.instance() or QApplication(sys.argv)
        from pringle.cell_list import CellListWidget
        return CellListWidget(on_cell_result=lambda *a: None, grid=grid)

    def test_trusted_by_default(self):
        """New CellListWidget starts in trusted mode."""
        grid = make_grid(GridConfig(n=8))
        cl = self._make_cell_list(grid)
        assert cl._session_trusted is True

    def test_untrusted_blocks_eval(self):
        """Setting _session_trusted=False prevents _rebuild_namespace from evaluating."""
        grid = make_grid(GridConfig(n=8))
        cl = self._make_cell_list(grid)
        cl._session_trusted = False
        cl.add_cell("a = 42")
        # Namespace should be empty — no evaluation happened
        assert "a" not in cl._shared_ns

    def test_trust_enables_eval(self):
        """After setting _session_trusted=True and calling _rebuild_namespace, cells evaluate."""
        grid = make_grid(GridConfig(n=8))
        cl = self._make_cell_list(grid)
        cl._session_trusted = False
        cl.add_cell("a = 42")
        assert "a" not in cl._shared_ns
        # Now trust and run
        cl._session_trusted = True
        cl._rebuild_namespace()
        assert cl._shared_ns.get("a") == 42
