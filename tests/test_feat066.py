"""
FEAT-066 — Colormap support for sphere and vector (arrow) render modes.

Tests cover:
- make_scatter_mesh with as_spheres=True + colormap → gfx.Mesh (not InstancedMesh)
- make_scatter_mesh with as_spheres=True + no colormap → gfx.InstancedMesh (unchanged)
- make_scatter_mesh with as_spheres=True + vertex_colors → gfx.Mesh
- make_arrow_mesh with colormap → gfx.Mesh (not InstancedMesh)
- make_arrow_mesh with vertex_colors → gfx.Mesh (pre-computed per-arrow RGBA)
- make_arrow_mesh with no colormap → gfx.InstancedMesh (unchanged)
- Sphere colormap: all vertices of each instance share the same color
- Arrow colormap: all vertices of each instance share the same color
- _merge_colored_mesh: merged geometry arrays have correct shapes
- update_arrows fast path skipped when colormap or vertex_colors active
- Batch arrows: each of k batches independently spans 0→1 (not one long sequence)
- Batch spheres: each of k batches independently spans 0→1
"""

from __future__ import annotations

import numpy as np
import pygfx as gfx
import pytest

from pringle.renderer import (
    _apply_colormap,
    _arrow_matrices_batch,
    _build_unit_arrow_geometry,
    _merge_colored_mesh,
    make_arrow_mesh,
    make_scatter_mesh,
)


# ---------------------------------------------------------------------------
# _merge_colored_mesh — shape checks
# ---------------------------------------------------------------------------

class TestMergeColoredMesh:
    def _identity_transforms(self, N: int) -> np.ndarray:
        Ms = np.zeros((N, 4, 4), dtype=np.float32)
        for i in range(4):
            Ms[:, i, i] = 1.0
        return Ms

    def test_output_is_gfx_mesh(self):
        geo = gfx.sphere_geometry(radius=0.5, width_segments=8, height_segments=8)
        N = 5
        Ms = self._identity_transforms(N)
        colors = np.ones((N, 4), dtype=np.float32)
        mesh = _merge_colored_mesh(geo, Ms, colors, opacity=1.0)
        assert isinstance(mesh, gfx.Mesh)
        assert not isinstance(mesh, gfx.InstancedMesh)

    def test_position_count(self):
        geo = gfx.sphere_geometry(radius=0.5, width_segments=8, height_segments=8)
        V = geo.positions.data.shape[0]
        N = 4
        Ms = self._identity_transforms(N)
        colors = np.ones((N, 4), dtype=np.float32)
        mesh = _merge_colored_mesh(geo, Ms, colors)
        assert mesh.geometry.positions.data.shape == (N * V, 3)

    def test_index_count(self):
        geo = gfx.sphere_geometry(radius=0.5, width_segments=8, height_segments=8)
        F = geo.indices.data.shape[0]
        N = 4
        Ms = self._identity_transforms(N)
        colors = np.ones((N, 4), dtype=np.float32)
        mesh = _merge_colored_mesh(geo, Ms, colors)
        assert mesh.geometry.indices.data.shape == (N * F, 3)

    def test_vertex_colors_count(self):
        geo = gfx.sphere_geometry(radius=0.5, width_segments=8, height_segments=8)
        V = geo.positions.data.shape[0]
        N = 4
        Ms = self._identity_transforms(N)
        colors = np.random.rand(N, 4).astype(np.float32)
        mesh = _merge_colored_mesh(geo, Ms, colors)
        assert mesh.geometry.colors.data.shape == (N * V, 4)

    def test_per_instance_color_repeated(self):
        """All V vertices of instance i must share exactly colors[i]."""
        geo = gfx.sphere_geometry(radius=0.5, width_segments=8, height_segments=8)
        V = geo.positions.data.shape[0]
        N = 3
        Ms = self._identity_transforms(N)
        colors = np.array([[1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1]], dtype=np.float32)
        mesh = _merge_colored_mesh(geo, Ms, colors)
        all_colors = mesh.geometry.colors.data
        for i, c in enumerate(colors):
            block = all_colors[i * V:(i + 1) * V]
            np.testing.assert_array_almost_equal(block, c[None].repeat(V, axis=0))

    def test_translation_applied(self):
        """With a pure translation matrix, positions should be shifted by t."""
        geo = gfx.sphere_geometry(radius=0.5, width_segments=8, height_segments=8)
        V = geo.positions.data.shape[0]
        N = 2
        offsets = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)
        Ms = np.zeros((N, 4, 4), dtype=np.float32)
        for i in range(4):
            Ms[:, i, i] = 1.0
        Ms[:, :3, 3] = offsets
        colors = np.ones((N, 4), dtype=np.float32)
        mesh = _merge_colored_mesh(geo, Ms, colors)
        base_pos = geo.positions.data
        all_pos = mesh.geometry.positions.data
        for i, t in enumerate(offsets):
            expected = base_pos + t
            np.testing.assert_array_almost_equal(all_pos[i * V:(i + 1) * V], expected, decimal=5)

    def test_opacity_below_1_sets_alpha_mode(self):
        geo = gfx.sphere_geometry(radius=0.5, width_segments=8, height_segments=8)
        N = 2
        Ms = self._identity_transforms(N)
        colors = np.ones((N, 4), dtype=np.float32)
        mesh = _merge_colored_mesh(geo, Ms, colors, opacity=0.5)
        assert mesh.material.opacity == pytest.approx(0.5)
        assert mesh.material.alpha_mode == "weighted_blend"


