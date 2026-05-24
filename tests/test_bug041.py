"""
BUG-041 regression: SyntaxError in recurrence RHS crashes the app (Abort trap: 6).

Root cause: compile(rhs, "<recurrence>", "eval") had no try/except SyntaxError.
A mid-edit partial expression (e.g. "path[n-1] - dt*") raises SyntaxError that
propagated out of execute_recurrence, through _eval_cell, and into wgpu internals
causing a fatal abort.

Fix: execute_recurrence now catches SyntaxError and returns it as a warning string,
consistent with how every other error in that function is handled.
"""

import numpy as np
import pytest

from pringle.recurrence import execute_recurrence, parse_recurrence


def _ns():
    """Minimal namespace for recurrence evaluation."""
    return {"np": np, "zeros": np.zeros, "array": np.array}


def test_incomplete_rhs_no_crash():
    """Partial expression that is syntactically invalid must not raise — return a warning."""
    arr = np.zeros((10, 2))
    result_arr, warn = execute_recurrence(
        "path", arr, [], "path[n] = path[n-1] - dt*", _ns()
    )
    assert warn is not None
    assert "syntax" in warn.lower()
    assert isinstance(result_arr, np.ndarray)


def test_empty_rhs_no_crash():
    """Completely empty RHS must not raise."""
    arr = np.zeros((5,))
    result_arr, warn = execute_recurrence(
        "arr", arr, [], "arr[n] = ", _ns()
    )
    assert warn is not None
    assert isinstance(result_arr, np.ndarray)


def test_valid_rhs_still_works():
    """A correct recurrence rule still evaluates normally after the fix."""
    arr = np.zeros(5)
    arr[0] = 1.0
    result_arr, warn = execute_recurrence(
        "arr", arr, [], "arr[n] = arr[n-1] * 2", _ns()
    )
    assert warn is None
    np.testing.assert_allclose(result_arr, [1, 2, 4, 8, 16])


def test_parse_recurrence_still_works():
    """parse_recurrence is unaffected by the fix."""
    ok, name, rhs = parse_recurrence("path[n] = path[n-1] + 1")
    assert ok
    assert name == "path"
    assert rhs == "path[n-1] + 1"
