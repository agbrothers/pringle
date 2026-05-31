"""
PERF-016 — _rebuild_namespace() skips data-mode cells whose source and
upstream dependencies haven't changed since the last rebuild.

Tests verify:
  - data-mode cells are skipped (eval_count stays 0) when nothing upstream changed
  - data-mode cells re-evaluate when an upstream slider changes
  - data-mode cells re-evaluate when their own source changes
  - data-mode cells re-evaluate when a sub-cell (recurrence rule) changes
  - the → button (_on_run_requested) always forces re-evaluation via rng_seed increment
  - non-data-mode cells always evaluate (they are fast, no skip gate)
  - skipped cells still export their values to the shared namespace
"""

import sys
import numpy as np
import pytest

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def _noop_result(cid, result, style):
    pass


@pytest.fixture
def cl(qapp):
    from pringle.cell_list import CellListWidget
    from pringle.grid import GridConfig, make_grid
    grid = make_grid(GridConfig(n=16))
    return CellListWidget(on_cell_result=_noop_result, grid=grid)


# ---------------------------------------------------------------------------
# Helper: count _eval_cell calls for a specific cell during one rebuild
# ---------------------------------------------------------------------------

def _eval_count(cl, cell) -> int:
    original = cl._eval_cell
    calls = [0]

    def patched(c, shared):
        if c is cell:
            calls[0] += 1
        return original(c, shared)

    cl._eval_cell = patched
    cl._rebuild_namespace()
    cl._eval_cell = original
    return calls[0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDataModeSkip:
    def test_data_mode_cell_skipped_when_unchanged(self, cl):
        """After initial eval, data-mode cell must not be re-evaluated if
        nothing upstream changed."""
        cell = cl.add_cell(source="pts = zeros((20, 3))")
        assert cell.is_data_mode()
        count = _eval_count(cl, cell)
        assert count == 0, f"Expected 0 evaluations for unchanged data cell, got {count}"

    def test_data_mode_cell_reevals_when_slider_changes(self, cl):
        """Data-mode cell must re-evaluate when an upstream slider value changes."""
        from pringle.slider_widget import SliderWidget

        cl.add_cell(source="n = 10")  # morphs to SliderWidget
        cell = cl.add_cell(source="pts = zeros((int(n), 3))")
        assert cell.is_data_mode()

        slider = next(c for c in cl._cells if isinstance(c, SliderWidget) and c.name == "n")
        # Pretend the slider had a different previous value so it triggers changed_ids
        cl._shared_ns[slider.name] = 5.0
        count = _eval_count(cl, cell)
        assert count == 1, f"Expected 1 evaluation after slider change, got {count}"

    def test_data_mode_cell_reevals_when_source_changes(self, cl):
        """Data-mode cell must re-evaluate when its own source text changes."""
        cell = cl.add_cell(source="pts = zeros((20, 3))")
        assert cell.is_data_mode()
        cell.set_source("pts = zeros((30, 3))")
        count = _eval_count(cl, cell)
        assert count == 1, f"Expected 1 evaluation after source change, got {count}"

    def test_data_mode_cell_reevals_when_recurrence_rule_changes(self, cl):
        """Data-mode cell must re-evaluate when its recurrence sub-cell changes."""
        cell = cl.add_cell(source="path = zeros((5, 2))")
        rec = cell.add_sub_cell(sub_type="recursion")
        rec._edit.setPlainText("path[n] = path[n-1] + 1")
        cl._rebuild_namespace()  # establish baseline hash with this rule

        rec._edit.setPlainText("path[n] = path[n-1] + 2")
        count = _eval_count(cl, cell)
        assert count == 1, f"Expected 1 evaluation after recurrence rule change, got {count}"

    def test_run_button_forces_reeval(self, cl):
        """→ button (_on_run_requested) must always trigger re-evaluation
        even when source and ancestors are unchanged (rng_seed increments)."""
        cell = cl.add_cell(source="pts = random.uniform(0, 1, (20, 3))")
        assert cell.is_data_mode()
        seed_before = cell._rng_seed

        original = cl._eval_cell
        calls = [0]

        def patched(c, shared):
            if c is cell:
                calls[0] += 1
            return original(c, shared)

        cl._eval_cell = patched
        cl._on_run_requested(cell.cell_id)
        cl._eval_cell = original

        assert cell._rng_seed == seed_before + 1
        assert calls[0] == 1, f"Expected 1 evaluation after → press, got {calls[0]}"

    def test_non_data_mode_cell_always_evaluates(self, cl):
        """Non-data-mode (surface/function) cells must always be evaluated;
        they are fast and not subject to the skip gate."""
        cell = cl.add_cell(source="z = x**2 + y**2")
        assert not cell.is_data_mode()
        count = _eval_count(cl, cell)
        assert count == 1, f"Expected 1 evaluation for surface cell, got {count}"

    def test_skip_reuses_last_result_exports(self, cl):
        """When a data-mode cell is skipped, its exports must still appear in shared."""
        cl.add_cell(source="pts = zeros((20, 3))")
        cl._rebuild_namespace()  # first pass: evaluate all, establish hashes
        assert "pts" in cl._shared_ns

        cl._rebuild_namespace()  # second pass: data cell should be skipped
        assert "pts" in cl._shared_ns, "Exported 'pts' missing from shared after skip"

    def test_grid_resolution_change_invalidates_data_mode_cells(self, cl):
        """Changing grid resolution must invalidate data-mode cells that use x/y
        magic variables (e.g. `grid = array([x, y]).reshape(2, -1)`).
        Regression for the PERF-016 skip gate ignoring external grid changes."""
        from pringle.grid import GridConfig, make_grid

        # Cell that exports a grid-derived array via x/y magic variables
        grid_cell = cl.add_cell(source="g = array([x, y]).reshape(2, -1)")
        assert grid_cell.is_data_mode()  # (2, N) array → data mode

        # Capture the shape after the initial eval
        first_shape = cl._shared_ns.get("g").shape if "g" in cl._shared_ns else None
        assert first_shape is not None

        # Change grid resolution — must invalidate the skip gate
        new_grid = make_grid(GridConfig(n=32))
        cl._grid = new_grid

        count = _eval_count(cl, grid_cell)
        assert count == 1, "Grid resolution change must force data-mode cell to re-evaluate"

        new_shape = cl._shared_ns.get("g").shape
        assert new_shape != first_shape, "Exported array shape must update after grid change"

    def test_downstream_data_cell_reevals_when_upstream_changes(self, cl):
        """If a data-mode cell IS re-evaluated, downstream data-mode cells
        that read its exports must also re-evaluate."""
        a = cl.add_cell(source="pts = zeros((5, 3))")
        b = cl.add_cell(source="pts2 = pts + 1")
        cl._rebuild_namespace()  # establish baseline hashes

        # Changing a's source makes it re-evaluate → b must follow
        a.set_source("pts = ones((5, 3))")

        original = cl._eval_cell
        b_calls = [0]

        def patched(c, shared):
            if c is b:
                b_calls[0] += 1
            return original(c, shared)

        cl._eval_cell = patched
        cl._rebuild_namespace()
        cl._eval_cell = original

        assert b_calls[0] == 1, f"Expected downstream cell to re-evaluate, got {b_calls[0]}"
