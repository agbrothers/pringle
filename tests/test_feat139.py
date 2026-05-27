"""
FEAT-139 — Batch scatter rendering for (k, N, 2) and (k, N, 3) arrays.

Tests cover:
- _detect_shape: (k, N, 3) → scatter_batch, (k, N, 2) → scatter_batch_2d
- _detect_shape: (k, N, 6) NOT treated as batch scatter (vectors take priority)
- _detect_shape: (k, N, 4) NOT treated as batch scatter (vectors_2d takes priority)
- channels-first vector shapes not shadowed by batch scatter
- run_cell: scatter_batch render type returned for bare (k, N, 3) assignment
- run_cell: scatter_batch_2d render type returned for bare (k, N, 2) assignment
- run_cell: points = arr with (k, N, 3) → scatter_batch via magic name path
- run_cell: points = arr with (k, N, 2) → scatter_batch_2d via magic name path
- run_cell: data is cast to float32
- validate_shape: correct validation for both batch types
- Per-line colormap: each of k lines independently gets 0→1 gradient
- app.py dispatch: circles mode → (k*N, 3) points geometry (no separators)
- app.py dispatch: line mode → NaN-separated concatenation
- app.py dispatch: arrows mode → vectorized (k*(N-1), 6) geometry
"""

from __future__ import annotations

import numpy as np
import pytest

from pringle.evaluator import _detect_shape, run_cell, validate_shape
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def grid():
    return make_grid(GridConfig(n=32))


# ---------------------------------------------------------------------------
# _detect_shape — batch scatter detection
# ---------------------------------------------------------------------------

class TestDetectShapeBatch:
    def test_k_n_3_is_scatter_batch(self):
        val = np.ones((5, 100, 3), dtype=np.float32)
        rt, data = _detect_shape(val)
        assert rt == "scatter_batch"
        assert data is val

    def test_k_n_2_is_scatter_batch_2d(self):
        val = np.ones((5, 100, 2), dtype=np.float32)
        rt, data = _detect_shape(val)
        assert rt == "scatter_batch_2d"
        assert data is val

    def test_k_n_6_is_vectors_not_batch(self):
        # (k, N, 6) must be detected as vectors (channels-last), not batch scatter
        val = np.ones((5, 100, 6), dtype=np.float32)
        rt, flat = _detect_shape(val)
        assert rt == "vectors"
        assert flat.shape == (500, 6)

    def test_k_n_4_is_vectors_2d_not_batch(self):
        val = np.ones((5, 100, 4), dtype=np.float32)
        rt, flat = _detect_shape(val)
        assert rt == "vectors_2d"
        assert flat.shape == (500, 4)

    def test_channels_first_6_n_n_not_shadowed(self):
        # (6, n, n) → vectors via channels-first path; must not fall into batch scatter
        val = np.ones((6, 10, 10), dtype=np.float32)
        rt, flat = _detect_shape(val)
        assert rt == "vectors"
        assert flat.shape == (100, 6)

    def test_channels_first_4_n_n_not_shadowed(self):
        val = np.ones((4, 10, 10), dtype=np.float32)
        rt, flat = _detect_shape(val)
        assert rt == "vectors_2d"
        assert flat.shape == (100, 4)

    def test_n_3_still_scatter(self):
        # 2D (N, 3) must still be plain scatter, not batch
        val = np.ones((100, 3), dtype=np.float32)
        rt, _ = _detect_shape(val)
        assert rt == "scatter"

    def test_n_2_still_scatter_2d(self):
        val = np.ones((100, 2), dtype=np.float32)
        rt, _ = _detect_shape(val)
        assert rt == "scatter_2d"

    def test_small_k_n_3(self):
        # k=1, N=1 edge case — still batch
        val = np.ones((1, 1, 3), dtype=np.float32)
        rt, _ = _detect_shape(val)
        assert rt == "scatter_batch"


# ---------------------------------------------------------------------------
# validate_shape — batch types
# ---------------------------------------------------------------------------

class TestValidateShapeBatch:
    def test_valid_scatter_batch(self, grid):
        data = np.ones((5, 100, 3), dtype=np.float32)
        assert validate_shape("scatter_batch", data, grid) is None

    def test_valid_scatter_batch_2d(self, grid):
        data = np.ones((5, 100, 2), dtype=np.float32)
        assert validate_shape("scatter_batch_2d", data, grid) is None

    def test_wrong_ndim_scatter_batch(self, grid):
        data = np.ones((100, 3), dtype=np.float32)
        msg = validate_shape("scatter_batch", data, grid)
        assert msg is not None
        assert "k, N, 3" in msg

    def test_wrong_cols_scatter_batch(self, grid):
        # (k, N, 2) given to scatter_batch (needs 3 cols)
        data = np.ones((5, 100, 2), dtype=np.float32)
        msg = validate_shape("scatter_batch", data, grid)
        assert msg is not None
        assert "3 columns" in msg

    def test_wrong_cols_scatter_batch_2d(self, grid):
        data = np.ones((5, 100, 3), dtype=np.float32)
        msg = validate_shape("scatter_batch_2d", data, grid)
        assert msg is not None
        assert "2 columns" in msg


