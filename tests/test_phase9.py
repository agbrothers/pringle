"""
Phase 9 tests: recurrence cells and data-namespace evaluation.

Tests validate:
- parse_recurrence / execute_recurrence correctness
- Shared namespace accumulates across run_cell calls
- import statement is blocked at runtime (no __builtins__)
- np alias is available via is_data_cell=True
- run_cell with is_data_cell=True skips AST safety check
- Recurrence sub-cells can reference functions defined in upstream cells
"""

import sys
import pytest
import numpy as np

from PyQt6.QtWidgets import QApplication

from pringle.recurrence import parse_recurrence, execute_recurrence
from pringle.evaluator import run_cell
from pringle.namespace import build_data_namespace
from pringle.grid import make_grid, GridConfig
from pringle.dag import cell_uses


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=32))


# ---------------------------------------------------------------------------
# parse_recurrence / execute_recurrence
# ---------------------------------------------------------------------------

class TestRecurrence:
    def test_parse_valid(self):
        ok, name, rhs = parse_recurrence("path[n] = path[n-1] * 0.5")
        assert ok is True
        assert name == "path"
        assert rhs == "path[n-1] * 0.5"

    def test_parse_invalid(self):
        ok, name, rhs = parse_recurrence("path = zeros((10, 2))")
        assert ok is False

    def test_parse_with_spaces(self):
        ok, name, rhs = parse_recurrence("  arr [ n ] = arr[n-1] + 1  ")
        assert ok is True
        assert name == "arr"

    def test_execute_geometric_decay(self):
        arr = np.zeros(10, dtype=np.float64)
        arr[0] = 1.0
        result, warn = execute_recurrence(
            "arr", arr,
            initial_exprs=[],
            rule_expr="arr[n] = arr[n-1] * 0.5",
            namespace={},
        )
        assert warn is None
        assert result[0] == pytest.approx(1.0)
        assert result[1] == pytest.approx(0.5)
        assert result[9] == pytest.approx(0.5**9)

    def test_execute_with_initial_condition(self):
        arr = np.zeros(5, dtype=np.float64)
        result, warn = execute_recurrence(
            "arr", arr,
            initial_exprs=["arr[0] = 3.0"],
            rule_expr="arr[n] = arr[n-1] + 1",
            namespace={"array": np.array, "zeros": np.zeros},
        )
        assert warn is None
        assert result[0] == pytest.approx(3.0)
        assert result[4] == pytest.approx(7.0)

    def test_execute_2d_path(self):
        path = np.zeros((5, 2), dtype=np.float64)
        path[0] = [1.0, 0.0]
        result, warn = execute_recurrence(
            "path", path,
            initial_exprs=[],
            rule_expr="path[n] = path[n-1] * 0.8",
            namespace={},
        )
        assert warn is None
        assert np.allclose(result[1], [0.8, 0.0])
        assert np.allclose(result[4], [0.8**4, 0.0])

    def test_execute_nan_detected(self):
        arr = np.zeros(5, dtype=np.float64)
        arr[0] = 1.0
        result, warn = execute_recurrence(
            "arr", arr,
            initial_exprs=[],
            rule_expr="arr[n] = arr[n-1] / 0",
            namespace={},
        )
        assert warn is not None
        assert "NaN" in warn or "Inf" in warn

    def test_invalid_rule_returns_warning(self):
        arr = np.zeros(5, dtype=np.float64)
        _, warn = execute_recurrence(
            "arr", arr,
            initial_exprs=[],
            rule_expr="not a valid rule",
            namespace={},
        )
        assert warn is not None


# ---------------------------------------------------------------------------
# Data namespace
# ---------------------------------------------------------------------------

class TestDataNamespace:
    def test_np_in_data_namespace(self):
        ns = build_data_namespace()
        assert "np" in ns
        assert ns["np"] is np

    def test_array_in_data_namespace(self):
        ns = build_data_namespace()
        assert "array" in ns

    def test_random_in_data_namespace(self):
        ns = build_data_namespace()
        assert "random" in ns


# ---------------------------------------------------------------------------
# run_cell with is_data_cell=True
# ---------------------------------------------------------------------------

