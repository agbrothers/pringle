"""
Core GPU renderer — builds and manages the pygfx scene.

Responsibilities:
- Convert numpy surface/curve/scatter arrays to pygfx objects
- Manage the scene graph (add / remove objects per cell)
- Expose snapshot() for offscreen PNG capture (testing)
- Expose run(canvas) for interactive rendering

Design note: normals for surface meshes are computed here via
finite differences on the (x, y, z) grids. pygfx's MeshPhongMaterial
requires per-vertex normals for smooth shading; without them the
renderer falls back to face normals (faceted appearance).
"""

from __future__ import annotations

import numpy as np
import pygfx as gfx


# ---------------------------------------------------------------------------
# Mesh construction helpers
# ---------------------------------------------------------------------------

def _grid_normals(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """
    Compute per-vertex normals for a height-field surface z = f(x, y).

    Uses central finite differences on x and y, then cross-products to get
    the surface normal at each vertex.  Output shape: (N*M, 3) float32.
    """
    # Gradient via central differences (padded edges use one-sided diff)
    dz_dx = np.gradient(z, x[0, :], axis=1)  # ∂z/∂x
    dz_dy = np.gradient(z, y[:, 0], axis=0)  # ∂z/∂y

    # Tangent vectors: T_x = (1, 0, dz/dx),  T_y = (0, 1, dz/dy)
    # Normal = T_x × T_y = (-dz/dx, -dz/dy, 1), then normalized
    nx = -dz_dx
    ny = -dz_dy
    nz = np.ones_like(z)
    length = np.sqrt(nx**2 + ny**2 + nz**2)
    nx /= length;  ny /= length;  nz /= length

    return np.stack([nx.ravel(), ny.ravel(), nz.ravel()], axis=1).astype(np.float32)


def _grid_indices(rows: int, cols: int) -> np.ndarray:
    """
    Build triangle indices for a rows×cols grid of vertices.
    Returns shape (2*(rows-1)*(cols-1), 3) int32.
    """
    triangles = []
    for r in range(rows - 1):
        for c in range(cols - 1):
            i = r * cols + c
            triangles.append([i,       i + 1,     i + cols])
            triangles.append([i + 1,   i + cols + 1, i + cols])
    return np.array(triangles, dtype=np.int32)


def make_surface_mesh(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    color: tuple = (0.2, 0.4, 0.9, 1.0),
) -> gfx.Mesh:
    """
    Build a pygfx Mesh from a height-field surface.

    Parameters
    ----------
    x, y : (N, M) float arrays — spatial coordinate grids (from np.meshgrid)
    z    : (N, M) float array  — surface height values; NaN → degenerate triangle (skipped)
    color: RGBA tuple in [0, 1]

    Returns a gfx.Mesh ready to be added to a scene.
    """
    rows, cols = z.shape
    positions = np.stack([x.ravel(), y.ravel(), z.ravel()], axis=1).astype(np.float32)
    indices   = _grid_indices(rows, cols)
    normals   = _grid_normals(x, y, z)

    geo = gfx.Geometry(positions=positions, indices=indices, normals=normals)
    mat = gfx.MeshPhongMaterial(color=color, side="both")
    return gfx.Mesh(geo, mat)


def make_line_mesh(
    points: np.ndarray,
    color: tuple = (0.9, 0.4, 0.2, 1.0),
    thickness: float = 2.0,
) -> gfx.Line:
    """
    Build a pygfx Line from an (N, 3) or (N, 2) array of points.
    2D input is promoted to 3D by setting z=0.
    """
    pts = np.asarray(points, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] not in (2, 3):
        raise ValueError(f"points must be (N, 2) or (N, 3), got {pts.shape}")
    if pts.shape[1] == 2:
        pts = np.column_stack([pts, np.zeros(len(pts), dtype=np.float32)])

    geo = gfx.Geometry(positions=pts)
    mat = gfx.LineMaterial(color=color, thickness=thickness)
    return gfx.Line(geo, mat)


def make_scatter_mesh(
    points: np.ndarray,
    color: tuple = (0.9, 0.6, 0.1, 1.0),
    size: float = 6.0,
) -> gfx.Points:
    """
    Build a pygfx Points object from an (N, 3) or (N, 2) array.
    """
    pts = np.asarray(points, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] not in (2, 3):
        raise ValueError(f"points must be (N, 2) or (N, 3), got {pts.shape}")
    if pts.shape[1] == 2:
        pts = np.column_stack([pts, np.zeros(len(pts), dtype=np.float32)])

    geo = gfx.Geometry(positions=pts)
    mat = gfx.PointsMaterial(color=color, size=size)
    return gfx.Points(geo, mat)


# ---------------------------------------------------------------------------
# Scene manager
# ---------------------------------------------------------------------------

class PringleRenderer:
    """
    Manages the pygfx scene, camera, lighting, and renderer.

    Usage (interactive):
        from rendercanvas.auto import RenderCanvas
        canvas = RenderCanvas(size=(1200, 800), title="pringle")
        pr = PringleRenderer(canvas)
        pr.add_object("cell-1", make_surface_mesh(x, y, z))
        canvas.run()

    Usage (offscreen / testing):
        from rendercanvas.offscreen import OffscreenRenderCanvas
        canvas = OffscreenRenderCanvas(size=(800, 600))
        pr = PringleRenderer(canvas)
        pr.add_object("cell-1", make_surface_mesh(x, y, z))
        pr.render()
        img = pr.snapshot()  # (H, W, 4) uint8
    """

    def __init__(self, canvas):
        self._canvas = canvas
        self._renderer = gfx.WgpuRenderer(canvas)
        self._scene = gfx.Scene()
        self._objects: dict[str, gfx.WorldObject] = {}

        # Lighting
        self._scene.add(gfx.AmbientLight(intensity=0.4))
        sun = gfx.DirectionalLight(intensity=1.5)
        sun.local.position = (5, 8, 10)
        self._scene.add(sun)

        # Background
        bg = gfx.Background(None, gfx.BackgroundMaterial((0.95, 0.95, 0.95)))
        self._scene.add(bg)

        # Camera — PerspectiveCamera with a sensible default position.
        # fit_camera() should be called after objects are added to reframe properly.
        self._camera = gfx.PerspectiveCamera(50)
        self._camera.local.position = (6, -8, 6)
        self._camera.look_at((0, 0, 0))

        # Orbit controller — register_events() wires mouse/wheel/key events.
        self._controller = gfx.OrbitController(self._camera)
        self._controller.register_events(self._renderer)

        # WASD keys: added as an additional handler on top of OrbitController.
        self._renderer.add_event_handler(self._on_key, "key_down")

    def _on_key(self, event):
        key = event.get("key", "")
        step = 0.05
        zoom_in, zoom_out = 0.92, 1.08
        if key == "w":
            self._controller.zoom(zoom_in)
        elif key == "s":
            self._controller.zoom(zoom_out)
        elif key == "a":
            self._controller.rotate(-step, 0)
        elif key == "d":
            self._controller.rotate(step, 0)
        elif key == " ":
            self._controller.rotate(0, -step)
        elif key == "Shift":
            self._controller.rotate(0, step)

    def add_object(self, cell_id: str, obj: gfx.WorldObject) -> None:
        self.remove_object(cell_id)
        self._objects[cell_id] = obj
        self._scene.add(obj)

    def remove_object(self, cell_id: str) -> None:
        if cell_id in self._objects:
            self._scene.remove(self._objects.pop(cell_id))

    def set_visible(self, cell_id: str, visible: bool) -> None:
        if cell_id in self._objects:
            self._objects[cell_id].visible = visible

    def fit_camera(self) -> None:
        bsphere = self._scene.get_world_bounding_sphere()
        if bsphere is not None:
            self._camera.show_object(self._scene, up=(0, 0, 1))

    def render(self) -> None:
        self._renderer.render(self._scene, self._camera)

    def snapshot(self) -> np.ndarray:
        """Return current frame as (H, W, 4) uint8 RGBA numpy array."""
        self.render()
        return self._renderer.snapshot()


# ---------------------------------------------------------------------------
# Interactive entry point
# ---------------------------------------------------------------------------

def _demo():
    """Stand-alone demo: render sin(x)*cos(y) in an interactive window."""
    from rendercanvas.auto import RenderCanvas

    n = 64
    x1d = np.linspace(-4, 4, n, dtype=np.float32)
    y1d = np.linspace(-4, 4, n, dtype=np.float32)
    x, y = np.meshgrid(x1d, y1d)
    z = np.sin(x) * np.cos(y)

    canvas = RenderCanvas(size=(1200, 800), title="pringle — Phase 1 demo")
    pr = PringleRenderer(canvas)
    pr.add_object("surface-1", make_surface_mesh(x, y, z))
    pr.fit_camera()

    @canvas.request_draw
    def draw():
        pr.render()

    canvas.run()


if __name__ == "__main__":
    _demo()