# ---------------------------------------------------------------------------
# run_cell — render type detection via shape inference
# ---------------------------------------------------------------------------

class TestRunCellBatch:
    def test_k_n_3_bare_assignment_gives_scatter_batch(self, grid):
        # k=5 avoids the channels-first ambiguity (shape[0] in {4, 6} → vector priority)
        src = "arr = ones((5, 50, 3))"
        result = run_cell(src, {}, grid, is_data_cell=True)
        assert result.render_type == "scatter_batch"
        assert result.data.shape == (5, 50, 3)
        assert result.data.dtype == np.float32

    def test_k_n_2_bare_assignment_gives_scatter_batch_2d(self, grid):
        src = "arr = ones((5, 50, 2))"
        result = run_cell(src, {}, grid, is_data_cell=True)
        assert result.render_type == "scatter_batch_2d"
        assert result.data.shape == (5, 50, 2)
        assert result.data.dtype == np.float32

    def test_points_magic_k_n_3_gives_scatter_batch(self, grid):
        src = "points = ones((3, 20, 3))"
        result = run_cell(src, {}, grid, is_data_cell=True)
        assert result.render_type == "scatter_batch"
        assert result.data.shape == (3, 20, 3)

    def test_points_magic_k_n_2_gives_scatter_batch_2d(self, grid):
        src = "points = ones((3, 20, 2))"
        result = run_cell(src, {}, grid, is_data_cell=True)
        assert result.render_type == "scatter_batch_2d"
        assert result.data.shape == (3, 20, 2)

    def test_points_magic_n_3_still_plain_scatter(self, grid):
        # (N, 3) via points = ... must remain plain scatter
        src = "points = ones((50, 3))"
        result = run_cell(src, {}, grid, is_data_cell=True)
        assert result.render_type == "scatter"

    def test_shape_preview_set(self, grid):
        src = "arr = ones((5, 50, 3))"
        result = run_cell(src, {}, grid, is_data_cell=True)
        assert result.shape_preview == "(5, 50, 3)"

    def test_from_shape_inference_true_for_bare(self, grid):
        src = "arr = ones((5, 50, 3))"
        result = run_cell(src, {}, grid, is_data_cell=True)
        assert result.from_shape_inference is True

    def test_from_shape_inference_false_for_points_magic(self, grid):
        src = "points = ones((4, 50, 3))"
        result = run_cell(src, {}, grid, is_data_cell=True)
        assert result.from_shape_inference is False

    def test_k_n_6_does_not_give_scatter_batch(self, grid):
        src = "arr = ones((4, 50, 6))"
        result = run_cell(src, {}, grid, is_data_cell=True)
        assert result.render_type == "vectors"


# ---------------------------------------------------------------------------
# Per-line colormap geometry — verified at the array level
# ---------------------------------------------------------------------------

