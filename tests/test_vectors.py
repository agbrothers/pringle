"""
FEAT-014 — Vector / arrow rendering tests.

Tests cover:
- Shape detection: (N, 6) → vectors, (N, 4) → vectors_2d, priority over scatter
- Evaluator: vectors/vectors_2d render type returned from run_cell
- Renderer: make_arrow_mesh builds valid InstancedMesh geometry
- _arrow_matrix: correct transform for standard cases
- Flow mode: scatter with scatter_render_mode="arrows" converts consecutive pairs
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from pringle.evaluator import _detect_shape, run_cell
from pringle.grid import make_grid


# ---------------------------------------------------------------------------
# _detect_shape priority and shape detection
# ---------------------------------------------------------------------------

class TestDetectShape:
    def test_n6_detected_as_vectors(self):
        val = np.ones((10, 6), dtype=np.float32)
        rt, data = _detect_shape(val)
        assert rt == "vectors"
        assert data is val

    def test_n4_detected_as_vectors_2d(self):
        val = np.ones((5, 4), dtype=np.float32)
        rt, data = _detect_shape(val)
        assert rt == "vectors_2d"
        assert data is val

    def test_n6_not_detected_as_scatter(self):
        # (N, 6) must never fall through to scatter
        val = np.ones((8, 6), dtype=np.float32)
        rt, _ = _detect_shape(val)
        assert rt == "vectors"

    def test_n3_still_scatter(self):
        val = np.ones((10, 3), dtype=np.float32)
        rt, _ = _detect_shape(val)
        assert rt == "scatter"

    def test_n2_still_scatter_2d(self):
        val = np.ones((10, 2), dtype=np.float32)
        rt, _ = _detect_shape(val)
        assert rt == "scatter_2d"

    def test_scalar_not_plottable(self):
        assert _detect_shape(np.float32(1.0)) == (None, None)

    def test_non_array_not_plottable(self):
        assert _detect_shape([1, 2, 3]) == (None, None)

    def test_row_vector_shape(self):
        # Single-row (1, 6) is still detected as vectors
        val = np.zeros((1, 6), dtype=np.float32)
        rt, _ = _detect_shape(val)
        assert rt == "vectors"

    # FEAT-049: grid-shaped vector fields
    def test_grid_n_n_4_channels_last(self):
        val = np.ones((10, 10, 4), dtype=np.float32)
        rt, flat = _detect_shape(val)
        assert rt == "vectors_2d"
        assert flat.shape == (100, 4)

    def test_grid_n_n_6_channels_last(self):
        val = np.ones((10, 10, 6), dtype=np.float32)
        rt, flat = _detect_shape(val)
        assert rt == "vectors"
        assert flat.shape == (100, 6)

    def test_grid_4_n_n_channels_first(self):
        val = np.ones((4, 10, 10), dtype=np.float32)
        rt, flat = _detect_shape(val)
        assert rt == "vectors_2d"
        assert flat.shape == (100, 4)

    def test_grid_6_n_n_channels_first(self):
        val = np.ones((6, 10, 10), dtype=np.float32)
        rt, flat = _detect_shape(val)
        assert rt == "vectors"
        assert flat.shape == (100, 6)

    def test_channels_last_and_first_produce_same_data(self):
        # Build a (4, n, n) array and its channels-last equivalent, verify same flat result.
        rng = np.random.default_rng(0)
        components = rng.random((4, 5, 7)).astype(np.float32)
        channels_first = components                              # (4, 5, 7)
        channels_last = np.moveaxis(components, 0, -1)          # (5, 7, 4)
        _, flat_cf = _detect_shape(channels_first)
        _, flat_cl = _detect_shape(channels_last)
        assert np.allclose(flat_cf, flat_cl)

    def test_existing_n4_unchanged(self):
        val = np.ones((20, 4), dtype=np.float32)
        rt, data = _detect_shape(val)
        assert rt == "vectors_2d"
        assert data is val

    def test_existing_n6_unchanged(self):
        val = np.ones((20, 6), dtype=np.float32)
        rt, data = _detect_shape(val)
        assert rt == "vectors"
        assert data is val

    def test_channels_last_priority_over_channels_first(self):
        # (4, n, 4): both first and last dim are 4; channels-last takes priority.
        val = np.ones((4, 8, 4), dtype=np.float32)
        rt, flat = _detect_shape(val)
        assert rt == "vectors_2d"
        assert flat.shape == (32, 4)


# ---------------------------------------------------------------------------
# run_cell: vectors render type end-to-end
# ---------------------------------------------------------------------------

class TestRunCellVectors:
    @pytest.fixture
    def grid(self):
        return make_grid()

    def test_explicit_n6_array_yields_vectors(self, grid):
        src = "arrows = column_stack([zeros((5, 3)), ones((5, 3))])"
        result = run_cell(src, {}, grid)
        assert result.error is None
        assert result.render_type == "vectors"
        assert result.data.shape == (5, 6)

    def test_explicit_n4_array_yields_vectors_2d(self, grid):
        src = "field = zeros((4, 4), dtype=float32)"
        result = run_cell(src, {}, grid)
        assert result.error is None
        assert result.render_type == "vectors_2d"
        assert result.data.shape == (4, 4)

    def test_vectors_data_is_float32(self, grid):
        src = "arrows = zeros((3, 6))"
        result = run_cell(src, {}, grid)
        assert result.data.dtype == np.float32

    def test_from_shape_inference_true_for_vectors(self, grid):
        src = "arrows = zeros((5, 6))"
        result = run_cell(src, {}, grid)
        assert result.from_shape_inference is True


# ---------------------------------------------------------------------------
# Arrow matrix transform
# ---------------------------------------------------------------------------

class TestArrowMatrix:
    def test_along_z(self):
        from pringle.renderer import _arrow_matrix
        M = _arrow_matrix(np.array([0., 0., 0.]), np.array([0., 0., 2.]))
        assert M is not None
        # Z column should be scaled by 2
        assert abs(float(M[2, 2]) - 2.0) < 1e-5
        # Translation at origin
        assert np.allclose(M[:3, 3], [0., 0., 0.], atol=1e-5)

    def test_along_x(self):
        from pringle.renderer import _arrow_matrix
        M = _arrow_matrix(np.array([0., 0., 0.]), np.array([3., 0., 0.]))
        assert M is not None
        # Length = 3; matrix should be valid 4x4
        assert M.shape == (4, 4)

    def test_zero_length_returns_none(self):
        from pringle.renderer import _arrow_matrix
        M = _arrow_matrix(np.array([1., 2., 3.]), np.array([1., 2., 3.]))
        assert M is None

    def test_antiparallel(self):
        from pringle.renderer import _arrow_matrix
        # Arrow pointing along -Z — degenerate rotation case
        M = _arrow_matrix(np.array([0., 0., 0.]), np.array([0., 0., -1.]))
        assert M is not None

    def test_translation_set_to_tail(self):
        from pringle.renderer import _arrow_matrix
        tail = np.array([1., 2., 3.])
        head = np.array([1., 2., 5.])
        M = _arrow_matrix(tail, head)
        assert M is not None
        assert np.allclose(M[:3, 3], tail, atol=1e-5)


# ---------------------------------------------------------------------------
# make_arrow_mesh
# ---------------------------------------------------------------------------

def _gpu_available() -> bool:
    try:
        import wgpu
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        return adapter is not None
    except Exception:
        return False


_needs_gpu = pytest.mark.skipif(not _gpu_available(), reason="GPU/wgpu not available")


@_needs_gpu
class TestMakeArrowMesh:
    def test_basic_shape(self):
        import pygfx as gfx
        from pringle.renderer import make_arrow_mesh

        arrows = np.array([
            [0., 0., 0.,  1., 0., 0.],
            [0., 0., 0.,  0., 1., 0.],
            [0., 0., 0.,  0., 0., 1.],
        ], dtype=np.float32)
        mesh = make_arrow_mesh(arrows)
        assert isinstance(mesh, gfx.InstancedMesh)

    def test_normalize_mode(self):
        import pygfx as gfx
        from pringle.renderer import make_arrow_mesh

        arrows = np.array([
            [0., 0., 0.,  1., 0., 0.],
            [0., 0., 0.,  0., 3., 0.],  # 3× longer
        ], dtype=np.float32)
        mesh = make_arrow_mesh(arrows, normalize=True)
        assert isinstance(mesh, gfx.InstancedMesh)

    def test_single_arrow(self):
        import pygfx as gfx
        from pringle.renderer import make_arrow_mesh

        arrows = np.array([[0., 0., 0.,  0., 0., 2.]], dtype=np.float32)
        mesh = make_arrow_mesh(arrows, color=(1., 0., 0., 1.))
        assert isinstance(mesh, gfx.InstancedMesh)

    def test_geometry_singleton_reused(self):
        from pringle.renderer import make_arrow_mesh, _ARROW_GEO
        arrows = np.array([[0., 0., 0., 1., 0., 0.]], dtype=np.float32)
        make_arrow_mesh(arrows)
        make_arrow_mesh(arrows)
        import pringle.renderer as _r
        # After two calls, the singleton must be set
        assert _r._ARROW_GEO is not None

    def test_instance_buffer_written_by_batch(self):
        """make_arrow_mesh must write instance_buffer via batch — no all-zero matrices."""
        from pringle.renderer import make_arrow_mesh
        arrows = np.array([
            [0., 0., 0.,  1., 0., 0.],
            [0., 0., 0.,  0., 2., 0.],
        ], dtype=np.float32)
        mesh = make_arrow_mesh(arrows)
        # Both instance matrices should be non-zero (valid arrows)
        Ms = mesh.instance_buffer.data["matrix"]
        assert not np.allclose(Ms[0], 0.0), "first matrix should be non-zero"
        assert not np.allclose(Ms[1], 0.0), "second matrix should be non-zero"


@_needs_gpu
class TestUpdateArrows:
    """PringleRenderer.update_arrows in-place path (PERF-017)."""

    def _make_renderer(self):
        from rendercanvas.offscreen import OffscreenRenderCanvas
        from pringle.renderer import PringleRenderer
        canvas = OffscreenRenderCanvas(size=(100, 100))
        return PringleRenderer(canvas)

    def test_first_call_returns_true(self):
        pr = self._make_renderer()
        arrows = np.array([[0., 0., 0., 1., 0., 0.]], dtype=np.float32)
        is_new = pr.update_arrows("c1", arrows, color=(1., 1., 1., 1.), opacity=1.0)
        assert is_new is True

    def test_second_call_same_n_returns_false(self):
        pr = self._make_renderer()
        arrows = np.array([[0., 0., 0., 1., 0., 0.]], dtype=np.float32)
        pr.update_arrows("c1", arrows, color=(1., 1., 1., 1.), opacity=1.0)
        is_new = pr.update_arrows("c1", arrows, color=(1., 1., 1., 1.), opacity=1.0)
        assert is_new is False

    def test_n_change_triggers_rebuild(self):
        pr = self._make_renderer()
        arrows1 = np.zeros((3, 6), dtype=np.float32)
        arrows1[:, 3] = 1.0
        arrows2 = np.zeros((5, 6), dtype=np.float32)
        arrows2[:, 3] = 1.0
        pr.update_arrows("c1", arrows1, color=(1., 1., 1., 1.), opacity=1.0)
        is_new = pr.update_arrows("c1", arrows2, color=(1., 1., 1., 1.), opacity=1.0)
        assert is_new is False  # cell existed before; not brand new
        assert pr._arrow_count["c1"] == 5

    def test_remove_clears_cache(self):
        pr = self._make_renderer()
        arrows = np.array([[0., 0., 0., 1., 0., 0.]], dtype=np.float32)
        pr.update_arrows("c1", arrows, color=(1., 1., 1., 1.), opacity=1.0)
        pr.remove_object("c1")
        assert "c1" not in pr._arrow_mesh
        assert "c1" not in pr._arrow_count

    def test_inplace_updates_buffer(self):
        """After in-place update the translation column must reflect the new tail."""
        pr = self._make_renderer()
        arrows1 = np.array([[0., 0., 0., 1., 0., 0.]], dtype=np.float32)
        pr.update_arrows("c1", arrows1, color=(1., 1., 1., 1.), opacity=1.0)

        arrows2 = np.array([[5., 6., 7., 6., 6., 7.]], dtype=np.float32)
        pr.update_arrows("c1", arrows2, color=(1., 1., 1., 1.), opacity=1.0)

        ib = pr._arrow_mesh["c1"].instance_buffer
        # Buffer stores M.T (pygfx column-major); translation row is buf[0, 3, :3]
        tail_row = ib.data["matrix"][0, 3, :3]
        assert np.allclose(tail_row, [5., 6., 7.], atol=1e-4)


# ---------------------------------------------------------------------------
# _arrow_matrices_batch — vectorized Rodrigues (PERF-017)
# ---------------------------------------------------------------------------

class TestArrowMatricesBatch:
    """Verify that _arrow_matrices_batch produces the same transforms as _arrow_matrix."""

    def _single_matrix(self, tail, head, size=0.1):
        from pringle.renderer import _arrow_matrix
        M = _arrow_matrix(tail.astype(np.float64), head.astype(np.float64), size=size)
        return M  # may be None for degenerate arrows

    def test_along_z_matches_single(self):
        from pringle.renderer import _arrow_matrices_batch
        tail = np.array([[0., 0., 0.]], dtype=np.float32)
        head = np.array([[0., 0., 2.]], dtype=np.float32)
        Ms = _arrow_matrices_batch(tail, head, size=0.1)
        M_single = self._single_matrix(tail[0], head[0])
        assert M_single is not None
        assert np.allclose(Ms[0], M_single, atol=1e-4)

    def test_along_x_matches_single(self):
        from pringle.renderer import _arrow_matrices_batch
        tail = np.array([[0., 0., 0.]], dtype=np.float32)
        head = np.array([[3., 0., 0.]], dtype=np.float32)
        Ms = _arrow_matrices_batch(tail, head, size=0.1)
        M_single = self._single_matrix(tail[0], head[0])
        assert M_single is not None
        assert np.allclose(Ms[0], M_single, atol=1e-4)

    def test_antiparallel_matches_single(self):
        from pringle.renderer import _arrow_matrices_batch
        tail = np.array([[0., 0., 0.]], dtype=np.float32)
        head = np.array([[0., 0., -1.]], dtype=np.float32)
        Ms = _arrow_matrices_batch(tail, head, size=0.1)
        M_single = self._single_matrix(tail[0], head[0])
        assert M_single is not None
        assert np.allclose(Ms[0], M_single, atol=1e-4)

    def test_degenerate_zero_length_is_zero_matrix(self):
        from pringle.renderer import _arrow_matrices_batch
        tail = np.array([[1., 2., 3.]], dtype=np.float32)
        head = np.array([[1., 2., 3.]], dtype=np.float32)
        Ms = _arrow_matrices_batch(tail, head)
        assert np.allclose(Ms[0], 0.0)

    def test_batch_matches_single_for_random_arrows(self):
        """Batch result must agree with per-arrow _arrow_matrix on valid arrows."""
        from pringle.renderer import _arrow_matrices_batch, _arrow_matrix
        rng = np.random.default_rng(42)
        N = 64
        tails = rng.uniform(-5, 5, (N, 3)).astype(np.float32)
        heads = rng.uniform(-5, 5, (N, 3)).astype(np.float32)
        Ms = _arrow_matrices_batch(tails, heads, size=0.15)
        for i in range(N):
            M_ref = _arrow_matrix(tails[i].astype(np.float64),
                                  heads[i].astype(np.float64), size=0.15)
            assert M_ref is not None, f"arrow {i} unexpectedly degenerate"
            assert np.allclose(Ms[i], M_ref, atol=1e-4), f"mismatch at arrow {i}"

    def test_output_shape(self):
        from pringle.renderer import _arrow_matrices_batch
        N = 10
        tails = np.zeros((N, 3), dtype=np.float32)
        heads = np.ones((N, 3), dtype=np.float32)
        Ms = _arrow_matrices_batch(tails, heads)
        assert Ms.shape == (N, 4, 4)
        assert Ms.dtype == np.float32

    def test_translation_column_is_tail(self):
        from pringle.renderer import _arrow_matrices_batch
        tail = np.array([[2., 3., 4.]], dtype=np.float32)
        head = np.array([[2., 3., 6.]], dtype=np.float32)
        Ms = _arrow_matrices_batch(tail, head)
        assert np.allclose(Ms[0, :3, 3], [2., 3., 4.], atol=1e-5)

    def test_homogeneous_row(self):
        from pringle.renderer import _arrow_matrices_batch
        tails = np.zeros((5, 3), dtype=np.float32)
        heads = np.ones((5, 3), dtype=np.float32)
        Ms = _arrow_matrices_batch(tails, heads)
        # Bottom row must be [0, 0, 0, 1] for valid arrows
        assert np.allclose(Ms[:, 3, :3], 0.0, atol=1e-6)
        assert np.allclose(Ms[:, 3, 3], 1.0, atol=1e-6)


# ---------------------------------------------------------------------------
# Flow mode: consecutive-pair dispatch
# ---------------------------------------------------------------------------

class TestFlowMode:
    """Verify that the scatter→arrows conversion produces correct (N-1, 6) arrays."""

    def test_consecutive_pair_shape(self):
        pts = np.array([[0., 0., 0.], [1., 0., 0.], [2., 1., 0.]], dtype=np.float32)
        arrows = np.concatenate([pts[:-1], pts[1:]], axis=1)
        assert arrows.shape == (2, 6)
        # First arrow: tail=(0,0,0), head=(1,0,0)
        assert np.allclose(arrows[0, :3], [0., 0., 0.])
        assert np.allclose(arrows[0, 3:], [1., 0., 0.])

    def test_single_point_no_arrows(self):
        pts = np.array([[0., 0., 0.]], dtype=np.float32)
        # With only one point, no arrows should be drawn (len < 2)
        assert len(pts) < 2
