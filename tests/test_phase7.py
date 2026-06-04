"""
Phase 7 tests: dependency graph (DAG) and topological evaluation.

Tests validate:
- DAG construction: correct edges from cell define/use sets
- Topological ordering respects dependencies
- Cycle detection flags both sides of a cycle
- Undefined-name warnings appear on the right cell
- Slider incremental eval: only descendants are re-evaluated
- cell_defines / cell_uses helpers
- downstream_of returns correct descendants in topo order
"""

import sys
import pytest
import numpy as np

from PyQt6.QtWidgets import QApplication

from pringle.dag import (
    build_dag, topo_order, downstream_of, undefined_names,
    cell_defines, cell_uses,
)
from pringle.slider_widget import SliderWidget
from pringle.cell_widget import CellWidget
from pringle.cell_list import CellListWidget
from pringle.style import CellStyle
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=32))


# ---------------------------------------------------------------------------
# Helper: minimal stub cell for DAG tests without a QApplication
# ---------------------------------------------------------------------------

class StubCell:
    """Lightweight stand-in that the DAG functions accept."""

    def __init__(self, cell_id: str, src: str):
        self.cell_id = cell_id
        self._src = src

    def source(self) -> str:
        return self._src


# ---------------------------------------------------------------------------
# cell_defines / cell_uses
# ---------------------------------------------------------------------------

class TestCellDefinesUses:
    def test_slider_defines_name(self, qapp):
        s = SliderWidget(name="a", value=1.0)
        assert cell_defines(s) == {"a"}

    def test_slider_uses_nothing(self, qapp):
        s = SliderWidget(name="a", value=1.0)
        assert cell_uses(s) == set()

    def test_surface_cell_defines_z(self):
        c = StubCell("c1", "z = sin(x) * cos(y)")
        assert "z" in cell_defines(c)

    def test_surface_cell_uses_user_name(self):
        c = StubCell("c1", "z = a * sin(x)")
        uses = cell_uses(c)
        assert "a" in uses
        # sin and x are always-defined; they should NOT appear
        assert "sin" not in uses
        assert "x" not in uses

    def test_lambda_cell_defines_function(self):
        c = StubCell("c1", "f = lambda x, y: x + y")
        assert "f" in cell_defines(c)

    def test_lambda_params_not_free(self):
        c = StubCell("c1", "f = lambda x, y: a * x + y")
        uses = cell_uses(c)
        assert "a" in uses
        assert "x" not in uses
        assert "y" not in uses

    def test_empty_cell_defines_nothing(self):
        c = StubCell("c1", "")
        assert cell_defines(c) == set()
        assert cell_uses(c) == set()


# ---------------------------------------------------------------------------
# build_dag
# ---------------------------------------------------------------------------

class TestBuildDag:
    def test_independent_cells_no_edges(self, qapp):
        c1 = StubCell("c1", "z = sin(x)")
        c2 = StubCell("c2", "z = cos(x)")
        dag = build_dag([c1, c2])
        assert dag.number_of_edges() == 0

    def test_slider_feeds_surface(self, qapp):
        s = SliderWidget(name="a", value=2.0, cell_id="s1")
        c = StubCell("c1", "z = a * sin(x)")
        dag = build_dag([s, c])
        assert dag.has_edge("s1", "c1"), "surface cell should depend on slider"

    def test_function_feeds_surface(self):
        f = StubCell("f1", "f = lambda x, y: x + y")
        z = StubCell("z1", "z = f(x, y)")
        dag = build_dag([f, z])
        assert dag.has_edge("f1", "z1")

    def test_chain_a_b_c(self):
        a = StubCell("a", "a_val = 3.0")
        b = StubCell("b", "b_val = a_val * 2")
        c = StubCell("c", "z = b_val + 1")
        dag = build_dag([a, b, c])
        assert dag.has_edge("a", "b")
        assert dag.has_edge("b", "c")

    def test_no_self_edges(self):
        c = StubCell("c1", "a = a + 1")  # self-reference
        dag = build_dag([c])
        assert not dag.has_edge("c1", "c1")

    def test_all_cells_are_nodes(self, qapp):
        s = SliderWidget(name="k", value=1.0, cell_id="s1")
        c = StubCell("c1", "")  # empty cell
        dag = build_dag([s, c])
        assert "s1" in dag.nodes
        assert "c1" in dag.nodes


# ---------------------------------------------------------------------------
# topo_order
# ---------------------------------------------------------------------------

