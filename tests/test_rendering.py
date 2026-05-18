"""
Rendering pipeline tests — close the loop between evaluation and GPU output.

These tests use OffscreenRenderCanvas so no display or window is required.
They are skipped automatically if the GPU / wgpu context is unavailable.

The key invariant: after evaluating an expression and adding the resulting
mesh to the renderer, the captured frame must contain non-background pixels.
Background is (0.067, 0.067, 0.067) ≈ rgb(17, 17, 17).  Any pixel that
differs by more than 10 counts in any channel is counted as "surface pixel".

Tests
-----
- make_surface_mesh produces a non-degenerate geometry
- PringleRenderer.snapshot() returns a non-black frame with a surface added
- fit_camera() positions the camera so the surface is actually visible
- Full pipeline: evaluator → mesh → renderer → non-background pixels
- Curve and scatter meshes also produce visible output
"""

from __future__ import annotations

import numpy as np
import pytest


def _gpu_available() -> bool:
    try:
        import wgpu
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        return adapter is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _gpu_available(),
    reason="GPU/wgpu context not available",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BG_RGB = np.array([int(0.067 * 255)] * 3, dtype=np.int32)  # ≈ [17, 17, 17]


def _non_bg_pixel_count(frame: np.ndarray, threshold: int = 10) -> int:
    """Count pixels whose RGB differs from the background by > threshold."""
    rgb = frame[:, :, :3].astype(np.int32)
    diff = np.abs(rgb - _BG_RGB).max(axis=2)
    return int((diff > threshold).sum())


def _make_offscreen_renderer(size=(400, 300)):
    from rendercanvas.offscreen import OffscreenRenderCanvas
    from pringle.renderer import PringleRenderer
    canvas = OffscreenRenderCanvas(size=size)
    pr = PringleRenderer(canvas)
    return pr


def _sin_cos_grid(n=32):
    from pringle.grid import GridConfig, make_grid
    g = make_grid(GridConfig(n=n))
    z = np.sin(g.x) * np.cos(g.y)
    return g, z


# ---------------------------------------------------------------------------
# Mesh geometry sanity
# ---------------------------------------------------------------------------

class TestMeshGeometry:
    def test_surface_mesh_positions_shape(self):
        from pringle.renderer import make_surface_mesh
        g, z = _sin_cos_grid()
        mesh = make_surface_mesh(g.x, g.y, z)
        n = g.x.shape[0]
        assert mesh.geometry.positions.data.shape == (n * n, 3)

    def test_surface_mesh_no_nan_positions(self):
        from pringle.renderer import make_surface_mesh
        g, z = _sin_cos_grid()
        mesh = make_surface_mesh(g.x, g.y, z)
        pos = mesh.geometry.positions.data
        assert not np.any(np.isnan(pos))

    def test_surface_mesh_z_range(self):
        from pringle.renderer import make_surface_mesh
        g, z = _sin_cos_grid()
        mesh = make_surface_mesh(g.x, g.y, z)
        pos = mesh.geometry.positions.data
        z_vals = pos[:, 2]
        assert z_vals.min() < -0.5
        assert z_vals.max() > 0.5

    def test_line_mesh_positions_shape(self):
        from pringle.renderer import make_line_mesh
        pts = np.column_stack([
            np.linspace(-5, 5, 64),
            np.sin(np.linspace(-5, 5, 64)),
            np.zeros(64),
        ]).astype(np.float32)
        line = make_line_mesh(pts)
        assert line.geometry.positions.data.shape == (64, 3)

    def test_scatter_mesh_positions_shape(self):
        from pringle.renderer import make_scatter_mesh
        pts = np.random.randn(50, 3).astype(np.float32)
        scatter = make_scatter_mesh(pts)
        assert scatter.geometry.positions.data.shape == (50, 3)

    def test_fully_clipped_mesh_does_not_crash(self):
        """All-outside constraint must not raise Buffer size cannot be zero."""
        from pringle.renderer import make_surface_mesh
        g, z = _sin_cos_grid()
        # mask that excludes every vertex
        mask = np.zeros(z.shape, dtype=bool)
        mesh = make_surface_mesh(g.x, g.y, z, constraint_mask=mask, z_raw=z)
        assert isinstance(mesh, __import__("pygfx").Mesh)

    def test_flat_zero_surface_does_not_crash(self):
        """z = 0 everywhere (e.g. slider at zero) must produce a valid mesh."""
        from pringle.renderer import make_surface_mesh
        from pringle.grid import GridConfig, make_grid
        g = make_grid(GridConfig(n=32))
        z = np.zeros_like(g.x, dtype=np.float32)
        mesh = make_surface_mesh(g.x, g.y, z)
        assert isinstance(mesh, __import__("pygfx").Mesh)