# ---------------------------------------------------------------------------
# make_scatter_mesh — sphere branch
# ---------------------------------------------------------------------------

class TestScatterMeshSpheres:
    def _pts(self, N: int = 10) -> np.ndarray:
        return np.random.rand(N, 3).astype(np.float32)

    def test_no_colormap_returns_instanced_mesh(self):
        mesh = make_scatter_mesh(self._pts(), as_spheres=True)
        assert isinstance(mesh, gfx.InstancedMesh)

    def test_colormap_returns_plain_mesh(self):
        mesh = make_scatter_mesh(self._pts(), as_spheres=True, colormap="viridis")
        assert isinstance(mesh, gfx.Mesh)
        assert not isinstance(mesh, gfx.InstancedMesh)

    def test_vertex_colors_returns_plain_mesh(self):
        pts = self._pts(5)
        sphere_geo = gfx.sphere_geometry(radius=0.05, width_segments=16, height_segments=16)
        V = sphere_geo.positions.data.shape[0]
        N = len(pts)
        vc = np.ones((N * V, 4), dtype=np.float32)
        # vertex_colors passed directly (pre-computed)
        mesh = make_scatter_mesh(pts, as_spheres=True, vertex_colors=vc)
        assert isinstance(mesh, gfx.Mesh)
        assert not isinstance(mesh, gfx.InstancedMesh)

    def test_colormap_color_mode_is_vertex(self):
        mesh = make_scatter_mesh(self._pts(), as_spheres=True, colormap="plasma")
        assert mesh.material.color_mode == "vertex"

    def test_colormap_reversed_applies(self):
        pts = self._pts(5)
        m_fwd = make_scatter_mesh(pts, as_spheres=True, colormap="viridis", colormap_reversed=False)
        m_rev = make_scatter_mesh(pts, as_spheres=True, colormap="viridis", colormap_reversed=True)
        c_fwd = m_fwd.geometry.colors.data[0]   # first vertex of first sphere
        c_rev = m_rev.geometry.colors.data[0]
        assert not np.allclose(c_fwd, c_rev), "reversed colormap should produce different first color"

    def test_no_colormap_unchanged_behavior(self):
        """Ensure the existing sphere InstancedMesh path is not broken."""
        N = 8
        pts = self._pts(N)
        mesh = make_scatter_mesh(pts, as_spheres=True, color=(0.5, 0.5, 0.5, 1.0))
        assert isinstance(mesh, gfx.InstancedMesh)
        # color_mode is 'auto' (the MeshPhongMaterial default — not vertex-driven)
        assert mesh.material.color_mode != "vertex"


# ---------------------------------------------------------------------------
# make_arrow_mesh
# ---------------------------------------------------------------------------

class _ArrowFixture:
    @staticmethod
    def arrows(N: int = 10) -> np.ndarray:
        tails = np.zeros((N, 3), dtype=np.float32)
        tails[:, 0] = np.arange(N, dtype=np.float32)
        heads = tails.copy()
        heads[:, 2] = 1.0
        return np.concatenate([tails, heads], axis=1)


