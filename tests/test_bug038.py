"""
BUG-038 regression: assigning to a reserved spatial variable crashes the app.

Fix: run_cell now returns result.warning (not an exception) when the cell
source assigns to x, u, or v. The curve_x render path is removed; x is
strictly an input variable.
"""

import numpy as np
import pytest

from pringle.evaluator import run_cell
from pringle.grid import make_grid, GridConfig


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=16))


def test_assign_x_gives_warning(grid):
    result = run_cell("x = linspace(0, 100)", {}, grid)
    assert result.warning is not None
    assert "reserved" in result.warning
    assert result.render_type is None
    assert result.error is None


def test_assign_u_gives_warning(grid):
    result = run_cell("u = zeros((16, 16))", {}, grid)
    assert result.warning is not None
    assert "reserved" in result.warning
    assert result.render_type is None
    assert result.error is None


def test_assign_v_gives_warning(grid):
    result = run_cell("v = ones((16, 16))", {}, grid)
    assert result.warning is not None
    assert "reserved" in result.warning
    assert result.render_type is None
    assert result.error is None


def test_assign_y_still_renders(grid):
    """y is a valid output variable and must not be blocked by the reserved-var guard."""
    result = run_cell("y = sin(x)", {}, grid)
    assert result.error is None
    assert result.warning is None
    assert result.render_type in ("curve", "surface_y")


def test_assign_z_still_renders_surface(grid):
    """z = f(x,y) must still produce a surface — z is a valid output variable."""
    result = run_cell("z = x**2 + y**2", {}, grid)
    assert result.error is None
    assert result.render_type == "surface"