# ---------------------------------------------------------------------------
# Offscreen rendering
# ---------------------------------------------------------------------------

class TestOffscreenRender:
    def test_snapshot_returns_array(self):
        pr = _make_offscreen_renderer()
        frame = pr.snapshot()
        assert isinstance(frame, np.ndarray)
        assert frame.ndim == 3
        assert frame.shape[2] == 4  # RGBA

    def test_empty_scene_is_background_color(self):
        pr = _make_offscreen_renderer()
        # Disable overlay so we're checking truly empty user-content scene
        pr.set_axes_visible(False)
        pr.set_bbox_visible(False)
        frame = pr.snapshot()
        non_bg = _non_bg_pixel_count(frame)
        assert non_bg < 500, f"Empty scene has too many non-bg pixels: {non_bg}"

    def test_surface_produces_non_background_pixels(self):
        from pringle.renderer import make_surface_mesh
        pr = _make_offscreen_renderer()
        g, z = _sin_cos_grid()
        mesh = make_surface_mesh(g.x, g.y, z)
        pr.add_object("surf", mesh)
        pr.fit_camera()
        frame = pr.snapshot()
        non_bg = _non_bg_pixel_count(frame)
        assert non_bg > 500, (
            f"Surface mesh rendered but only {non_bg} non-background pixels found. "
            "The surface is likely invisible — check camera position or mesh normals."
        )

    def test_fit_camera_makes_surface_visible(self):
        """fit_camera() must position the camera to see the bounding box."""
        from pringle.renderer import make_surface_mesh
        pr = _make_offscreen_renderer()
        g, z = _sin_cos_grid()
        pr.add_object("surf", make_surface_mesh(g.x, g.y, z))

        pr.fit_camera()
        frame_fitted = pr.snapshot()

        non_bg = _non_bg_pixel_count(frame_fitted)
        assert non_bg > 500, (
            f"fit_camera() did not produce a visible surface ({non_bg} non-bg pixels). "
            "Camera may not be framing the scene correctly."
        )

    def test_remove_object_clears_pixels(self):
        from pringle.renderer import make_surface_mesh
        pr = _make_offscreen_renderer()
        pr.set_axes_visible(False)
        pr.set_bbox_visible(False)
        g, z = _sin_cos_grid()
        pr.add_object("surf", make_surface_mesh(g.x, g.y, z))
        pr.fit_camera()
        _ = pr.snapshot()  # with surface

        pr.remove_object("surf")
        frame = pr.snapshot()
        non_bg = _non_bg_pixel_count(frame)
        assert non_bg < 500, f"Object removed but {non_bg} non-bg pixels remain"


# ---------------------------------------------------------------------------
# Full evaluator → renderer pipeline
# ---------------------------------------------------------------------------

