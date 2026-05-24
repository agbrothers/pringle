"""
BUG-040 regression: float32 overflow during data cast emits a silent RuntimeWarning
and produces ±inf in the GPU buffer instead of notifying the user.

Fix: _cast_float32() in evaluator.py wraps np.asarray(..., dtype=np.float32) in
warnings.catch_warnings, counts any resulting ±inf values, and returns them as an
explicit warning string that surfaces as an orange indicator on the cell.
"""

import numpy as np
import pytest

from pringle.evaluator import run_cell, _cast_float32
from pringle.grid import make_grid, GridConfig


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=16))


# ---------------------------------------------------------------------------
# _cast_float32 unit tests
# ---------------------------------------------------------------------------

def test_cast_float32_normal_values():
    """Values within float32 range cast cleanly with no warning."""
    arr, warn = _cast_float32(np.array([1.0, 2.0, 3.0]))
    assert warn is None
    np.testing.assert_array_equal(arr, np.float32([1, 2, 3]))


def test_cast_float32_overflow_returns_warning():
    """Values exceeding float32 range produce ±inf and a non-empty warning."""
    big = np.array([1e39, -1e39])  # outside float32 max (~3.4e38)
    arr, warn = _cast_float32(big)
    assert warn is not None
    assert "inf" in warn.lower() or "overflow" in warn.lower()
    assert np.isinf(arr).all()


def test_cast_float32_warns_count():
    """Warning message includes the count of overflowed values."""
    data = np.array([1e39, 0.0, -1e39, 0.5])
    _, warn = _cast_float32(data)
    assert warn is not None
    assert "2" in warn  # two values overflowed


def test_cast_float32_nan_passthrough():
    """NaN values do not trigger an overflow warning (NaN is valid float32)."""
    data = np.array([np.nan, 1.0, np.nan])
    _, warn = _cast_float32(data)
    assert warn is None


# ---------------------------------------------------------------------------
# run_cell integration tests
# ---------------------------------------------------------------------------

def test_overflow_surface_sets_warning(grid):
    """A surface expression producing out-of-range values sets result.warning, not error."""
    # 1e39 exceeds float32 max; force a constant out-of-range surface
    result = run_cell("z = full((16,16), 1e39)", {}, grid)
    assert result.error is None
    assert result.warning is not None
    assert "overflow" in result.warning.lower() or "inf" in result.warning.lower()
    assert result.render_type == "surface"
    assert np.isinf(result.data).all()


def test_overflow_scatter_sets_warning(grid):
    """An (N,3) scatter with out-of-range values sets result.warning."""
    result = run_cell("points = full((5, 3), 1e39)", {}, grid)
    assert result.error is None
    assert result.warning is not None
    assert result.render_type == "scatter"


def test_normal_surface_no_overflow_warning(grid):
    """A well-behaved surface produces no overflow warning."""
    result = run_cell("z = sin(x) * cos(y)", {}, grid)
    assert result.error is None
    assert result.warning is None
    assert result.render_type == "surface"
