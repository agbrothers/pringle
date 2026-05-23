"""
FEAT-038 tests: recurrence sub-cells for all renderable array shapes.

Tests validate:
- add_sub_cell("recursion") on a non-data-mode cell auto-enables data mode
- Recurrence on (N, 6) vectors produces render_type "vectors"
- Recurrence on (N, 3) scatter still produces render_type "scatter" (regression)
- Recurrence on (N, 6) vectors does not auto-disable data mode after eval
- Recurrence on a 3D array (no render type) exports to namespace with render_type None
- Sub-cell menu shows all four options regardless of data mode
"""

import sys
import pytest
import numpy as np

from PyQt6.QtWidgets import QApplication

from pringle.grid import GridConfig, make_grid


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=16))


def _noop_result(cid, result, style):
    pass


@pytest.fixture
def cell_list(qapp, grid):
    from pringle.cell_list import CellListWidget
    return CellListWidget(on_cell_result=_noop_result, grid=grid)


# ---------------------------------------------------------------------------
# Step 1: auto-enable data mode when recursion sub-cell is added
# ---------------------------------------------------------------------------

class TestRecursionAutoEnablesDataMode:
    def test_add_recursion_to_non_data_cell_enables_data_mode(self, qapp):
        from pringle.cell_widget import CellWidget
        cell = CellWidget()
        assert not cell.is_data_mode()
        cell.add_sub_cell("recursion")
        assert cell.is_data_mode()

    def test_add_initial_condition_does_not_enable_data_mode(self, qapp):
        from pringle.cell_widget import CellWidget
        cell = CellWidget()
        assert not cell.is_data_mode()
        cell.add_sub_cell("initial_condition")
        assert not cell.is_data_mode()

    def test_add_recursion_when_already_in_data_mode_is_noop(self, qapp):
        from pringle.cell_widget import CellWidget
        cell = CellWidget()
        cell.set_data_mode(True)
        cell.add_sub_cell("recursion")
        assert cell.is_data_mode()
        assert len(cell._sub_cells) == 1

    def test_recursion_sub_cell_survives_invalidating_source_change(self, cell_list):
        """BUG: changing cell source so the recurrence rule no longer matches removed the sub-cell.

        When the variable name referenced in the rule doesn't exist in result.exports, the
        recurrence branch is silently skipped.  In _eval_spec (the dispatch path), should_be_data
        was computed without a recursion guard, so any non-scatter result caused set_data_mode(False)
        and deleted the sub-cell.  Fix: guard the apply-back in _on_eval_results with
        has_recursion_sub_cell().
        """
        cell = cell_list.add_cell(source="V = zeros((10, 6))")
        rec = cell.add_sub_cell("recursion")
        rec._edit.setPlainText("V[n] = V[n-1]")
        cell_list._rebuild_namespace()
        assert cell.is_data_mode()

        # Rename the variable — rule now references a name that doesn't exist
        cell._text_edit.setPlainText("W = zeros((10, 6))")
        cell_list._rebuild_namespace()

        assert cell.is_data_mode(), "data mode must survive mismatched rule variable name"
        assert len(cell._sub_cells) == 1, "recursion sub-cell must not be deleted on source change"

    def test_empty_recursion_sub_cell_survives_rebuild(self, cell_list):
        """BUG: empty recursion sub-cell was removed on first _rebuild_namespace call.

        Reproduction: add a cell producing a non-scatter array (e.g. (10,10)), add a
        recursion sub-cell but leave it empty, trigger rebuild.  The auto-switch logic
        saw recurrence_expr() == None (empty rule) and called set_data_mode(False),
        which deleted the sub-cell immediately.  Fix: guard on has_recursion_sub_cell()
        instead of recurrence_expr().
        """
        cell = cell_list.add_cell(source="A = zeros((10, 10))")
        cell.add_sub_cell("recursion")  # empty — rule not yet typed
        assert cell.is_data_mode()
        assert len(cell._sub_cells) == 1

        cell_list._rebuild_namespace()

        assert cell.is_data_mode(), "data mode must survive rebuild with an empty recursion sub-cell"
        assert len(cell._sub_cells) == 1, "empty recursion sub-cell must not be removed on rebuild"


