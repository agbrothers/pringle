"""
BUG-042 regression: `t` cannot be used as a reliable integer index.

Two bugs fixed:
1. `t` was in _ALWAYS_DEFINED in dag.py, suppressing "Undefined: 't'" warnings
   for cells that used `t` without defining a slider named `t`.
2. `int` was absent from the equation namespace (builtins disabled), so
   `path[int(t)]` raised NameError regardless of whether `t` was defined.
"""

import numpy as np
import pytest

from pringle.evaluator import run_cell
from pringle.grid import make_grid, GridConfig
from pringle.dag import _always_defined


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=16))


# ---------------------------------------------------------------------------
# Fix 1: t is not in _ALWAYS_DEFINED — cells using t without a slider get warned
# ---------------------------------------------------------------------------

def test_t_not_in_always_defined():
    """`t` must not appear in the always-defined set so the DAG can warn about it."""
    assert "t" not in _always_defined()


# ---------------------------------------------------------------------------
# Fix 2: int() is available in the equation namespace
# ---------------------------------------------------------------------------

def test_int_available_in_namespace(grid):
    """int() must work inside an equation cell (it's needed for array indexing)."""
    shared = {"k": 3}
    result = run_cell("val = int(k)", shared, grid)
    assert result.error is None
    assert result.exports.get("val") == 3


def test_int_coercion_of_slider_for_index(grid):
    """A slider value coerced with int() must produce the correct array element."""
    arr = np.arange(10, dtype=np.float32)
    shared = {"arr": arr, "idx_val": 4}  # slider t=4 (already int via _ns_value)
    result = run_cell("val = arr[idx_val]", shared, grid)
    assert result.error is None
    assert result.exports.get("val") == pytest.approx(4.0)


def test_int_round_for_float_slider_index(grid):
    """int(round(t)) handles floating-point slider values without off-by-one errors."""
    arr = np.arange(10, dtype=np.float32)
    # Simulate a float slider value that accumulates FP error (e.g. 0.1 * 20 ≠ 2.0 exactly)
    t_val = 0.1 * 20   # typically 2.0000000000000004 in float64
    shared = {"arr": arr, "t_val": t_val}
    result = run_cell("val = arr[int(round(t_val))]", shared, grid)
    assert result.error is None
    assert result.exports.get("val") == pytest.approx(2.0)


def test_int_of_whole_float_slider(grid):
    """int(t) works correctly when the slider value is a whole-number float."""
    arr = np.arange(10, dtype=np.float32)
    shared = {"arr": arr, "t_val": 5.0}
    result = run_cell("val = arr[int(t_val)]", shared, grid)
    assert result.error is None
    assert result.exports.get("val") == pytest.approx(5.0)
