"""
Phase 9 tests: data panel and recurrence cells.

Tests validate:
- DataCellWidget structure, signals, and sub-cells
- DataPanelWidget add/remove/run
- Shared namespace accumulates across data cells
- import statement is blocked at runtime (no __builtins__)
- np alias is available in data cells (np.random.randn)
- run_cell with is_data_cell=True skips AST safety check
- Recurrence: parse_recurrence, execute_recurrence
- Recurrence integration: path builds a geometric sequence
- DataPanelWidget namespace_changed signal
"""

import sys
import pytest
import numpy as np

from PyQt6.QtWidgets import QApplication

from pringle.data_cell_widget import DataCellWidget
from pringle.data_panel import DataPanelWidget
from pringle.recurrence import parse_recurrence, execute_recurrence
from pringle.evaluator import run_cell
from pringle.namespace import build_data_namespace
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=32))


# ---------------------------------------------------------------------------
# DataCellWidget
# ---------------------------------------------------------------------------

class TestDataCellWidget:
    def test_creates(self, qapp):
        cell = DataCellWidget()
        assert cell.cell_id != ""
        assert cell.source() == ""

    def test_set_source(self, qapp):
        cell = DataCellWidget()
        cell.set_source("d = zeros((10, 3))")
        assert cell.source() == "d = zeros((10, 3))"

    def test_run_requested_signal(self, qapp):
        cell = DataCellWidget()
        received = []
        cell.run_requested.connect(received.append)
        cell._run_btn.click()
        assert cell.cell_id in received

    def test_delete_requested_signal(self, qapp):
        cell = DataCellWidget()
        received = []
        cell.delete_requested.connect(received.append)
        cell._delete_btn.click()
        assert cell.cell_id in received

    def test_edit_marks_stale(self, qapp):
        cell = DataCellWidget()
        cell.set_status("ok")
        cell._text_edit.setPlainText("new source")
        assert "stale" in cell._status_dot.styleSheet().lower() or \
               "cc7700" in cell._status_dot.styleSheet().lower()

    def test_set_status_ok(self, qapp):
        cell = DataCellWidget()
        cell.set_status("ok")
        assert "2a8a2a" in cell._status_dot.styleSheet()

    def test_set_status_error_shows_message(self, qapp):
        cell = DataCellWidget()
        cell.set_status("error", "NameError: x is not defined")
        assert not cell._msg_label.isHidden()

    def test_add_initial_condition_sub_cell(self, qapp):
        cell = DataCellWidget()
        sub = cell.add_sub_cell("initial_condition")
        assert sub.sub_type() == "initial_condition"
        assert len(cell._sub_cells) == 1

    def test_add_recursion_sub_cell(self, qapp):
        cell = DataCellWidget()
        sub = cell.add_sub_cell("recursion")
        assert sub.sub_type() == "recursion"

    def test_initial_condition_exprs(self, qapp):
        cell = DataCellWidget()
        sub = cell.add_sub_cell("initial_condition")
        sub._edit.setText("path[0] = array([1.0, 0.0])")
        assert cell.initial_condition_exprs() == ["path[0] = array([1.0, 0.0])"]

    def test_recurrence_expr(self, qapp):
        cell = DataCellWidget()
        sub = cell.add_sub_cell("recursion")
        sub._edit.setText("path[n] = path[n-1] * 0.9")
        assert cell.recurrence_expr() == "path[n] = path[n-1] * 0.9"

    def test_recurrence_expr_none_when_blank(self, qapp):
        cell = DataCellWidget()
        cell.add_sub_cell("recursion")  # blank
        assert cell.recurrence_expr() is None


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
        # import fails at runtime because __builtins__ is disabled
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
# DataPanelWidget
# ---------------------------------------------------------------------------

class TestDataPanelWidget:
    def test_creates_empty(self, qapp, grid):
        panel = DataPanelWidget(grid=grid)
        assert len(panel._cells) == 0

    def test_add_cell(self, qapp, grid):
        panel = DataPanelWidget(grid=grid)
        cell = panel.add_cell("d = zeros((5, 3))")
        assert len(panel._cells) == 1
        assert cell.source() == "d = zeros((5, 3))"

    def test_remove_cell(self, qapp, grid):
        panel = DataPanelWidget(grid=grid)
        cell = panel.add_cell("d = zeros((5,))")
        panel.remove_cell(cell.cell_id)
        assert len(panel._cells) == 0

    def test_run_cell_updates_namespace(self, qapp, grid):
        panel = DataPanelWidget(grid=grid)
        cell = panel.add_cell("scale = 7.0")
        panel._run_cell(cell)
        assert "scale" in panel._namespace
        assert panel._namespace["scale"] == pytest.approx(7.0)

    def test_run_all_accumulates(self, qapp, grid):
        panel = DataPanelWidget(grid=grid)
        panel.add_cell("a_val = 3.0")
        panel.add_cell("b_val = a_val * 2")
        panel.run_all()
        assert panel._namespace.get("a_val") == pytest.approx(3.0)
        assert panel._namespace.get("b_val") == pytest.approx(6.0)

    def test_namespace_changed_signal(self, qapp, grid):
        received = []
        panel = DataPanelWidget(grid=grid)
        panel.namespace_changed.connect(lambda: received.append(True))
        cell = panel.add_cell("v = 1.0")
        panel._run_cell(cell)
        assert len(received) > 0

    def test_error_cell_sets_error_status(self, qapp, grid):
        panel = DataPanelWidget(grid=grid)
        cell = panel.add_cell("z = undefined_variable_xyz")
        panel._run_cell(cell)
        # Status dot should reflect error
        assert "cc2222" in cell._status_dot.styleSheet()

    def test_get_namespace(self, qapp, grid):
        panel = DataPanelWidget(grid=grid)
        cell = panel.add_cell("alpha = 42.0")
        panel._run_cell(cell)
        ns = panel.get_namespace()
        assert ns.get("alpha") == pytest.approx(42.0)
        # Should be a copy, not the live dict
        ns["alpha"] = 0.0
        assert panel._namespace.get("alpha") == pytest.approx(42.0)

    def test_recurrence_integration(self, qapp, grid):
        """Geometric decay recurrence produces correct path."""
        panel = DataPanelWidget(grid=grid)
        cell = panel.add_cell("path = zeros(8)")
        ic = cell.add_sub_cell("initial_condition")
        ic._edit.setText("path[0] = 1.0")
        rule = cell.add_sub_cell("recursion")
        rule._edit.setText("path[n] = path[n-1] * 0.5")

        panel._run_cell(cell)

        assert "path" in panel._namespace
        path = panel._namespace["path"]
        assert path[0] == pytest.approx(1.0)
        assert path[4] == pytest.approx(0.5**4, abs=1e-6)

    def test_on_cell_result_callback(self, qapp, grid):
        """DataPanelWidget calls on_cell_result for renderable outputs."""
        results = []
        panel = DataPanelWidget(
            on_cell_result=lambda cid, r, s: results.append((cid, r)),
            grid=grid,
        )
        cell = panel.add_cell("points = random.randn(10, 3)")
        panel._run_cell(cell)
        assert len(results) > 0
        _, r = results[0]
        assert r.render_type == "scatter"