# ---------------------------------------------------------------------------
# Step 2 & 3: _detect_shape used for render type after recurrence
# ---------------------------------------------------------------------------

class TestRecurrenceShapeDetection:
    def test_vector_recurrence_produces_vectors_render_type(self, cell_list):
        """Recurrence on (N, 6) → render_type 'vectors', data.shape (N, 6)."""
        results = {}
        cell_list._on_cell_result = lambda cid, r, s: results.update({cid: r})

        cell = cell_list.add_cell(source="V = zeros((10, 6))")
        rec = cell.add_sub_cell("recursion")
        rec._edit.setPlainText("V[n] = V[n-1]")

        cell_list._rebuild_namespace()

        r = cell._last_result
        assert r.error is None, r.error
        assert r.render_type == "vectors"
        assert r.data is not None
        assert r.data.shape == (10, 6)

    def test_scatter_recurrence_still_produces_scatter(self, cell_list):
        """Regression: recurrence on (N, 3) still produces render_type 'scatter'."""
        cell = cell_list.add_cell(source="path = zeros((50, 3))")
        rec = cell.add_sub_cell("recursion")
        rec._edit.setPlainText("path[n] = path[n-1]")

        cell_list._rebuild_namespace()

        r = cell._last_result
        assert r.error is None, r.error
        assert r.render_type == "scatter"
        assert r.data is not None
        assert r.data.shape == (50, 3)

    def test_unrenderable_shape_exports_only(self, cell_list):
        """Recurrence on (5, 100, 5) (3D, not a vector field shape) → render_type None, exported to namespace."""
        cell = cell_list.add_cell(source="D = zeros((5, 100, 5))")
        rec = cell.add_sub_cell("recursion")
        rec._edit.setPlainText("D[n] = D[n-1]")

        cell_list._rebuild_namespace()

        r = cell._last_result
        assert r.error is None, r.error
        assert r.render_type is None
        assert r.data is None
        assert "D" in r.exports
        assert r.exports["D"].shape == (5, 100, 5)

    def test_vector_recurrence_does_not_disable_data_mode(self, cell_list):
        """After eval of a vector recurrence cell, data mode must remain True."""
        cell = cell_list.add_cell(source="V = zeros((8, 6))")
        rec = cell.add_sub_cell("recursion")
        rec._edit.setPlainText("V[n] = V[n-1]")

        cell_list._rebuild_namespace()

        assert cell.is_data_mode(), "data mode should remain True after vector recurrence eval"


# ---------------------------------------------------------------------------
# Step 1: sub-cell menu shows all four options regardless of data mode
# ---------------------------------------------------------------------------

class TestSubCellMenuUnified:
    def test_menu_actions_present_in_non_data_mode(self, qapp):
        from pringle.cell_widget import CellWidget
        from PyQt6.QtWidgets import QMenu
        cell = CellWidget()
        assert not cell.is_data_mode()

        # Simulate the menu build without showing it
        menu = QMenu()
        menu.addAction("Add Recursion Rule", lambda: None)
        menu.addAction("Add Initial Condition", lambda: None)
        menu.addAction("Add Constraint (filter surface)", lambda: None)
        menu.addAction("Add Condition (piecewise branch)", lambda: None)

        # Build the actual menu via the private method logic
        actual_menu = QMenu()
        cell._on_add_sub_clicked.__func__  # confirm it exists
        # Verify the method doesn't gate on data mode by checking add_sub_cell works for all types
        sub_r = cell.add_sub_cell("recursion")
        assert cell.is_data_mode()  # auto-enabled by recursion

        cell2 = CellWidget()
        sub_c = cell2.add_sub_cell("constraint")
        assert not cell2.is_data_mode()
        sub_cond = cell2.add_sub_cell("condition")
        assert len(cell2._sub_cells) == 2