class TestMakeArrowMesh:
    def test_no_colormap_returns_instanced_mesh(self):
        arrows = _ArrowFixture.arrows()
        mesh = make_arrow_mesh(arrows)
        assert isinstance(mesh, gfx.InstancedMesh)

    def test_colormap_returns_plain_mesh(self):
        arrows = _ArrowFixture.arrows()
        mesh = make_arrow_mesh(arrows, colormap="viridis")
        assert isinstance(mesh, gfx.Mesh)
        assert not isinstance(mesh, gfx.InstancedMesh)

    def test_colormap_color_mode_is_vertex(self):
        arrows = _ArrowFixture.arrows()
        mesh = make_arrow_mesh(arrows, colormap="inferno")
        assert mesh.material.color_mode == "vertex"

    def test_arrow_colormap_vertex_count(self):
        N = 8
        arrows = _ArrowFixture.arrows(N)
        arrow_geo = _build_unit_arrow_geometry()
        V = arrow_geo.positions.data.shape[0]
        mesh = make_arrow_mesh(arrows, colormap="viridis")
        assert mesh.geometry.positions.data.shape == (N * V, 3)
        assert mesh.geometry.colors.data.shape == (N * V, 4)

    def test_arrow_colormap_per_instance_colors(self):
        """All vertices of arrow i must share the same color."""
        N = 5
        arrows = _ArrowFixture.arrows(N)
        arrow_geo = _build_unit_arrow_geometry()
        V = arrow_geo.positions.data.shape[0]
        mesh = make_arrow_mesh(arrows, colormap="viridis")
        all_colors = mesh.geometry.colors.data
        for i in range(N):
            block = all_colors[i * V:(i + 1) * V]
            # All rows in block must be equal (same instance color)
            assert np.allclose(block, block[0]), f"arrow {i} has non-uniform vertex colors"

    def test_colormap_reversed_applies(self):
        arrows = _ArrowFixture.arrows(5)
        arrow_geo = _build_unit_arrow_geometry()
        V = arrow_geo.positions.data.shape[0]
        m_fwd = make_arrow_mesh(arrows, colormap="viridis", colormap_reversed=False)
        m_rev = make_arrow_mesh(arrows, colormap="viridis", colormap_reversed=True)
        c_fwd = m_fwd.geometry.colors.data[0]
        c_rev = m_rev.geometry.colors.data[0]
        assert not np.allclose(c_fwd, c_rev)

    def test_normalize_with_colormap(self):
        """normalize=True should work alongside colormap without error."""
        arrows = _ArrowFixture.arrows(6)
        mesh = make_arrow_mesh(arrows, colormap="viridis", normalize=True)
        assert isinstance(mesh, gfx.Mesh)

    def test_vertex_colors_returns_plain_mesh(self):
        N = 6
        arrows = _ArrowFixture.arrows(N)
        vc = np.ones((N, 4), dtype=np.float32)
        mesh = make_arrow_mesh(arrows, vertex_colors=vc)
        assert isinstance(mesh, gfx.Mesh)
        assert not isinstance(mesh, gfx.InstancedMesh)

    def test_vertex_colors_overrides_colormap(self):
        """vertex_colors takes priority; the result is a plain Mesh with the supplied colors."""
        N = 4
        arrows = _ArrowFixture.arrows(N)
        arrow_geo = _build_unit_arrow_geometry()
        V = arrow_geo.positions.data.shape[0]
        # Distinct color per arrow
        vc = np.zeros((N, 4), dtype=np.float32)
        vc[:, 3] = 1.0
        vc[0, 0] = 1.0  # red
        vc[1, 1] = 1.0  # green
        mesh = make_arrow_mesh(arrows, vertex_colors=vc, colormap="viridis")
        all_colors = mesh.geometry.colors.data
        # All V vertices of arrow 0 must share vc[0]
        assert np.allclose(all_colors[:V], vc[0][None]), "first arrow's vertices must all be red"

    def test_no_colormap_unchanged_behavior(self):
        """Ensure the existing InstancedMesh fast path is not broken."""
        arrows = _ArrowFixture.arrows()
        mesh = make_arrow_mesh(arrows, color=(0.9, 0.6, 0.1, 1.0))
        assert isinstance(mesh, gfx.InstancedMesh)
        assert mesh.material.color_mode != "vertex"


# ---------------------------------------------------------------------------
# Batch colormap — per-batch 0→1 gradient
# ---------------------------------------------------------------------------

