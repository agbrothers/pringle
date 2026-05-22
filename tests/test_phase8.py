"""
Phase 8 tests: constraint and piecewise sub-cells.

Tests validate:
- SubCell widget structure and signals
- CellWidget.add_sub_cell / remove_sub_cell
- constraint_exprs() and condition_exprs() return correct lists
- Backend: apply_constraints masks surface with NaN outside filter region
- Backend: piecewise evaluation via condition sub-cells
- Integration: cell with constraint sub-cell renders masked surface
- Integration: piecewise cell renders two-piece surface
"""

import sys
import pytest
import numpy as np

from PyQt6.QtWidgets import QApplication

from pringle.cell_widget import CellWidget, SubCell
from pringle.cell_list import CellListWidget
from pringle.evaluator import apply_constraints, run_cell, CellResult
from pringle.grid import make_grid, GridConfig
from pringle.style import CellStyle


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=32))


# ---------------------------------------------------------------------------
# SubCell
# ---------------------------------------------------------------------------

class TestSubCell:
    def test_creates_constraint(self, qapp):
        s = SubCell(sub_type="constraint")
        assert s.sub_type() == "constraint"
        assert s.source() == ""

    def test_creates_condition(self, qapp):
        s = SubCell(sub_type="condition")
        assert s.sub_type() == "condition"

    def test_source_reflects_edit(self, qapp):
        s = SubCell()
        s._edit.setPlainText("x**2 + y**2 < 4")
        assert s.source() == "x**2 + y**2 < 4"

    def test_content_changed_signal(self, qapp):
        s = SubCell()
        received = []
        s.content_changed.connect(lambda: received.append(True))
        s._edit.setPlainText("x > 0")
        assert len(received) > 0

    def test_delete_requested_signal(self, qapp):
        s = SubCell()
        received = []
        s.delete_requested.connect(lambda: received.append(True))
        # Click the delete button
        from PyQt6.QtWidgets import QPushButton
        for i in range(s.layout().count()):
            w = s.layout().itemAt(i).widget()
            if isinstance(w, QPushButton) and w.text() == "✕":
                w.click()
                break
        assert len(received) > 0


# ---------------------------------------------------------------------------
# CellWidget sub-cell management
# ---------------------------------------------------------------------------

class TestCellWidgetSubCells:
    def test_starts_with_no_sub_cells(self, qapp):
        cell = CellWidget()
        assert len(cell._sub_cells) == 0
        assert cell.constraint_exprs() == []
        assert cell.condition_exprs() == []

    def test_add_constraint_sub_cell(self, qapp):
        cell = CellWidget()
        sub = cell.add_sub_cell("constraint")
        assert isinstance(sub, SubCell)
        assert len(cell._sub_cells) == 1
        assert sub.sub_type() == "constraint"

    def test_add_condition_sub_cell(self, qapp):
        cell = CellWidget()
        sub = cell.add_sub_cell("condition")
        assert sub.sub_type() == "condition"

    def test_constraint_exprs_empty_when_blank(self, qapp):
        cell = CellWidget()
        cell.add_sub_cell("constraint")  # blank source
        assert cell.constraint_exprs() == []

    def test_constraint_exprs_returns_filled(self, qapp):
        cell = CellWidget()
        sub = cell.add_sub_cell("constraint")
        sub._edit.setPlainText("x**2 + y**2 < 4")
        assert cell.constraint_exprs() == ["x**2 + y**2 < 4"]

    def test_condition_exprs_separate_from_constraints(self, qapp):
        cell = CellWidget()
        c_sub = cell.add_sub_cell("constraint")
        d_sub = cell.add_sub_cell("condition")
        c_sub._edit.setPlainText("x > 0")
        d_sub._edit.setPlainText("y > 0")
        assert cell.constraint_exprs() == ["x > 0"]
        assert cell.condition_exprs() == ["y > 0"]

    def test_remove_sub_cell(self, qapp):
        cell = CellWidget()
        sub = cell.add_sub_cell("constraint")
        cell._remove_sub_cell(sub)
        assert len(cell._sub_cells) == 0
        assert cell.constraint_exprs() == []

    def test_multiple_constraints(self, qapp):
        cell = CellWidget()
        s1 = cell.add_sub_cell("constraint")
        s2 = cell.add_sub_cell("constraint")
        s1._edit.setPlainText("x > 0")
        s2._edit.setPlainText("y > 0")
        exprs = cell.constraint_exprs()
        assert "x > 0" in exprs
        assert "y > 0" in exprs
        assert len(exprs) == 2

    def test_sub_cell_change_triggers_debounce(self, qapp):
        cell = CellWidget()
        received = []
        cell.content_changed.connect(received.append)
        sub = cell.add_sub_cell("constraint")
        sub._edit.setPlainText("x > 0")
        # Fire the debounce timer immediately
        cell._debounce.stop()
        cell._emit_changed()
        assert cell.cell_id in received