class TestEvaluatorToRendererPipeline:
    def test_equation_cell_produces_visible_surface(self):
        from pringle.grid import GridConfig, make_grid
        from pringle.evaluator import run_cell
        from pringle.renderer import PringleRenderer, make_surface_mesh
        from rendercanvas.offscreen import OffscreenRenderCanvas

        grid = make_grid(GridConfig(n=32))
        result = run_cell("z = sin(x) * cos(y)", {}, grid)
        assert result.render_type == "surface", f"Expected surface, got {result.render_type!r}"
        assert result.error is None, f"Evaluation error: {result.error}"

        canvas = OffscreenRenderCanvas(size=(400, 300))
        pr = PringleRenderer(canvas)
        mesh = make_surface_mesh(result.x, result.y, result.data)
        pr.add_object("cell-1", mesh)
        pr.fit_camera()

        frame = pr.snapshot()
        non_bg = _non_bg_pixel_count(frame)
        assert non_bg > 500, (
            f"Evaluated 'z = sin(x)*cos(y)' but only {non_bg} non-background pixels "
            "rendered. The evaluation→mesh→GPU pipeline is broken."
        )

    def test_curve_cell_produces_visible_line(self):
        from pringle.grid import GridConfig, make_grid
        from pringle.evaluator import run_cell
        from pringle.renderer import PringleRenderer, make_line_mesh
        from rendercanvas.offscreen import OffscreenRenderCanvas
        import numpy as np

        grid = make_grid(GridConfig(n=64))
        # f(x) = sin(x) is the curve form; y = sin(x) with 2D x gives surface_y
        result = run_cell("f(x) = sin(x)", {}, grid)
        assert result.render_type == "curve", f"Unexpected render_type: {result.render_type!r}"

        pts = np.column_stack([
            grid.x1d,
            result.data,
            np.zeros(len(result.data), dtype=np.float32),
        ])
        canvas = OffscreenRenderCanvas(size=(400, 300))
        pr = PringleRenderer(canvas)
        pr.add_object("curve", make_line_mesh(pts, thickness=3.0))
        pr.fit_camera()

        frame = pr.snapshot()
        non_bg = _non_bg_pixel_count(frame)
        assert non_bg > 50, (
            f"Curve 'y = sin(x)' produced only {non_bg} non-background pixels."
        )

    def test_constraint_masks_surface(self):
        """A constrained surface should cover less area than an unconstrained one."""
        from pringle.grid import GridConfig, make_grid
        from pringle.evaluator import run_cell
        from pringle.renderer import PringleRenderer, make_surface_mesh
        from rendercanvas.offscreen import OffscreenRenderCanvas

        grid = make_grid(GridConfig(n=32))

        def _pixel_count(constraint_exprs):
            result = run_cell("z = sin(x) * cos(y)", {}, grid,
                              constraint_exprs=constraint_exprs)
            canvas = OffscreenRenderCanvas(size=(400, 300))
            pr = PringleRenderer(canvas)
            pr.add_object("surf", make_surface_mesh(result.x, result.y, result.data))
            pr.fit_camera()
            return _non_bg_pixel_count(pr.snapshot())

        full = _pixel_count([])
        half = _pixel_count(["x > 0"])
        assert full > 500
        # Constraining to x > 0 should produce fewer pixels than full surface.
        # Camera foreshortening means it won't be exactly 50%, so allow up to 90%.
        assert half < full * 0.90, (
            f"Constraint 'x > 0' should reduce visible area: full={full}, half={half}"
        )


# ---------------------------------------------------------------------------
# Smooth constraint boundary clipping
# ---------------------------------------------------------------------------

