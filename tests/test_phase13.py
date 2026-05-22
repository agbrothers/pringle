"""
Phase 13 tests: RNG state persistence (BUG-029).

Tests validate:
- Equation cell random draws are stable across repeated _rebuild_namespace calls
- Equation cell random draws reproduce correctly after session save/load
- Full MT state (pos, has_gauss, cached_gaussian) round-trips cleanly
"""

import sys
import os
import tempfile

import numpy as np
import pytest

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
# Equation cell RNG persistence
# ---------------------------------------------------------------------------

class TestEquationCellRNG:
    def test_rng_state_captured_on_first_eval(self, qapp, grid):
        """_rng_state is set on an equation cell after its first evaluation."""
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("M = random.random((10, 2)) * 6 - 3")
        assert hasattr(cell, "_rng_state"), "_rng_state not set after first eval"
        assert cell._rng_state is not None

    def test_random_draws_stable_across_rebuilds(self, qapp, grid):
        """Random equation cell produces identical exports on every _rebuild_namespace."""
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("M = random.random((10, 2)) * 6 - 3")

        original = cell._last_result.exports["M"].copy()

        for _ in range(3):
            cl._rebuild_namespace()
            assert np.allclose(cell._last_result.exports["M"], original), \
                "M changed after rebuild — RNG state not restored"

    def test_random_draws_stable_with_other_cells(self, qapp, grid):
        """Random cell stays stable even when an unrelated cell rebuilds."""
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        random_cell = cl.add_cell("M = random.random((10, 2)) * 6 - 3")
        cl.add_cell("z = sin(x) + cos(y)")  # triggers rebuild when added

        original_M = random_cell._last_result.exports["M"].copy()

        # Multiple additional rebuilds should not change M
        for _ in range(3):
            cl._rebuild_namespace()
            assert np.allclose(random_cell._last_result.exports["M"], original_M), \
                "M changed when an unrelated cell was updated"

    def test_rng_state_round_trip_yaml(self, qapp, grid):
        """rng_state is written to and read back from YAML with correct shape and dtype."""
        from pringle.cell_list import CellListWidget
        from pringle.session import save_session, load_session
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.add_cell("M = random.random((10, 2)) * 6 - 3")

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name
        try:
            save_session(path, cl, grid.config)
            data = load_session(path)
            cell_data = data["cells"][0]
            assert "rng_state" in cell_data, "rng_state not written to YAML"
            assert len(cell_data["rng_state"]) == 624
            assert "rng_pos" in cell_data
            assert "rng_has_gauss" in cell_data
            assert "rng_gauss" in cell_data
        finally:
            os.unlink(path)

    def test_random_draws_reproduce_after_session_load(self, qapp, grid):
        """Random equation cell produces the same M after save → load → rebuild."""
        from pringle.cell_list import CellListWidget
        from pringle.session import save_session, load_session, restore_cell_list

        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("M = random.random((10, 2)) * 6 - 3")
        original_M = cell._last_result.exports["M"].copy()

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name
        try:
            save_session(path, cl, grid.config)

            cl2 = CellListWidget(on_cell_result=_noop_result, grid=grid)
            restore_cell_list(cl2, load_session(path)["cells"])

            cell2 = cl2._cells[0]
            assert cell2._last_result is not None
            loaded_M = cell2._last_result.exports["M"]
            assert np.allclose(loaded_M, original_M), \
                f"M changed after session load.\nOriginal:\n{original_M}\nLoaded:\n{loaded_M}"
        finally:
            os.unlink(path)

    def test_random_draws_stable_after_load_and_rebuild(self, qapp, grid):
        """After session load, further rebuilds still reproduce the same M."""
        from pringle.cell_list import CellListWidget
        from pringle.session import save_session, load_session, restore_cell_list

        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("M = random.random((10, 2)) * 6 - 3")
        original_M = cell._last_result.exports["M"].copy()

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name
        try:
            save_session(path, cl, grid.config)

            cl2 = CellListWidget(on_cell_result=_noop_result, grid=grid)
            restore_cell_list(cl2, load_session(path)["cells"])

            cell2 = cl2._cells[0]
            for _ in range(3):
                cl2._rebuild_namespace()
                assert np.allclose(cell2._last_result.exports["M"], original_M), \
                    "M changed on post-load rebuild"
        finally:
            os.unlink(path)

    def test_run_requested_produces_fresh_draws(self, qapp, grid):
        """Explicit → click (run_requested) clears saved state so new draws are produced."""
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("M = random.random((10, 2)) * 6 - 3")

        first = cell._last_result.exports["M"].copy()

        # Simulate → click: emits run_requested → _on_run_requested
        cl._on_run_requested(cell.cell_id)

        second = cell._last_result.exports["M"]
        assert not np.allclose(first, second), \
            "→ click should produce new random draws, but M is unchanged"

        # After the explicit re-run, subsequent automatic rebuilds should be stable
        for _ in range(3):
            cl._rebuild_namespace()
            assert np.allclose(cell._last_result.exports["M"], second), \
                "M changed on passive rebuild after explicit re-run"

    def test_two_random_cells_independent(self, qapp, grid):
        """Two random equation cells each pin their own state independently."""
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        c1 = cl.add_cell("A = random.random((5, 2))")
        c2 = cl.add_cell("B = random.random((5, 2))")

        orig_A = c1._last_result.exports["A"].copy()
        orig_B = c2._last_result.exports["B"].copy()

        # A and B should be different from each other (drawn at different MT positions)
        assert not np.allclose(orig_A, orig_B), "A and B coincidentally identical — seed issue"

        for _ in range(3):
            cl._rebuild_namespace()
            assert np.allclose(c1._last_result.exports["A"], orig_A)
            assert np.allclose(c2._last_result.exports["B"], orig_B)
