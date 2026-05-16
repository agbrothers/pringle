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


def _clip_mesh_to_mask(
    positions: np.ndarray,
    indices: np.ndarray,
    normals: np.ndarray,
    inside: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Clip a triangle mesh to a boolean vertex mask.

    Triangles entirely outside are removed.  Triangles that cross the
    constraint boundary get a new vertex added at the midpoint of each
    boundary edge, turning the staircase pixel-steps into smooth diagonal
    cuts.  Works in O(n_triangles) with a dict cache for shared edges.

    Returns (positions, indices, normals) for the clipped mesh.
    """
    new_pos = list(positions)
    new_nor = list(normals)
    new_idx: list[list[int]] = []
    edge_cache: dict[tuple[int, int], int] = {}

    def _bv(ia: int, ib: int) -> int:
        """Return (or create) the midpoint boundary vertex on edge ia→ib."""
        key = (min(ia, ib), max(ia, ib))
        if key in edge_cache:
            return edge_cache[key]
        p = (positions[ia] + positions[ib]) * 0.5
        n = (normals[ia] + normals[ib]) * 0.5
        length = float(np.linalg.norm(n))
        if length > 1e-8:
            n = n / length
        idx = len(new_pos)
        new_pos.append(p)
        new_nor.append(n)
        edge_cache[key] = idx
        return idx

    for tri in indices:
        a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
        ia, ib, ic = bool(inside[a]), bool(inside[b]), bool(inside[c])
        n_in = int(ia) + int(ib) + int(ic)

        if n_in == 3:
            new_idx.append([a, b, c])
        elif n_in == 0:
            pass  # entirely outside — discard
        elif n_in == 1:
            # One inside vertex — one output triangle
            if ia:
                vi, o1, o2 = a, b, c
            elif ib:
                vi, o1, o2 = b, a, c
            else:
                vi, o1, o2 = c, a, b
            p1, p2 = _bv(vi, o1), _bv(vi, o2)
            new_idx.append([vi, p1, p2])
        else:
            # Two inside vertices — quad split into two triangles
            if not ia:
                vo, v1, v2 = a, b, c
            elif not ib:
                vo, v1, v2 = b, c, a
            else:
                vo, v1, v2 = c, a, b
            p1, p2 = _bv(v1, vo), _bv(v2, vo)
            new_idx.append([v1, v2, p1])
            new_idx.append([v2, p2, p1])

    out_pos = np.array(new_pos, dtype=np.float32)
    out_nor = np.array(new_nor, dtype=np.float32)
    if new_idx:
        out_idx = np.array(new_idx, dtype=np.int32)
    else:
        out_idx = np.zeros((0, 3), dtype=np.int32)
    return out_pos, out_idx, out_nor


def make_surface_mesh(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    color: tuple = (0.2, 0.4, 0.9, 1.0),
    constraint_mask: np.ndarray | None = None,
    z_raw: np.ndarray | None = None,
) -> gfx.Mesh:
    """
    Build a pygfx Mesh from a height-field surface.

    Parameters
    ----------
    x, y : (N, M) float arrays — spatial coordinate grids (from np.meshgrid)
    z    : (N, M) float array  — surface height values; NaN → degenerate triangle (skipped)
    color: RGBA tuple in [0, 1]

    Returns a gfx.Mesh ready to be added to a scene.

    If constraint_mask is provided (bool array, True = inside), boundary
    triangles are clipped using z_raw (z before NaN masking) so that edges
    are smooth diagonal cuts rather than pixel-stepped staircases.
    """
    rows, cols = z.shape
    # Use raw (pre-mask) z for vertex positions when clipping, so boundary
    # vertices on both sides of the mask have valid (non-NaN) z values.
    z_pos = z_raw if (z_raw is not None and constraint_mask is not None) else z
    positions = np.stack([x.ravel(), y.ravel(), z_pos.ravel()], axis=1).astype(np.float32)
    indices   = _grid_indices(rows, cols)
    normals   = _grid_normals(x, y, z_pos)

    if constraint_mask is not None:
        inside = constraint_mask.ravel().astype(bool)
        positions, indices, normals = _clip_mesh_to_mask(positions, indices, normals, inside)

    if len(indices) == 0:
        # Degenerate mesh (e.g. slider at zero collapses surface) — return invisible placeholder
        positions = np.zeros((3, 3), dtype=np.float32)
        indices   = np.array([[0, 1, 2]], dtype=np.int32)
        normals   = np.zeros((3, 3), dtype=np.float32)
        mat = gfx.MeshPhongMaterial(color=color, side="both")
        mat.opacity = 0.0
        geo = gfx.Geometry(positions=positions, indices=indices, normals=normals)
        return gfx.Mesh(geo, mat)

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

        # Overlay: axis lines + wireframe bounding box + orbit crosshair
        self._axes_visible = True
        self._bbox_visible = True
        self._crosshair_visible = True
        self._overlay: list[gfx.WorldObject] = []
        self._overlay_bounds = (-5.0, 5.0, -5.0, 5.0, -5.0, 5.0)  # xn,xx,yn,yx,zn,zx
        self._crosshair_group: gfx.WorldObject | None = None
        self._rebuild_overlay()
        self._rebuild_crosshair()

    def _on_key(self, event):
        key = getattr(event, "key", "") or ""
        cam_pos = np.array(self._camera.local.position, dtype=np.float64)
        target  = np.array(self._controller.target,     dtype=np.float64)
        dist    = float(np.linalg.norm(cam_pos - target))
        step    = max(dist * 0.05, 0.01)

        _moves = {
            "w": ( 0,    step,  0),
            "s": ( 0,   -step,  0),
            "a": (-step,  0,    0),
            "d": ( step,  0,    0),
            " ": ( 0,    0,    step),
            "Shift": (0, 0,   -step),
        }
        if key in _moves:
            self._pan_target(*_moves[key])

    def _pan_target(self, dx: float, dy: float, dz: float) -> None:
        """Translate the orbit target (and camera by the same delta) in world space."""
        delta = np.array([dx, dy, dz], dtype=np.float64)
        cam_pos = np.array(self._camera.local.position, dtype=np.float64)
        new_target = np.array(self._controller.target, dtype=np.float64) + delta
        self._controller.target = new_target
        self._camera.local.position = cam_pos + delta

    # ------------------------------------------------------------------
    # Overlay: axes + wireframe bounding box
    # ------------------------------------------------------------------

    def _rebuild_overlay(self) -> None:
        for obj in self._overlay:
            self._scene.remove(obj)
        self._overlay.clear()

        xn, xx, yn, yx, zn, zx = self._overlay_bounds

        def _line(p0, p1, color, thickness=1.5):
            pts = np.array([p0, p1], dtype=np.float32)
            geo = gfx.Geometry(positions=pts)
            mat = gfx.LineMaterial(color=color, thickness=thickness)
            return gfx.Line(geo, mat)

        # Axis lines
        axes = [
            _line((xn, 0, 0), (xx, 0, 0), (0.9, 0.2, 0.2, 1.0), 2.0),  # X red
            _line((0, yn, 0), (0, yx, 0), (0.2, 0.75, 0.2, 1.0), 2.0),  # Y green
            _line((0, 0, zn), (0, 0, zx), (0.2, 0.45, 0.95, 1.0), 2.0), # Z blue
        ]
        for ax in axes:
            ax.visible = self._axes_visible
            self._scene.add(ax)
            self._overlay.append(ax)
        self._axis_objects = axes

        # Wireframe bounding box — 12 edges
        corners = [
            (xn, yn, zn), (xx, yn, zn), (xx, yx, zn), (xn, yx, zn),
            (xn, yn, zx), (xx, yn, zx), (xx, yx, zx), (xn, yx, zx),
        ]
        edges = [
            (0,1),(1,2),(2,3),(3,0),  # bottom face
            (4,5),(5,6),(6,7),(7,4),  # top face
            (0,4),(1,5),(2,6),(3,7),  # verticals
        ]
        bbox_objs = []
        for i, j in edges:
            ln = _line(corners[i], corners[j], (0.55, 0.55, 0.55, 1.0), 1.0)
            ln.visible = self._bbox_visible
            self._scene.add(ln)
            self._overlay.append(ln)
            bbox_objs.append(ln)
        self._bbox_objects = bbox_objs

    def set_overlay_bounds(
        self,
        x_min: float, x_max: float,
        y_min: float, y_max: float,
        z_min: float, z_max: float,
    ) -> None:
        self._overlay_bounds = (x_min, x_max, y_min, y_max, z_min, z_max)
        self._rebuild_overlay()
        self._rebuild_crosshair()

    def set_axes_visible(self, visible: bool) -> None:
        self._axes_visible = visible
        for obj in self._axis_objects:
            obj.visible = visible

    def set_bbox_visible(self, visible: bool) -> None:
        self._bbox_visible = visible
        for obj in self._bbox_objects:
            obj.visible = visible

    def set_crosshair_visible(self, visible: bool) -> None:
        self._crosshair_visible = visible
        if self._crosshair_group is not None:
            self._crosshair_group.visible = visible

    def _rebuild_crosshair(self) -> None:
        if self._crosshair_group is not None:
            self._scene.remove(self._crosshair_group)

        xn, xx, yn, yx, zn, zx = self._overlay_bounds
        arm = max(xx - xn, yx - yn, zx - zn) * 0.025

        group = gfx.Group()
        for p0, p1, color in [
            ((-arm, 0, 0), (arm, 0, 0),  (0.85, 0.35, 0.35, 1.0)),
            ((0, -arm, 0), (0, arm, 0),  (0.35, 0.75, 0.35, 1.0)),
            ((0, 0, -arm), (0, 0, arm),  (0.35, 0.50, 0.90, 1.0)),
        ]:
            pts = np.array([p0, p1], dtype=np.float32)
            geo = gfx.Geometry(positions=pts)
            mat = gfx.LineMaterial(color=color, thickness=2.5)
            group.add(gfx.Line(geo, mat))

        group.visible = self._crosshair_visible
        self._scene.add(group)
        self._crosshair_group = group

    def get_scene_bsphere(self) -> tuple | None:
        """Return (cx, cy, cz, radius) of the scene bounding sphere, or None."""
        bs = self._scene.get_world_bounding_sphere()
        if bs is None:
            return None
        return tuple(bs)

    def add_object(self, cell_id: str, obj: gfx.WorldObject) -> bool:
        """Add or replace an object. Returns True if cell_id is new to the scene."""
        is_new = cell_id not in self._objects
        self.remove_object(cell_id)
        self._objects[cell_id] = obj
        self._scene.add(obj)
        return is_new

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
            # Always orbit around the coordinate origin, not the bounding sphere
            # center.  A surface constrained to z>0 would otherwise pull the
            # orbit target upward, making the origin appear off-screen.
            self._controller.target = (0.0, 0.0, 0.0)

    def render(self) -> None:
        if self._crosshair_group is not None:
            t = self._controller.target
            self._crosshair_group.local.position = (float(t[0]), float(t[1]), float(t[2]))
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