class TestConstraintBoundaryClipping:
    def test_clip_mesh_produces_non_nan_positions(self):
        """All vertex positions in a clipped mesh must be finite."""
        from pringle.renderer import make_surface_mesh
        from pringle.evaluator import run_cell
        from pringle.grid import GridConfig, make_grid

        grid = make_grid(GridConfig(n=32))
        result = run_cell("z = x**2 - y**2", {}, grid,
                          constraint_exprs=["x**2 + y**2 < 1"])
        assert result.constraint_mask is not None
        assert result.data_unmasked is not None

        mesh = make_surface_mesh(
            result.x, result.y, result.data,
            constraint_mask=result.constraint_mask,
            z_raw=result.data_unmasked,
        )
        pos = mesh.geometry.positions.data
        assert np.all(np.isfinite(pos)), "Clipped mesh has NaN/Inf vertex positions"

    def test_clip_mesh_fewer_triangles_than_full(self):
        """A constrained mesh should have fewer triangles than an unconstrained one."""
        from pringle.renderer import make_surface_mesh, _grid_indices
        from pringle.evaluator import run_cell
        from pringle.grid import GridConfig, make_grid

        grid = make_grid(GridConfig(n=32))
        result = run_cell("z = x**2 - y**2", {}, grid,
                          constraint_exprs=["x**2 + y**2 < 1"])
        mesh = make_surface_mesh(
            result.x, result.y, result.data,
            constraint_mask=result.constraint_mask,
            z_raw=result.data_unmasked,
        )
        n = grid.x.shape[0]
        full_tris = (n - 1) * (n - 1) * 2
        clipped_tris = mesh.geometry.indices.data.shape[0]
        assert clipped_tris < full_tris, \
            f"Clipped mesh has {clipped_tris} triangles, expected < {full_tris}"

    def test_clip_produces_smoother_edges_than_nan_masking(self):
        """
        The clipped mesh should render with a smoother boundary pixel profile
        than the NaN-masked mesh at the same resolution.

        Measure: count boundary pixels (pixels adjacent to a background pixel)
        — smooth edges have fewer boundary pixels than staircase edges.
        """
        from rendercanvas.offscreen import OffscreenRenderCanvas
        from pringle.renderer import PringleRenderer, make_surface_mesh
        from pringle.evaluator import run_cell
        from pringle.grid import GridConfig, make_grid
        import numpy as np

        grid = make_grid(GridConfig(n=32))
        result = run_cell("z = x**2 - y**2", {}, grid,
                          constraint_exprs=["x**2 + y**2 < 1"])

        def render_mesh(mesh):
            canvas = OffscreenRenderCanvas(size=(400, 300))
            pr = PringleRenderer(canvas)
            pr.add_object("surf", mesh)
            pr.fit_camera()
            return pr.snapshot()

        # NaN-masked mesh (legacy approach)
        nan_mesh = make_surface_mesh(result.x, result.y, result.data)
        nan_frame = render_mesh(nan_mesh)

        # Clipped mesh (smooth boundary)
        clip_mesh = make_surface_mesh(
            result.x, result.y, result.data,
            constraint_mask=result.constraint_mask,
            z_raw=result.data_unmasked,
        )
        clip_frame = render_mesh(clip_mesh)

        def boundary_pixels(frame, threshold=10):
            """Count pixels that neighbor a background pixel."""
            rgb = frame[:, :, :3].astype(np.int32)
            bg = np.array([int(0.067 * 255)] * 3)
            is_bg = (np.abs(rgb - bg).max(axis=2) <= threshold)
            is_surface = ~is_bg
            # erode surface: find surface pixels with any bg neighbor
            from numpy.lib.stride_tricks import sliding_window_view
            padded = np.pad(is_bg.astype(np.uint8), 1, mode='edge')
            kernel = sliding_window_view(padded, (3, 3))
            has_bg_neighbor = kernel.reshape(*is_surface.shape, -1).max(axis=2).astype(bool)
            return int((is_surface & has_bg_neighbor).sum())

        nan_boundary = boundary_pixels(nan_frame)
        clip_boundary = boundary_pixels(clip_frame)

        assert clip_boundary <= nan_boundary, (
            f"Clipped mesh boundary ({clip_boundary} px) should be ≤ "
            f"NaN-masked boundary ({nan_boundary} px) — clipping should smooth edges"
        )