class TestDataCellEval:
    def test_np_available(self, grid):
        result = run_cell("d = np.zeros((5, 3))", {}, grid, is_data_cell=True)
        assert result.error is None
        assert "d" in result.exports
        assert result.exports["d"].shape == (5, 3)

    def test_random_available(self, grid):
        result = run_cell("d = random.randn(10, 3)", {}, grid, is_data_cell=True)
        assert result.error is None
        assert result.exports["d"].shape == (10, 3)

    def test_import_blocked_at_runtime(self, grid):
        result = run_cell("import os", {}, grid, is_data_cell=True)
        assert result.error is not None

    def test_scatter_detected(self, grid):
        result = run_cell("points = random.randn(20, 3)", {}, grid, is_data_cell=True)
        assert result.render_type == "scatter"

    def test_exports_propagate(self, grid):
        result1 = run_cell("scale = 5.0", {}, grid, is_data_cell=True)
        ns = result1.exports
        result2 = run_cell("d = zeros((10,)) + scale", ns, grid, is_data_cell=True)
        assert result2.error is None
        assert np.allclose(result2.exports["d"], 5.0)


# ---------------------------------------------------------------------------
# Recurrence sub-cell dependency tracking via DAG
# ---------------------------------------------------------------------------

class _FakeSubCell:
    """Minimal sub-cell stub for DAG dependency tests."""
    def __init__(self, sub_type, source):
        self._sub_type = sub_type
        self._source = source

    def sub_type(self):
        return self._sub_type

    def source(self):
        return self._source


class _FakeCell:
    """Minimal cell stub for DAG dependency tests."""
    def __init__(self, cell_id, source, sub_cells=None):
        self.cell_id = cell_id
        self._source = source
        self._sub_cells = sub_cells or []

    def source(self):
        return self._source


class TestRecurrenceDAGDeps:
    """Verify that cell_uses() includes external deps from recurrence sub-cells."""

    def test_recursion_rule_external_deps_tracked(self):
        # path cell source has no reference to dL or dt — only zeros and k
        # but the recursion sub-cell references dL and dt
        sub = _FakeSubCell("recursion", "path[n] = path[n-1] + dt * dL(path[n-1])")
        cell = _FakeCell("path-cell", "path = zeros((k, 3))", sub_cells=[sub])
        uses = cell_uses(cell)
        assert "dL" in uses, f"expected 'dL' in cell_uses, got: {uses}"
        assert "dt" in uses, f"expected 'dt' in cell_uses, got: {uses}"

    def test_recurrence_loop_var_n_not_in_deps(self):
        sub = _FakeSubCell("recursion", "path[n] = path[n-1] * 0.9")
        cell = _FakeCell("path-cell", "path = zeros((10, 2))", sub_cells=[sub])
        uses = cell_uses(cell)
        assert "n" not in uses, f"'n' (loop var) should not be a tracked dep, got: {uses}"

    def test_initial_condition_external_deps_not_flagged(self):
        # array is always-defined so it should not appear; path is self-defined so
        # cell_uses may include it but build_dag's self-edge guard prevents a cycle
        sub = _FakeSubCell("initial_condition", "path[0] = array([1.0, 0.0])")
        cell = _FakeCell("path-cell", "path = zeros((10, 2))", sub_cells=[sub])
        uses = cell_uses(cell)
        assert "array" not in uses  # whitelist — always available

    def test_cross_cell_recurrence_evaluates_correctly(self, grid, qapp):
        # Simulate the Lorenz pattern: upstream cell defines f(pos), recurrence uses it
        from pringle.cell_list import CellListWidget
        results = {}
        cl = CellListWidget(
            on_cell_result=lambda cid, r, s: results.update({cid: r}),
            grid=grid, parent=None,
        )
        # Upstream cell: define a step function
        step_cell = cl.add_cell(source="f(pos) = pos * 0.5")
        # Recurrence cell: path[n] = f(path[n-1]), initial path[0] = array([4.0, 0.0])
        path_cell = cl.add_cell(source="path = zeros((5, 2))")
        ic = path_cell.add_sub_cell(sub_type="initial_condition")
        ic._edit.setPlainText("path[0] = array([4.0, 0.0])")
        rec = path_cell.add_sub_cell(sub_type="recursion")
        rec._edit.setPlainText("path[n] = f(path[n-1])")

        cl._rebuild_namespace()

        r = path_cell._last_result
        assert r.error is None, r.error
        assert r.warning is None or "dL" not in str(r.warning)
        p = r.exports.get("path")
        assert p is not None
        assert np.allclose(p[0], [4.0, 0.0]), p[0]
        assert np.allclose(p[1], [2.0, 0.0]), p[1]
        assert np.allclose(p[2], [1.0, 0.0]), p[2]