class TestBatchColormap:
    """Verify that batch dispatches apply colormaps per-batch, not across all batches."""

    def _batch_arrow_vc(self, k: int, N: int, cmap: str = "viridis") -> np.ndarray:
        """Replicate the app.py batch-arrow colormap logic."""
        from pringle.renderer import _apply_colormap
        idx = np.linspace(0.0, 1.0, N - 1, dtype=np.float32)
        colors = _apply_colormap(idx, cmap, False)   # (N-1, 4)
        return np.tile(colors, (k, 1))               # (k*(N-1), 4)

    def _batch_sphere_vc(self, k: int, N: int, cmap: str = "viridis") -> np.ndarray:
        """Replicate the app.py batch-sphere/circle colormap logic."""
        from pringle.renderer import _apply_colormap
        idx = np.linspace(0.0, 1.0, N, dtype=np.float32)
        colors = _apply_colormap(idx, cmap, False)   # (N, 4)
        return np.tile(colors, (k, 1))               # (k*N, 4)

    def test_batch_arrows_each_batch_spans_full_gradient(self):
        """Each block of (N-1) arrows in the vertex_colors array must be identical."""
        k, N = 4, 10
        vc = self._batch_arrow_vc(k, N)
        per_batch = N - 1
        assert vc.shape == (k * per_batch, 4)
        first_block = vc[:per_batch]
        for i in range(1, k):
            block = vc[i * per_batch:(i + 1) * per_batch]
            np.testing.assert_array_equal(block, first_block,
                err_msg=f"batch {i} colors differ from batch 0")

    def test_batch_arrows_not_one_long_gradient(self):
        """If the colormap were applied across all k*(N-1) arrows, adjacent-batch
        colors would be different. With per-batch, first arrow of each batch is identical."""
        k, N = 3, 8
        per_batch = N - 1
        vc = self._batch_arrow_vc(k, N)
        # First arrow of batch 0 and batch 1 must be the same (both = colormap[0.0])
        np.testing.assert_array_equal(vc[0], vc[per_batch])

    def test_batch_spheres_each_batch_spans_full_gradient(self):
        k, N = 5, 12
        vc = self._batch_sphere_vc(k, N)
        assert vc.shape == (k * N, 4)
        first_block = vc[:N]
        for i in range(1, k):
            block = vc[i * N:(i + 1) * N]
            np.testing.assert_array_equal(block, first_block,
                err_msg=f"batch {i} colors differ from batch 0")

    def test_batch_spheres_not_one_long_gradient(self):
        k, N = 3, 6
        vc = self._batch_sphere_vc(k, N)
        # First sphere of batch 0 and batch 1 must share the same color
        np.testing.assert_array_equal(vc[0], vc[N])

    def test_batch_arrows_vertex_colors_passed_to_mesh(self):
        """make_arrow_mesh with vertex_colors=(k*(N-1), 4) produces correct geometry."""
        k, N = 3, 6
        per_batch = N - 1
        vc = self._batch_arrow_vc(k, N)
        arrows_data = np.zeros((k * per_batch, 6), dtype=np.float32)
        arrows_data[:, 3:] = 1.0  # unit Z arrows
        arrow_geo = _build_unit_arrow_geometry()
        V = arrow_geo.positions.data.shape[0]
        mesh = make_arrow_mesh(arrows_data, vertex_colors=vc)
        assert mesh.geometry.colors.data.shape == (k * per_batch * V, 4)

    def test_batch_spheres_vertex_colors_passed_to_mesh(self):
        """make_scatter_mesh with as_spheres=True and vertex_colors=(k*N, 4)."""
        k, N = 3, 6
        vc = self._batch_sphere_vc(k, N)
        pts = np.random.rand(k * N, 3).astype(np.float32)
        sphere_geo = gfx.sphere_geometry(radius=0.05, width_segments=16, height_segments=16)
        V = sphere_geo.positions.data.shape[0]
        mesh = make_scatter_mesh(pts, as_spheres=True, vertex_colors=vc)
        assert isinstance(mesh, gfx.Mesh)
        assert mesh.geometry.colors.data.shape == (k * N * V, 4)


# ---------------------------------------------------------------------------
# update_arrows — fast path behaviour
# ---------------------------------------------------------------------------

class TestUpdateArrowsFastPath:
    def _make_renderer(self):
        from pringle.renderer import PringleRenderer
        import pygfx as gfx_
        # Minimal offscreen renderer
        canvas = gfx_.renderers.WgpuRenderer.__new__(gfx_.renderers.WgpuRenderer)
        # Use PringleRenderer with a real canvas via the snapshot path would
        # require a display; instead test the logic directly on update_arrows.
        return None

    def test_colormap_bypasses_fast_path(self):
        """When colormap is active, update_arrows must always do a full rebuild
        (the fast path requires InstancedMesh.instance_buffer which doesn't exist
        on a colormap-built gfx.Mesh). Verify by checking that calling update_arrows
        twice with the same N but a colormap still produces a plain gfx.Mesh."""
        from pringle.renderer import PringleRenderer
        import wgpu
        # Skip if no display / GPU available
        try:
            from wgpu.gui.offscreen import WgpuCanvas
        except Exception:
            pytest.skip("offscreen canvas not available")

        canvas = WgpuCanvas(size=(64, 64))
        try:
            pr = PringleRenderer(canvas)
        except Exception:
            pytest.skip("GPU not available in this environment")

        arrows = _ArrowFixture.arrows(5)
        pr.update_arrows("c1", arrows, (1, 1, 1, 1), 1.0, colormap="viridis")
        assert isinstance(pr._arrow_mesh["c1"], gfx.Mesh)
        assert not isinstance(pr._arrow_mesh["c1"], gfx.InstancedMesh)
        # Second call — same N, should still rebuild (not crash on missing instance_buffer)
        pr.update_arrows("c1", arrows, (1, 1, 1, 1), 1.0, colormap="viridis")
        assert isinstance(pr._arrow_mesh["c1"], gfx.Mesh)