# ---------------------------------------------------------------------------
# set_data_mode silent sub-cell removal (BUG-034)
# ---------------------------------------------------------------------------

class TestSetDataMode:
    def test_force_false_silently_removes_incompatible_sub_cells(self, qapp):
        # Constraint sub-cells are incompatible with data mode; force=False must
        # remove them without spawning a QMessageBox.
        cell = CellWidget()
        cell.add_sub_cell("constraint")
        assert len(cell._sub_cells) == 1
        cell.set_data_mode(True)  # force=False by default
        assert len(cell._sub_cells) == 0
        assert cell.is_data_mode()

    def test_force_false_removes_recursion_when_leaving_data_mode(self, qapp):
        cell = CellWidget()
        cell._data_mode = True  # put cell in data mode without going through set_data_mode
        cell.add_sub_cell("recursion")
        assert len(cell._sub_cells) == 1
        cell.set_data_mode(False)  # force=False by default
        assert len(cell._sub_cells) == 0
        assert not cell.is_data_mode()

    def test_compatible_sub_cells_are_preserved(self, qapp):
        # Recursion sub-cells are compatible with data mode; they must survive the switch.
        cell = CellWidget()
        cell._data_mode = True
        cell.add_sub_cell("recursion")
        cell.set_data_mode(True)  # no-op (already in data mode), sub-cell untouched
        assert len(cell._sub_cells) == 1

    def test_no_change_when_already_in_target_mode(self, qapp):
        cell = CellWidget()
        cell.add_sub_cell("constraint")
        cell.set_data_mode(False)  # already False — must be a no-op
        assert len(cell._sub_cells) == 1


# ---------------------------------------------------------------------------
# Sub-cell signal wiring in data mode (BUG-033)
# ---------------------------------------------------------------------------

class TestSubCellDataModeSignals:
    def test_sub_cell_in_data_mode_does_not_start_debounce(self, qapp):
        cell = CellWidget()
        cell.set_data_mode(True)
        sub = cell.add_sub_cell("recursion")
        cell._debounce.stop()
        sub._edit.setPlainText("x[n+1] = x[n] + 1")
        assert not cell._debounce.isActive()

    def test_sub_cell_in_expression_mode_starts_debounce(self, qapp):
        cell = CellWidget()
        sub = cell.add_sub_cell("constraint")
        cell._debounce.stop()
        sub._edit.setPlainText("x > 0")
        assert cell._debounce.isActive()

    def test_switch_to_data_mode_rewires_existing_sub_cells(self, qapp):
        cell = CellWidget()
        sub = cell.add_sub_cell("recursion")  # connected to _on_text_changed
        cell.set_data_mode(True)              # should rewire to _mark_data_stale
        cell._debounce.stop()
        sub._edit.setPlainText("x[n+1] = x[n] + 1")
        assert not cell._debounce.isActive()

    def test_switch_to_expression_mode_rewires_sub_cells_back(self, qapp):
        # A constraint sub-cell added while in data mode (connected to _mark_data_stale)
        # should be rewired to _on_text_changed when the cell returns to expression mode.
        # Constraint sub-cells are compatible with expression mode so they survive the switch.
        cell = CellWidget()
        cell.set_data_mode(True)
        sub = cell.add_sub_cell("constraint")  # data mode → _mark_data_stale
        cell.set_data_mode(False)              # constraint survives; should rewire to _on_text_changed
        cell._debounce.stop()
        sub._edit.setPlainText("x > 0")
        assert cell._debounce.isActive()


# ---------------------------------------------------------------------------
# Backend: apply_constraints
# ---------------------------------------------------------------------------

