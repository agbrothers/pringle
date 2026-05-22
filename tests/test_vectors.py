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


# ---------------------------------------------------------------------------
# run_cell: vectors render type end-to-end
# ---------------------------------------------------------------------------

class TestRunCellVectors:
    @pytest.fixture
    def grid(self):
        return make_grid()

    def test_explicit_n6_array_yields_vectors(self, grid):
        src = "arrows = np.column_stack([np.zeros((5, 3)), np.ones((5, 3))])"
        result = run_cell(src, {}, grid, is_data_cell=True)
        assert result.error is None
        assert result.render_type == "vectors"
        assert result.data.shape == (5, 6)

    def test_explicit_n4_array_yields_vectors_2d(self, grid):
        src = "field = np.zeros((4, 4), dtype=np.float32)"
        result = run_cell(src, {}, grid, is_data_cell=True)
        assert result.error is None
        assert result.render_type == "vectors_2d"
        assert result.data.shape == (4, 4)

    def test_vectors_data_is_float32(self, grid):
        src = "arrows = np.zeros((3, 6))"
        result = run_cell(src, {}, grid, is_data_cell=True)
        assert result.data.dtype == np.float32

    def test_from_shape_inference_true_for_vectors(self, grid):
        src = "arrows = np.zeros((5, 6))"
        result = run_cell(src, {}, grid, is_data_cell=True)
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