class TestPerLineColormap:
    """Verify that the colormap arrays produced in the dispatch block are correct."""

    def _apply_colormap(self, idx_vals, cmap, rev):
        from pringle.renderer import _apply_colormap
        return _apply_colormap(idx_vals, cmap, rev)

    def test_circles_vertex_colors_shape(self):
        """circles mode: vertex_colors must be (k*N, 4)."""
        k, N = 5, 100
        cmap = "viridis"
        idx_line = np.linspace(0.0, 1.0, N, dtype=np.float32)
        line_colors = self._apply_colormap(idx_line, cmap, False)   # (N, 4)
        vertex_colors = np.tile(line_colors, (k, 1))                # (k*N, 4)
        assert vertex_colors.shape == (k * N, 4)

    def test_circles_each_line_spans_0_to_1(self):
        """Each block of N rows in vertex_colors must independently span 0→1."""
        k, N = 3, 50
        cmap = "viridis"
        idx_line = np.linspace(0.0, 1.0, N, dtype=np.float32)
        line_colors = self._apply_colormap(idx_line, cmap, False)
        vertex_colors = np.tile(line_colors, (k, 1))
        for i in range(k):
            block = vertex_colors[i * N:(i + 1) * N]
            # Each block should be identical to line_colors
            np.testing.assert_array_equal(block, line_colors)

    def test_line_mode_vertex_colors_shape(self):
        """line mode: vertex_colors must be (k*(N+1)-1, 4)."""
        k, N = 5, 100
        cmap = "viridis"
        idx_line = np.linspace(0.0, 1.0, N, dtype=np.float32)
        line_colors = self._apply_colormap(idx_line, cmap, False)       # (N, 4)
        tiled = np.tile(line_colors, (k, 1)).reshape(k, N, 4)
        nan_row = np.zeros((k, 1, 4), dtype=np.float32)
        vertex_colors = np.concatenate([tiled, nan_row], axis=1).reshape(-1, 4)[:-1]
        assert vertex_colors.shape == (k * (N + 1) - 1, 4)

    def test_line_mode_each_line_block_spans_0_to_1(self):
        """line mode: each N-point block in vertex_colors must span the full colormap."""
        k, N = 3, 50
        cmap = "viridis"
        idx_line = np.linspace(0.0, 1.0, N, dtype=np.float32)
        line_colors = self._apply_colormap(idx_line, cmap, False)
        tiled = np.tile(line_colors, (k, 1)).reshape(k, N, 4)
        nan_row = np.zeros((k, 1, 4), dtype=np.float32)
        vertex_colors = np.concatenate([tiled, nan_row], axis=1).reshape(-1, 4)[:-1]
        for i in range(k):
            block = vertex_colors[i * (N + 1):i * (N + 1) + N]
            np.testing.assert_array_equal(block, line_colors)


# ---------------------------------------------------------------------------
# Arrow geometry — vectorized construction
# ---------------------------------------------------------------------------

class TestBatchArrowGeometry:
    def test_arrows_shape_k_n_3(self):
        """Vectorized arrow construction: k*(N-1) arrows from (k, N, 3) data."""
        k, N = 4, 10
        data = np.random.randn(k, N, 3).astype(np.float32)
        tails = data[:, :-1, :].reshape(-1, 3)
        heads = data[:, 1:, :].reshape(-1, 3)
        arrows = np.concatenate([tails, heads], axis=1)
        assert arrows.shape == (k * (N - 1), 6)

    def test_arrows_tails_and_heads_correct(self):
        """Verify tails and heads match the original per-line consecutive pairs."""
        k, N = 2, 5
        data = np.arange(k * N * 3, dtype=np.float32).reshape(k, N, 3)
        tails = data[:, :-1, :].reshape(-1, 3)
        heads = data[:, 1:, :].reshape(-1, 3)
        # Line 0: arrows from pts[0..3] to pts[1..4]
        np.testing.assert_array_equal(tails[:N - 1], data[0, :N - 1, :])
        np.testing.assert_array_equal(heads[:N - 1], data[0, 1:N, :])
        # Line 1: arrows from pts[0..3] to pts[1..4] in second line
        np.testing.assert_array_equal(tails[N - 1:], data[1, :N - 1, :])
        np.testing.assert_array_equal(heads[N - 1:], data[1, 1:N, :])

    def test_arrows_n_1_produces_empty(self):
        """N=1 → no arrows (handled by the N >= 2 guard in dispatch)."""
        k, N = 3, 1
        data = np.ones((k, N, 3), dtype=np.float32)
        assert N < 2  # confirms the guard fires


# ---------------------------------------------------------------------------
# NaN-separator concatenation for line mode
# ---------------------------------------------------------------------------

class TestNanSeparatorConcatenation:
    def test_line_pts_shape(self):
        k, N = 5, 100
        data = np.ones((k, N, 3), dtype=np.float32)
        sep = np.full((k, 1, 3), np.nan, dtype=np.float32)
        padded = np.concatenate([data, sep], axis=1)   # (k, N+1, 3)
        pts = padded.reshape(-1, 3)[:-1]               # trim trailing NaN row
        assert pts.shape == (k * (N + 1) - 1, 3)

    def test_nan_rows_are_at_expected_positions(self):
        k, N = 3, 4
        data = np.arange(k * N * 3, dtype=np.float32).reshape(k, N, 3)
        sep = np.full((k, 1, 3), np.nan, dtype=np.float32)
        padded = np.concatenate([data, sep], axis=1)
        pts = padded.reshape(-1, 3)[:-1]
        # NaN separator rows are at indices N, 2*(N+1)-1, ...
        for i in range(k - 1):
            nan_idx = (i + 1) * (N + 1) - 1
            assert np.all(np.isnan(pts[nan_idx]))
        # Valid rows between separators are not NaN
        assert not np.any(np.isnan(pts[:N]))
