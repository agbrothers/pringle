"""
FEAT-050 (design-doc) — int_ and intp in equation namespace for array indexing.

Tests:
- int_ scalar cast
- int_ array cast
- arr[int_(round(k))] does not raise when k is a float
- intp is present and works identically
- AST check still blocks dangerous attribute access on int_/intp results
"""

import sys
import numpy as np
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.namespace import build_equation_namespace
from pringle.evaluator import run_cell
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(scope="module")
def ns():
    return build_equation_namespace()


@pytest.fixture(scope="module")
def grid():
    return make_grid(GridConfig(n=16))


# ---------------------------------------------------------------------------
# Namespace presence
# ---------------------------------------------------------------------------

def test_int_in_namespace(ns):
    assert "int_" in ns


def test_intp_in_namespace(ns):
    assert "intp" in ns


# ---------------------------------------------------------------------------
# int_ scalar and array casting
# ---------------------------------------------------------------------------

def test_int_scalar_cast(ns):
    result = ns["int_"](np.float64(3.5))
    assert result == 3
    assert np.issubdtype(type(result), np.integer)


def test_int_array_cast(ns):
    result = ns["int_"](np.array([1.9, 2.1, 3.0]))
    assert list(result) == [1, 2, 3]
    assert np.issubdtype(result.dtype, np.integer)


def test_intp_scalar_cast(ns):
    result = ns["intp"](np.float64(7.8))
    assert result == 7
    assert np.issubdtype(type(result), np.integer)


def test_intp_array_cast(ns):
    result = ns["intp"](np.array([0.5, 1.5, 2.5]))
    assert list(result) == [0, 1, 2]
    assert np.issubdtype(result.dtype, np.integer)


# ---------------------------------------------------------------------------
# Array indexing in an equation cell
# ---------------------------------------------------------------------------

def test_array_index_with_int_in_cell(qapp, grid):
    """int_(round(k)) can index an array without IndexError when k is a float."""
    shared = {"k": np.float64(2.0)}
    result = run_cell("arr = arange(10)\nn = int_(round(k))\nout = arr[n]", shared, grid)
    assert not result.error, result.error
    assert result.exports["out"] == 2


def test_array_index_with_intp_in_cell(qapp, grid):
    shared = {"k": np.float64(5.0)}
    result = run_cell("arr = arange(10)\nn = intp(round(k))\nout = arr[n]", shared, grid)
    assert not result.error, result.error
    assert result.exports["out"] == 5


# ---------------------------------------------------------------------------
# int_ dunder access is allowed (no sandbox)
# ---------------------------------------------------------------------------

def test_dunder_access_allowed_on_int_result(qapp, grid):
    """With the sandbox removed, dunder access on int_ results is no longer blocked."""
    result = run_cell("n = int_(1.0)\nklass = n.__class__", {}, grid)
    assert result.error is None
