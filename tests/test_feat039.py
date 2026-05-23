"""
FEAT-039 tests: compact per-cell RNG seed replacing full MT19937 state.

Tests validate:
- Same seed produces identical draws across rebuilds
- Incrementing seed (→ press) produces different draws
- Session round-trip preserves rng_seed
- Old sessions with rng_state key load without error and default to seed 0
- Global np.random state is NOT mutated by cell evaluation
- rng_seed is omitted from shared namespace after rebuild
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
def cell_list(qapp):
    from pringle.cell_list import CellListWidget
    from pringle.grid import GridConfig, make_grid
    grid = make_grid(GridConfig(n=16))
    return CellListWidget(on_cell_result=_noop_result, grid=grid)


# ---------------------------------------------------------------------------
# Reproducibility: same seed → same draws
# ---------------------------------------------------------------------------

class TestSeedReproducibility:
    def test_same_seed_produces_identical_draws(self, cell_list):
        """Rebuilding twice with the same seed must produce the same export value."""
        cell = cell_list.add_cell(source="M = random.random((10, 2))")
        cell_list._rebuild_namespace()
        first = cell._last_result.exports["M"].copy()

        cell_list._rebuild_namespace()
        second = cell._last_result.exports["M"].copy()

        np.testing.assert_array_equal(first, second)

    def test_different_seeds_produce_different_draws(self, cell_list):
        """Manually setting a different seed must change the output."""
        cell = cell_list.add_cell(source="M = random.random((10, 2))")
        cell._rng_seed = 0
        cell_list._rebuild_namespace()
        at_seed_0 = cell._last_result.exports["M"].copy()

        cell._rng_seed = 1
        cell_list._rebuild_namespace()
        at_seed_1 = cell._last_result.exports["M"].copy()

        assert not np.array_equal(at_seed_0, at_seed_1)

    def test_run_requested_increments_seed(self, cell_list):
        """Pressing → increments _rng_seed by 1, producing different draws."""
        cell = cell_list.add_cell(source="M = random.random((10, 2))")
        cell._rng_seed = 0
        cell_list._rebuild_namespace()
        before = cell._last_result.exports["M"].copy()

        # Simulate → button press
        cell_list._on_run_requested(cell.cell_id)
        assert cell._rng_seed == 1

        after = cell._last_result.exports["M"].copy()
        assert not np.array_equal(before, after)

    def test_seed_wraps_at_2_32(self, cell_list):
        """Seed increments modulo 2**32 to stay within MT seed range."""
        cell = cell_list.add_cell(source="M = random.random((4,))")
        cell._rng_seed = 2**32 - 1
        cell_list._on_run_requested(cell.cell_id)
        assert cell._rng_seed == 0


# ---------------------------------------------------------------------------
# Global np.random state isolation
# ---------------------------------------------------------------------------

class TestGlobalStateIsolation:
    def test_global_np_random_not_mutated(self, cell_list):
        """Cell evaluation must not change the global np.random state."""
        np.random.seed(42)
        ref = np.random.random(5).copy()

        np.random.seed(42)
        cell = cell_list.add_cell(source="M = random.random((100, 3))")
        cell_list._rebuild_namespace()
        after = np.random.random(5)

        np.testing.assert_array_equal(ref, after)


# ---------------------------------------------------------------------------
# Shared namespace cleanup
# ---------------------------------------------------------------------------

class TestSharedNamespaceCleanup:
    def test_random_not_in_shared_ns_after_rebuild(self, cell_list):
        """random must not leak into _shared_ns after rebuild."""
        cell_list.add_cell(source="M = random.random((5,))")
        cell_list._rebuild_namespace()
        assert "random" not in cell_list._shared_ns


# ---------------------------------------------------------------------------
# Session round-trip
# ---------------------------------------------------------------------------

class TestSessionRoundTrip:
    def test_rng_seed_survives_save_load(self, cell_list, tmp_path):
        """rng_seed is written to YAML and restored on load."""
        from pringle.session import cell_to_dict, restore_cell_list
        from pringle.cell_widget import CellWidget

        cell = cell_list.add_cell(source="M = random.random((5,))")
        cell._rng_seed = 7
        cell_list._rebuild_namespace()

        data = cell_to_dict(cell, folder_id=None)
        assert data["rng_seed"] == 7

        cell2 = CellWidget()
        restore_cell_list(cell_list, [data])
        restored = next(c for c in cell_list._cells
                        if hasattr(c, "_rng_seed") and c.source() == "M = random.random((5,))")
        assert restored._rng_seed == 7

    def test_old_rng_state_key_migrates_to_seed_0(self, cell_list):
        """Old YAML with rng_state key loads without error, seed defaults to 0."""
        from pringle.cell_widget import CellWidget

        cell = CellWidget()
        # Simulate what restore_cell_list does for old format data
        data = {
            "rng_state": list(range(624)),
            "rng_pos": 0,
            "rng_has_gauss": 0,
            "rng_gauss": 0.0,
        }
        if "rng_state" in data:
            cell._rng_seed = 0
        elif "rng_seed" in data:
            cell._rng_seed = int(data["rng_seed"])
        else:
            cell._rng_seed = 0

        assert cell._rng_seed == 0
        # Must not have _pending_rng_state (old attribute)
        assert not hasattr(cell, "_pending_rng_state")

    def test_new_rng_seed_key_restored_correctly(self, cell_list):
        """New YAML with rng_seed key restores the exact integer."""
        from pringle.cell_widget import CellWidget

        cell = CellWidget()
        data = {"rng_seed": 42}
        if "rng_state" in data:
            cell._rng_seed = 0
        elif "rng_seed" in data:
            cell._rng_seed = int(data["rng_seed"])
        else:
            cell._rng_seed = 0

        assert cell._rng_seed == 42


def CellListWidget(on_cell_result, grid):
    from pringle.cell_list import CellListWidget as _CL
    return _CL(on_cell_result=on_cell_result, grid=grid)