class TestApplyConstraints:
    def test_no_constraints_passthrough(self, grid):
        z = np.ones(grid.x.shape, dtype=np.float32)
        result = apply_constraints(z, [], {"x": grid.x, "y": grid.y})
        assert np.allclose(result, z)

    def test_circular_constraint(self, grid):
        z = np.ones(grid.x.shape, dtype=np.float32)
        ns = {"x": grid.x, "y": grid.y}
        result = apply_constraints(z, ["x**2 + y**2 < 4"], ns)
        outside = (grid.x**2 + grid.y**2) >= 4
        assert np.all(np.isnan(result[outside]))
        inside = (grid.x**2 + grid.y**2) < 4
        assert np.all(result[inside] == pytest.approx(1.0))

    def test_two_constraints_and_logic(self, grid):
        z = np.ones(grid.x.shape, dtype=np.float32)
        ns = {"x": grid.x, "y": grid.y}
        result = apply_constraints(z, ["x > 0", "y > 0"], ns)
        # Only Q1 (x>0, y>0) should be non-NaN
        excluded = (grid.x <= 0) | (grid.y <= 0)
        assert np.all(np.isnan(result[excluded]))

    def test_bad_constraint_expression_ignored(self, grid):
        z = np.ones(grid.x.shape, dtype=np.float32)
        ns = {"x": grid.x, "y": grid.y}
        # Should not raise; bad expr is skipped
        result = apply_constraints(z, ["not valid python !!!", "x > 0"], ns)
        # Only the valid constraint is applied
        assert not np.all(np.isnan(result))


# ---------------------------------------------------------------------------
# Backend: piecewise via run_cell
# ---------------------------------------------------------------------------

class TestPiecewise:
    def test_piecewise_two_pieces(self, grid):
        source = "z = [lambda x, y: x**2, lambda x, y: -x**2]"
        conditions = ["x > 0", "x <= 0"]
        result = run_cell(source, {}, grid, condition_exprs=conditions)
        assert result.render_type == "surface"
        assert result.data is not None
        # Right half (x>0) should be x**2 ≥ 0
        right = grid.x > 0
        assert np.all(result.data[right] >= 0)
        # Left half (x<=0) should be -x**2 ≤ 0
        left = grid.x <= 0
        assert np.all(result.data[left] <= 0)

    def test_piecewise_count_mismatch_warns(self, grid):
        source = "z = [lambda x, y: x**2, lambda x, y: -x**2]"
        result = run_cell(source, {}, grid, condition_exprs=["x > 0"])  # 2 pieces, 1 cond
        assert result.warning is not None
        assert "Piecewise" in result.warning

    def test_piecewise_no_conditions_warns(self, grid):
        source = "z = [lambda x, y: x**2, lambda x, y: -x**2]"
        result = run_cell(source, {}, grid)
        assert result.warning is not None


# ---------------------------------------------------------------------------
# Integration: CellListWidget with sub-cells
# ---------------------------------------------------------------------------

class TestCellListSubCells:
    def test_constraint_filters_surface(self, qapp, grid):
        """Surface cell with circular constraint produces NaN outside disc."""
        surface_data = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: surface_data.append(r.data)
            if r.render_type == "surface" else None,
            grid=grid,
        )
        cell = clist.add_cell("z = x**2 + y**2")
        sub = cell.add_sub_cell("constraint")
        sub._edit.setPlainText("x**2 + y**2 < 4")

        # Trigger re-evaluation
        cell._debounce.stop()
        cell._emit_changed()

        assert len(surface_data) > 0
        data = surface_data[-1]
        outside = (grid.x**2 + grid.y**2) >= 4
        assert np.any(np.isnan(data[outside])), "Outside disc should be NaN"

    def test_piecewise_integration(self, qapp, grid):
        """Piecewise list with condition sub-cell renders two-piece surface."""
        surface_data = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: surface_data.append(r.data)
            if r.render_type == "surface" else None,
            grid=grid,
        )
        cell = clist.add_cell("z = [lambda x, y: x**2, lambda x, y: -x**2]")
        d1 = cell.add_sub_cell("condition")
        d2 = cell.add_sub_cell("condition")
        d1._edit.setPlainText("x > 0")
        d2._edit.setPlainText("x <= 0")

        cell._debounce.stop()
        cell._emit_changed()

        assert len(surface_data) > 0
        data = surface_data[-1]
        right = grid.x > 0
        left = grid.x <= 0
        assert np.all(data[right] >= -0.01), "Right half should be x**2 ≥ 0"
        assert np.all(data[left] <= 0.01), "Left half should be -x**2 ≤ 0"

    def test_constraint_removal_restores_surface(self, qapp, grid):
        """Removing constraint sub-cell restores full surface."""
        surface_data = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: surface_data.append(r.data)
            if r.render_type == "surface" else None,
            grid=grid,
        )
        cell = clist.add_cell("z = ones((32, 32))")
        sub = cell.add_sub_cell("constraint")
        sub._edit.setPlainText("x > 0")

        cell._debounce.stop()
        cell._emit_changed()
        nan_count_with = np.sum(np.isnan(surface_data[-1]))

        cell._remove_sub_cell(sub)
        cell._debounce.stop()
        cell._emit_changed()
        nan_count_without = np.sum(np.isnan(surface_data[-1]))

        assert nan_count_without < nan_count_with, "Removing constraint should restore NaN-free surface"