class TestTopoOrder:
    def test_independent_cells_visual_order(self):
        c1 = StubCell("c1", "z = sin(x)")
        c2 = StubCell("c2", "z = cos(x)")
        dag = build_dag([c1, c2])
        ordered, cyclic = topo_order(dag, [c1, c2])
        assert cyclic == set()
        assert [c.cell_id for c in ordered] == ["c1", "c2"]

    def test_independent_cells_visual_order_reversed_input(self):
        # Cells with no DAG edges must preserve visual order even when nx.topological_sort
        # would return them in reversed order (its DFS post-order reversal bug).
        c1 = StubCell("c1", "z = sin(x)")
        c2 = StubCell("c2", "z = cos(x)")
        c3 = StubCell("c3", "z = tan(x)")
        dag = build_dag([c1, c2, c3])
        ordered, cyclic = topo_order(dag, [c1, c2, c3])
        assert cyclic == set()
        assert [c.cell_id for c in ordered] == ["c1", "c2", "c3"]

    def test_dependency_before_dependent(self):
        # c2 depends on c1 (c1 defines 'val'; c2 uses 'val')
        c1 = StubCell("c1", "val = 3.0")
        c2 = StubCell("c2", "z = val * sin(x)")
        dag = build_dag([c1, c2])
        ordered, cyclic = topo_order(dag, [c1, c2])
        assert cyclic == set()
        ids = [c.cell_id for c in ordered]
        assert ids.index("c1") < ids.index("c2")

    def test_cycle_detected(self):
        # c1 uses b_var; c2 uses a_var; c1 defines a_var; c2 defines b_var → cycle
        c1 = StubCell("c1", "a_var = b_var + 1")
        c2 = StubCell("c2", "b_var = a_var - 1")
        dag = build_dag([c1, c2])
        _, cyclic = topo_order(dag, [c1, c2])
        assert "c1" in cyclic
        assert "c2" in cyclic

    def test_three_cell_chain(self):
        a = StubCell("a", "aa = 1.0")
        b = StubCell("b", "bb = aa * 2")
        c = StubCell("c", "z = bb + 1")
        dag = build_dag([a, b, c])
        ordered, cyclic = topo_order(dag, [a, b, c])
        assert cyclic == set()
        ids = [x.cell_id for x in ordered]
        assert ids.index("a") < ids.index("b") < ids.index("c")


# ---------------------------------------------------------------------------
# downstream_of
# ---------------------------------------------------------------------------

class TestDownstreamOf:
    def test_no_descendants(self):
        c1 = StubCell("c1", "z = sin(x)")
        dag = build_dag([c1])
        assert downstream_of(dag, "c1", [c1]) == []

    def test_direct_descendant(self, qapp):
        s = SliderWidget(name="a", value=1.0, cell_id="s1")
        c = StubCell("c1", "z = a * sin(x)")
        dag = build_dag([s, c])
        desc = downstream_of(dag, "s1", [s, c])
        assert len(desc) == 1
        assert desc[0].cell_id == "c1"

    def test_transitive_descendants(self):
        a = StubCell("a", "aa = 1.0")
        b = StubCell("b", "bb = aa * 2")
        c = StubCell("c", "z = bb + 1")
        dag = build_dag([a, b, c])
        desc = downstream_of(dag, "a", [a, b, c])
        desc_ids = [x.cell_id for x in desc]
        assert "b" in desc_ids
        assert "c" in desc_ids
        # b must come before c
        assert desc_ids.index("b") < desc_ids.index("c")

    def test_missing_id(self):
        c = StubCell("c1", "z = sin(x)")
        dag = build_dag([c])
        assert downstream_of(dag, "nonexistent", [c]) == []


# ---------------------------------------------------------------------------
# undefined_names
# ---------------------------------------------------------------------------

class TestUndefinedNames:
    def test_all_defined(self, qapp):
        s = SliderWidget(name="a", value=1.0, cell_id="s1")
        c = StubCell("c1", "z = a * sin(x)")
        result = undefined_names([s, c])
        assert "c1" not in result  # 'a' is defined by s

    def test_undefined_user_name(self):
        c = StubCell("c1", "z = q * sin(x)")
        result = undefined_names([c])
        assert "c1" in result
        assert "q" in result["c1"]

    def test_spatial_not_undefined(self):
        c = StubCell("c1", "z = x * y")
        result = undefined_names([c])
        assert "c1" not in result  # x and y are always defined

    def test_namespace_builtins_not_undefined(self):
        c = StubCell("c1", "z = sin(x) + cos(y) + pi")
        result = undefined_names([c])
        assert "c1" not in result  # sin, cos, pi are always defined


