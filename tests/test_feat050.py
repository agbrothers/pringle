"""
FEAT-050 tests: shape preview for array-valued assignment cells.

Tests validate:
- Assignment cell with 2D+ ndarray sets shape_preview
- Assignment cell with 1D ndarray sets both shape_preview and preview
- Assignment cell with scalar sets preview but not shape_preview
- Bare expression path (existing behavior) is unchanged
- Multi-assignment: first user variable (source order) wins
"""

import numpy as np
import pytest

from pringle.evaluator import run_cell
from pringle.grid import make_grid


@pytest.fixture
def grid():
    return make_grid()


class TestAssignmentShapePreview:
    def test_2d_array_sets_shape_preview(self, grid):
        result = run_cell("M = zeros((10, 10))", {}, grid)
        assert result.error is None
        assert result.shape_preview == "(10, 10)"
        assert result.preview is None

    def test_3d_array_sets_shape_preview(self, grid):
        # (3, 8, 8): ndim=3, shape[0]=3 and shape[2]=8 — not detected by FEAT-049.
        result = run_cell("field = zeros((3, 8, 8))", {}, grid)
        assert result.error is None
        assert result.shape_preview == "(3, 8, 8)"
        assert result.preview is None

    def test_1d_array_sets_both_shape_and_preview(self, grid):
        # 'vec' avoids SPATIAL_NAMES (x, y, u, v); zeros() gives a previewable 1D array.
        result = run_cell("vec = zeros(3)", {}, grid)
        assert result.error is None
        assert result.shape_preview == "(3,)"
        assert result.preview == "[0, 0, 0]"

    def test_scalar_sets_preview_not_shape(self, grid):
        # 'a = 3.14' is a slider cell; use a computed expression instead.
        result = run_cell("a_val = 3.0 + 0.14", {}, grid)
        assert result.error is None
        assert result.preview == "3.14"
        assert result.shape_preview is None

    def test_integer_scalar_unchanged(self, grid):
        # 'n = 42' is a slider cell; use a computed expression instead.
        result = run_cell("n_computed = 6 * 7", {}, grid)
        assert result.error is None
        assert result.preview == "42"
        assert result.shape_preview is None

    def test_multi_assignment_scalar_first(self, grid):
        # Source order: a_val before mat_val. Scalar wins (sets preview, breaks before mat_val).
        result = run_cell("a_val = 3.14 + 0\nmat_val = zeros((5, 5))", {}, grid)
        assert result.error is None
        assert result.preview == "3.14"
        assert result.shape_preview is None

    def test_multi_assignment_array_first(self, grid):
        # Source order: mat_val before a_val. Array wins (sets shape_preview, breaks).
        result = run_cell("mat_val = zeros((5, 5))\na_val = 1.0 + 0", {}, grid)
        assert result.error is None
        assert result.shape_preview == "(5, 5)"

    def test_grid_vector_field_shows_original_shape(self, grid):
        # (4, n, n) is flattened by FEAT-049 into (n*n, 4) for rendering;
        # shape_preview must show the user's original variable shape, not the flat data.
        result = run_cell("field = zeros((4, 8, 8))", {}, grid)
        assert result.error is None
        assert result.render_type == "vectors_2d"
        assert result.shape_preview == "(4, 8, 8)"

    def test_1d_scatter_shows_original_shape(self, grid):
        # (3,) → detected as scatter (1, 3) by _detect_shape; shape_preview must show (3,).
        result = run_cell("pts = zeros(3)", {}, grid)
        assert result.error is None
        assert result.render_type == "scatter"
        assert result.shape_preview == "(3,)"

    def test_bare_expression_shape_preview_unchanged(self, grid):
        shared_ns = {"field": np.zeros((4, 64, 64), dtype=np.float32)}
        result = run_cell("field", shared_ns, grid)
        assert result.error is None
        assert result.shape_preview == "(4, 64, 64)"

    def test_bare_scalar_preview_unchanged(self, grid):
        shared_ns = {"c": np.float32(2.71)}
        result = run_cell("c", shared_ns, grid)
        assert result.error is None
        assert result.preview is not None
        assert result.shape_preview is None