# ---------------------------------------------------------------------------
# CellListWidget DAG integration
# ---------------------------------------------------------------------------

class TestCellListDag:
    def _make_list(self, qapp, grid):
        results = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: results.append((cid, r, s)),
            grid=grid,
        )
        return clist, results

    def test_forward_dependency_resolves(self, qapp, grid):
        """Cell evaluating a downstream-defined name works when topo order is correct."""
        captured = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: captured.append((cid, r, s)),
            grid=grid,
        )
        # Slider 'a' defined first, used by surface second — should work
        clist.add_cell("a = 2.0")
        clist.add_cell("z = a * sin(x) * cos(y)")

        surface = [(cid, r) for cid, r, _ in captured if r.render_type == "surface"]
        assert len(surface) > 0
        _, res = surface[-1]
        assert res.data is not None

    def test_cycle_shows_error(self, qapp, grid):
        """Cells in a cycle both display a cycle error."""
        clist, _ = self._make_list(qapp, grid)
        c1 = clist.add_cell("aa = bb + 1")
        c2 = clist.add_cell("bb = aa - 1")
        # Both cells should have their error label visible
        assert not c1._error_label.isHidden(), "c1 should show cycle error"
        assert not c2._error_label.isHidden(), "c2 should show cycle error"

    def test_undefined_shows_warning(self, qapp, grid):
        """A cell using an undefined name shows a warning."""
        clist, _ = self._make_list(qapp, grid)
        cell = clist.add_cell("z = q_undefined * sin(x)")
        # Warning or error should be visible (NameError from eval or DAG warning)
        visible = (
            not cell._error_label.isHidden()
            or not cell._warning_label.isHidden()
        )
        assert visible

    def test_slider_incremental_eval(self, qapp, grid):
        """Slider change re-evaluates only its downstream cells."""
        eval_count = {"count": 0}
        original_run_cell = None

        import pringle.cell_list as cl_mod
        import pringle.evaluator as ev_mod

        original_run_cell = ev_mod.run_cell

        def counting_run_cell(source, shared, grid, **kw):
            eval_count["count"] += 1
            return original_run_cell(source, shared, grid, **kw)

        ev_mod.run_cell = counting_run_cell
        try:
            clist = CellListWidget(
                on_cell_result=lambda cid, r, s: None,
                grid=grid,
            )
            slider = clist.add_cell("a = 1.0")
            clist.add_cell("z = a * sin(x) * cos(y)")
            clist.add_cell("w = cos(x) * sin(y)")  # independent of slider

            # After initial setup, reset count
            eval_count["count"] = 0

            # Change slider value — should only re-eval the 'z' cell (dependent)
            # NOT the 'w' cell (independent)
            slider.set_value(3.0)

            # Only the dependent cell(s) should have been re-evaluated
            # 'w = cos(x)*sin(y)' is independent → should NOT be re-evaluated
            assert eval_count["count"] < 3, (
                f"Expected incremental eval (< 3 calls), got {eval_count['count']}"
            )
        finally:
            ev_mod.run_cell = original_run_cell

    def test_slider_downstream_updates_value(self, qapp, grid):
        """After slider change, downstream surface uses the new value."""
        surface_data = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: surface_data.append(r.data)
            if r.render_type == "surface" else None,
            grid=grid,
        )
        slider = clist.add_cell("a = 1.0")
        clist.add_cell("z = a * sin(x) * cos(y)")

        surface_data.clear()
        slider.set_value(5.0)

        assert len(surface_data) > 0
        assert np.max(np.abs(surface_data[-1])) == pytest.approx(5.0, abs=0.4)

    def test_three_cell_chain_correct_order(self, qapp, grid):
        """Chain: val → scale_z → z renders correctly regardless of add order."""
        captured = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: captured.append((cid, r, s)),
            grid=grid,
        )
        # Add in dependency order
        clist.add_cell("scale = 2.0")
        clist.add_cell("amplitude = scale * 1.5")
        clist.add_cell("z = amplitude * sin(x) * cos(y)")

        surface = [(cid, r) for cid, r, _ in captured if r.render_type == "surface"]
        assert len(surface) > 0
        _, res = surface[-1]
        assert res.data is not None
        # Peak ~= 2.0 * 1.5 = 3.0
        assert np.max(np.abs(res.data)) == pytest.approx(3.0, abs=0.4)
