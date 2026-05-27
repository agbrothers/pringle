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

import collections
import math
import time
import numpy as np
import pygfx as gfx
import pylinalg as la

try:
    import numba
    from numba.typed import Dict as _NumbaDict
    from numba import types as _numba_types
    _HAVE_NUMBA = True
except ImportError:
    _HAVE_NUMBA = False


# ---------------------------------------------------------------------------
# Numba JIT boundary-triangle loop (PERF-011)
# ---------------------------------------------------------------------------

if _HAVE_NUMBA:
    @numba.njit(cache=True)
    def _clip_boundary_njit(
        positions,     # float32 (N, 3)
        normals,       # float32 (N, 3)
        f_values,      # float32 (N,)
        inside,        # bool   (N,)
        boundary_tris, # int32  (B, 3)
        out_pos,       # float32 (max_new, 3) — pre-allocated
        out_nor,       # float32 (max_new, 3) — pre-allocated
        out_idx,       # int32  (max_new, 3) — pre-allocated
        vert_offset,   # int: len(positions)
    ):
        """JIT boundary-triangle clipper. Returns (n_new_verts, n_new_tris).

        Edge key: pack (min_idx, max_idx) into one int64 so the edge cache
        avoids UniTuple typing issues across numba versions.
        """
        edge_cache = _NumbaDict.empty(
            key_type=_numba_types.int64,
            value_type=_numba_types.int32,
        )
        nv = 0
        nt = 0

        for ti in range(len(boundary_tris)):
            a = boundary_tris[ti, 0]
            b = boundary_tris[ti, 1]
            c = boundary_tris[ti, 2]
            ia = inside[a]; ib = inside[b]; ic = inside[c]
            n_in = int(ia) + int(ib) + int(ic)

            if n_in == 1:
                if ia:   vi, o1, o2 = a, b, c
                elif ib: vi, o1, o2 = b, a, c
                else:    vi, o1, o2 = c, a, b

                lo1 = np.int64(vi) if vi < o1 else np.int64(o1)
                hi1 = np.int64(o1) if vi < o1 else np.int64(vi)
                k1 = (lo1 << np.int64(32)) | hi1
                if k1 not in edge_cache:
                    fa = f_values[vi]; fb = f_values[o1]
                    denom = fa - fb
                    t = fa / denom if abs(denom) > 1e-10 else np.float32(0.5)
                    if t < 0.0: t = np.float32(0.0)
                    elif t > 1.0: t = np.float32(1.0)
                    for d in range(3):
                        out_pos[nv, d] = positions[vi, d] + t * (positions[o1, d] - positions[vi, d])
                        out_nor[nv, d] = normals[vi, d]   + t * (normals[o1, d]   - normals[vi, d])
                    nx_ = out_nor[nv, 0]; ny_ = out_nor[nv, 1]; nz_ = out_nor[nv, 2]
                    ln = math.sqrt(nx_*nx_ + ny_*ny_ + nz_*nz_)
                    if ln > 1e-8:
                        out_nor[nv, 0] /= ln; out_nor[nv, 1] /= ln; out_nor[nv, 2] /= ln
                    edge_cache[k1] = np.int32(vert_offset + nv)
                    nv += 1
                p1 = edge_cache[k1]

                lo2 = np.int64(vi) if vi < o2 else np.int64(o2)
                hi2 = np.int64(o2) if vi < o2 else np.int64(vi)
                k2 = (lo2 << np.int64(32)) | hi2
                if k2 not in edge_cache:
                    fa = f_values[vi]; fb = f_values[o2]
                    denom = fa - fb
                    t = fa / denom if abs(denom) > 1e-10 else np.float32(0.5)
                    if t < 0.0: t = np.float32(0.0)
                    elif t > 1.0: t = np.float32(1.0)
                    for d in range(3):
                        out_pos[nv, d] = positions[vi, d] + t * (positions[o2, d] - positions[vi, d])
                        out_nor[nv, d] = normals[vi, d]   + t * (normals[o2, d]   - normals[vi, d])
                    nx_ = out_nor[nv, 0]; ny_ = out_nor[nv, 1]; nz_ = out_nor[nv, 2]
                    ln = math.sqrt(nx_*nx_ + ny_*ny_ + nz_*nz_)
                    if ln > 1e-8:
                        out_nor[nv, 0] /= ln; out_nor[nv, 1] /= ln; out_nor[nv, 2] /= ln
                    edge_cache[k2] = np.int32(vert_offset + nv)
                    nv += 1
                p2 = edge_cache[k2]

                out_idx[nt, 0] = np.int32(vi); out_idx[nt, 1] = p1; out_idx[nt, 2] = p2
                nt += 1

            else:  # n_in == 2
                if not ia:    vo, v1, v2 = a, b, c
                elif not ib:  vo, v1, v2 = b, c, a
                else:         vo, v1, v2 = c, a, b

                lo1 = np.int64(v1) if v1 < vo else np.int64(vo)
                hi1 = np.int64(vo) if v1 < vo else np.int64(v1)
                k1 = (lo1 << np.int64(32)) | hi1
                if k1 not in edge_cache:
                    fa = f_values[v1]; fb = f_values[vo]
                    denom = fa - fb
                    t = fa / denom if abs(denom) > 1e-10 else np.float32(0.5)
                    if t < 0.0: t = np.float32(0.0)
                    elif t > 1.0: t = np.float32(1.0)
                    for d in range(3):
                        out_pos[nv, d] = positions[v1, d] + t * (positions[vo, d] - positions[v1, d])
                        out_nor[nv, d] = normals[v1, d]   + t * (normals[vo, d]   - normals[v1, d])
                    nx_ = out_nor[nv, 0]; ny_ = out_nor[nv, 1]; nz_ = out_nor[nv, 2]
                    ln = math.sqrt(nx_*nx_ + ny_*ny_ + nz_*nz_)
                    if ln > 1e-8:
                        out_nor[nv, 0] /= ln; out_nor[nv, 1] /= ln; out_nor[nv, 2] /= ln
                    edge_cache[k1] = np.int32(vert_offset + nv)
                    nv += 1
                p1 = edge_cache[k1]

                lo2 = np.int64(v2) if v2 < vo else np.int64(vo)
                hi2 = np.int64(vo) if v2 < vo else np.int64(v2)
                k2 = (lo2 << np.int64(32)) | hi2
                if k2 not in edge_cache:
                    fa = f_values[v2]; fb = f_values[vo]
                    denom = fa - fb
                    t = fa / denom if abs(denom) > 1e-10 else np.float32(0.5)
                    if t < 0.0: t = np.float32(0.0)
                    elif t > 1.0: t = np.float32(1.0)
                    for d in range(3):
                        out_pos[nv, d] = positions[v2, d] + t * (positions[vo, d] - positions[v2, d])
                        out_nor[nv, d] = normals[v2, d]   + t * (normals[vo, d]   - normals[v2, d])
                    nx_ = out_nor[nv, 0]; ny_ = out_nor[nv, 1]; nz_ = out_nor[nv, 2]
                    ln = math.sqrt(nx_*nx_ + ny_*ny_ + nz_*nz_)
                    if ln > 1e-8:
                        out_nor[nv, 0] /= ln; out_nor[nv, 1] /= ln; out_nor[nv, 2] /= ln
                    edge_cache[k2] = np.int32(vert_offset + nv)
                    nv += 1
                p2 = edge_cache[k2]

                out_idx[nt, 0] = np.int32(v1); out_idx[nt, 1] = np.int32(v2); out_idx[nt, 2] = p1
                nt += 1
                out_idx[nt, 0] = np.int32(v2); out_idx[nt, 1] = p2; out_idx[nt, 2] = p1
                nt += 1

        return nv, nt


# ---------------------------------------------------------------------------
# Mesh construction helpers
# ---------------------------------------------------------------------------

def _grid_gradients(
    x: np.ndarray, y: np.ndarray, z: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """∂z/∂x and ∂z/∂y via central finite differences on the (x, y, z) grid.
    Shared by _grid_normals and any downstream gradient consumer (critical points,
    slope maps, etc.) — compute once per surface update, pass the result to each."""
    return np.gradient(z, x[0, :], axis=1), np.gradient(z, y[:, 0], axis=0)


def _grid_normals(dz_dx: np.ndarray, dz_dy: np.ndarray) -> np.ndarray:
    """
    Compute per-vertex normals from pre-computed surface gradients.

    Normal = T_x × T_y = (-dz/dx, -dz/dy, 1), then normalized.
    Output shape: (N*M, 3) float32.
    """
    nx = -dz_dx
    ny = -dz_dy
    nz = np.ones_like(dz_dx)
    length = np.sqrt(nx**2 + ny**2 + nz**2)
    nx /= length;  ny /= length;  nz /= length
    return np.stack([nx.ravel(), ny.ravel(), nz.ravel()], axis=1).astype(np.float32)


def _parametric_normals(xyz: np.ndarray) -> np.ndarray:
    """Per-vertex normals for a parametric surface (3, N, M) via tangent cross product.
    Returns (N*M, 3) float32."""
    dPdu = np.gradient(xyz, axis=2)   # (3, N, M) tangent along u
    dPdv = np.gradient(xyz, axis=1)   # (3, N, M) tangent along v
    nx = dPdu[1] * dPdv[2] - dPdu[2] * dPdv[1]
    ny = dPdu[2] * dPdv[0] - dPdu[0] * dPdv[2]
    nz = dPdu[0] * dPdv[1] - dPdu[1] * dPdv[0]
    length = np.sqrt(nx**2 + ny**2 + nz**2)
    length = np.where(length < 1e-10, 1.0, length)
    nx /= length; ny /= length; nz /= length
    return np.stack([nx.ravel(), ny.ravel(), nz.ravel()], axis=1).astype(np.float32)


def _grid_indices(rows: int, cols: int) -> np.ndarray:
    """
    Build triangle indices for a rows×cols grid of vertices.
    Returns shape (2*(rows-1)*(cols-1), 3) int32.
    """
    r = np.arange(rows - 1, dtype=np.int32)[:, None]
    c = np.arange(cols - 1, dtype=np.int32)[None, :]
    i = (r * cols + c).ravel()
    t1 = np.column_stack([i,     i + 1,        i + cols])
    t2 = np.column_stack([i + 1, i + cols + 1, i + cols])
    return np.vstack([t1, t2])


def _clip_mesh_to_mask(
    positions: np.ndarray,
    indices: np.ndarray,
    normals: np.ndarray,
    f_values: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Clip a triangle mesh to a signed constraint field.

    f_values: float32 per-vertex array — positive = inside, negative = outside.
    inside is derived as f_values >= 0.

    Fast path: all-inside and all-outside triangles are handled in bulk via
    numpy boolean indexing — no Python loop. Only the O(n) perimeter triangles
    that straddle the boundary go through the Python loop.

    Boundary vertices are placed at the true constraint zero-crossing via
    linear interpolation: t = f_A / (f_A - f_B), which positions the vertex
    exactly where the constraint function equals zero along the edge.

    Returns (positions, indices, normals) for the clipped mesh.
    """
    inside = f_values >= 0

    # --- Vectorized classification ---
    inside_tri   = inside[indices]           # (T, 3) bool
    inside_count = inside_tri.sum(axis=1)   # (T,) int

    all_in       = inside_count == 3
    boundary     = (inside_count > 0) & (inside_count < 3)

    # All-inside triangles pass through unchanged.
    all_in_idx = indices[all_in]  # (K, 3) numpy array

    # --- Boundary triangles ---
    boundary_tris = indices[boundary]  # (B, 3) int32

    if _HAVE_NUMBA:
        # JIT path (PERF-011): compiled boundary loop, ~12× faster than Python
        max_new = 2 * max(len(boundary_tris), 1)
        _nb_pos = np.empty((max_new, 3), dtype=np.float32)
        _nb_nor = np.empty((max_new, 3), dtype=np.float32)
        _nb_idx = np.empty((max_new, 3), dtype=np.int32)
        nv_new, nt_new = _clip_boundary_njit(
            positions, normals, f_values, inside,
            boundary_tris, _nb_pos, _nb_nor, _nb_idx, len(positions),
        )
        if nv_new > 0:
            out_pos = np.concatenate([positions, _nb_pos[:nv_new]], axis=0)
            out_nor = np.concatenate([normals,   _nb_nor[:nv_new]], axis=0)
        else:
            out_pos, out_nor = positions, normals
        parts: list[np.ndarray] = []
        if len(all_in_idx):
            parts.append(all_in_idx)
        if nt_new > 0:
            parts.append(_nb_idx[:nt_new])
        out_idx = np.concatenate(parts, axis=0) if parts else np.zeros((0, 3), dtype=np.int32)
        return out_pos, out_idx, out_nor

    # --- Python fallback (no Numba) ---
    # Only new boundary vertices are accumulated; original arrays are never
    # converted to Python lists (avoids the O(n²) list(positions) cost).
    new_verts_pos: list[np.ndarray] = []
    new_verts_nor: list[np.ndarray] = []
    vertex_offset = len(positions)   # index of first new vertex
    new_idx: list[list[int]] = []
    edge_cache: dict[tuple[int, int], int] = {}

    def _bv(ia: int, ib: int) -> int:
        """Return (or create) a boundary vertex on edge ia→ib using zero-crossing interpolation."""
        key = (min(ia, ib), max(ia, ib))
        if key in edge_cache:
            return edge_cache[key]
        f_a = float(f_values[ia])
        f_b = float(f_values[ib])
        denom = f_a - f_b
        if abs(denom) > 1e-10 and np.isfinite(f_a) and np.isfinite(f_b):
            t = float(np.clip(f_a / denom, 0.0, 1.0))
        else:
            t = 0.5
        p = positions[ia] + t * (positions[ib] - positions[ia])
        nv = normals[ia] + t * (normals[ib] - normals[ia])
        length = float(np.linalg.norm(nv))
        new_verts_pos.append(p)
        new_verts_nor.append(nv / length if length > 1e-8 else nv)
        vi = vertex_offset + len(new_verts_pos) - 1
        edge_cache[key] = vi
        return vi

    for tri in boundary_tris:
        a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
        ia, ib, ic = bool(inside[a]), bool(inside[b]), bool(inside[c])
        n_in = int(ia) + int(ib) + int(ic)

        if n_in == 1:
            if ia:
                vi, o1, o2 = a, b, c
            elif ib:
                vi, o1, o2 = b, a, c
            else:
                vi, o1, o2 = c, a, b
            p1, p2 = _bv(vi, o1), _bv(vi, o2)
            new_idx.append([vi, p1, p2])
        else:
            # n_in == 2: quad split into two triangles
            if not ia:
                vo, v1, v2 = a, b, c
            elif not ib:
                vo, v1, v2 = b, c, a
            else:
                vo, v1, v2 = c, a, b
            p1, p2 = _bv(v1, vo), _bv(v2, vo)
            new_idx.append([v1, v2, p1])
            new_idx.append([v2, p2, p1])

    if new_verts_pos:
        out_pos = np.concatenate([positions, np.array(new_verts_pos, dtype=np.float32)], axis=0)
        out_nor = np.concatenate([normals,   np.array(new_verts_nor, dtype=np.float32)], axis=0)
    else:
        out_pos, out_nor = positions, normals

    parts2: list[np.ndarray] = []
    if len(all_in_idx):
        parts2.append(all_in_idx)
    if new_idx:
        parts2.append(np.array(new_idx, dtype=np.int32))
    out_idx = np.concatenate(parts2, axis=0) if parts2 else np.zeros((0, 3), dtype=np.int32)
    return out_pos, out_idx, out_nor


def _apply_colormap(
    values: np.ndarray,
    cmap_name: str,
    reverse: bool = False,
    v_min: float | None = None,
    v_max: float | None = None,
) -> np.ndarray:
    """Map scalar values to RGBA colors via matplotlib. Returns (N, 4) float32."""
    import matplotlib
    cmap = matplotlib.colormaps[cmap_name]
    if reverse:
        cmap = cmap.reversed()
    _min = v_min if v_min is not None else float(np.nanmin(values))
    _max = v_max if v_max is not None else float(np.nanmax(values))
    if _max - _min < 1e-10:
        norm = np.full(len(values), 0.5, dtype=np.float32)
    else:
        norm = ((values - _min) / (_max - _min)).astype(np.float32)
    np.clip(norm, 0.0, 1.0, out=norm)
    return cmap(norm).astype(np.float32)


def _build_unit_arrow_geometry(
    shaft_r: float = 0.3,
    head_r: float = 0.9,
    head_frac: float = 0.25,
    segments: int = 8,
) -> gfx.Geometry:
    """Shaft cylinder + cone head, combined into one Geometry. Unit arrow points along +Z, z ∈ [0, 1]."""
    shaft_h = 1.0 - head_frac
    head_h  = head_frac

    sg = gfx.cylinder_geometry(radius_bottom=shaft_r, radius_top=shaft_r,
                               height=shaft_h, radial_segments=segments)
    sp = sg.positions.data.copy(); sp[:, 2] += shaft_h / 2
    sn = sg.normals.data.copy()

    cg = gfx.cylinder_geometry(radius_bottom=head_r, radius_top=0.0,
                               height=head_h, radial_segments=segments)
    cp = cg.positions.data.copy(); cp[:, 2] += shaft_h + head_h / 2
    cn = cg.normals.data.copy()

    positions = np.concatenate([sp, cp], axis=0)
    normals   = np.concatenate([sn, cn], axis=0)
    indices   = np.concatenate([sg.indices.data,
                                cg.indices.data + len(sp)], axis=0)
    return gfx.Geometry(positions=positions.astype(np.float32),
                        normals=normals.astype(np.float32),
                        indices=indices.astype(np.int32))


_ARROW_GEO: gfx.Geometry | None = None  # module-level singleton; built once


def _arrow_matrix(tail: np.ndarray, head: np.ndarray, size: float = 1.0) -> np.ndarray | None:
    """
    4×4 float32 transform that rotates/scales the unit +Z arrow to point from tail to head.

    size scales the X and Y (radial) axes independently of the arrow length, so the
    shaft/head radius = unit_geometry_radius * size. Returns None for zero-length arrows.
    """
    d = np.asarray(head, dtype=np.float64) - np.asarray(tail, dtype=np.float64)
    L = float(np.linalg.norm(d))
    if L < 1e-10:
        return None
    d_hat = d / L

    z = np.array([0.0, 0.0, 1.0])
    axis = np.cross(z, d_hat)
    s = float(np.linalg.norm(axis))
    c = float(np.dot(z, d_hat))

    if s < 1e-8:  # parallel or anti-parallel
        R = np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    else:
        axis /= s
        K = np.array([[ 0,       -axis[2],  axis[1]],
                       [ axis[2],  0,       -axis[0]],
                       [-axis[1],  axis[0],  0      ]])
        R = np.eye(3) + s * K + (1 - c) * (K @ K)  # Rodrigues

    M = np.eye(4, dtype=np.float32)
    M[:3, 0] = R[:, 0] * size  # X scaled by size → controls shaft/head radius
    M[:3, 1] = R[:, 1] * size  # Y scaled by size
    M[:3, 2] = R[:, 2] * L    # Z scaled by length
    M[:3, 3] = tail.astype(np.float32)
    return M


def _arrow_matrices_batch(
    tails: np.ndarray,   # (N, 3) float32
    heads: np.ndarray,   # (N, 3) float32
    size: float = 0.1,
) -> np.ndarray:
    """Return (N, 4, 4) float32 instance transform matrices — fully vectorized Rodrigues.

    Replaces the O(N) Python loop in make_arrow_mesh; 200× faster at N=4096 (PERF-017).
    Degenerate arrows (zero length) produce all-zero matrices and are invisible.
    """
    N = len(tails)
    d = heads.astype(np.float64) - tails.astype(np.float64)     # (N, 3)
    L = np.linalg.norm(d, axis=1)                                # (N,)
    valid = L > 1e-10
    L_safe = np.where(valid, L, 1.0)
    d_hat = d / L_safe[:, None]                                  # (N, 3)

    # cross(z=[0,0,1], d_hat) = (-d_hat_y, d_hat_x, 0)
    axis = np.stack([-d_hat[:, 1], d_hat[:, 0], np.zeros(N)], axis=1)  # (N, 3)
    s = np.linalg.norm(axis, axis=1)                             # (N,) sin(angle)
    c = d_hat[:, 2]                                              # (N,) cos(angle)
    s_safe = np.where(s > 1e-8, s, 1.0)
    axis_n = axis / s_safe[:, None]                              # (N, 3) normalized

    ax, ay, az = axis_n[:, 0], axis_n[:, 1], axis_n[:, 2]
    zero = np.zeros(N)
    K = np.stack([
        np.stack([ zero, -az,   ay], axis=1),
        np.stack([ az,   zero, -ax], axis=1),
        np.stack([-ay,   ax,   zero], axis=1),
    ], axis=1)                                                    # (N, 3, 3)

    I3 = np.eye(3, dtype=np.float64)[None]
    KK = K @ K
    R = I3 + s[:, None, None] * K + (1 - c)[:, None, None] * KK  # (N, 3, 3)

    # Handle parallel (s≈0) and anti-parallel (c≈-1) cases
    parallel = s < 1e-8
    R[parallel & ~(c < 0)] = np.eye(3)
    flip = np.eye(3); flip[1, 1] = -1.0; flip[2, 2] = -1.0
    R[parallel & (c < 0)] = flip

    Ms = np.zeros((N, 4, 4), dtype=np.float32)
    Ms[:, :3, 0] = (R[:, :, 0] * size).astype(np.float32)
    Ms[:, :3, 1] = (R[:, :, 1] * size).astype(np.float32)
    Ms[:, :3, 2] = (R[:, :, 2] * L_safe[:, None]).astype(np.float32)
    Ms[:, :3, 3] = tails.astype(np.float32)
    Ms[:, 3, 3] = 1.0
    Ms[~valid] = 0.0
    return Ms


def make_arrow_mesh(
    arrows: np.ndarray,               # (N, 6): [tail_x,y,z, head_x,y,z]
    color: tuple = (0.9, 0.6, 0.1, 1.0),
    opacity: float = 1.0,
    normalize: bool = False,
    size: float = 0.1,
) -> gfx.InstancedMesh:
    """
    Build a pygfx InstancedMesh of 3D arrows from an (N, 6) array of tail+head pairs.

    normalize=True pins all arrows to equal length (mean magnitude) so that
    vector field direction is visually dominant over magnitude.
    size controls the shaft/head radius in world units (maps to style.point_size).
    The unit geometry has shaft_r=0.3 and head_r=0.9, so size=0.1 gives shaft_r=0.03.
    """
    global _ARROW_GEO
    if _ARROW_GEO is None:
        _ARROW_GEO = _build_unit_arrow_geometry()

    arrows = np.asarray(arrows, dtype=np.float32)
    tails, heads = arrows[:, :3], arrows[:, 3:]

    if normalize:
        mags = np.linalg.norm(heads - tails, axis=1, keepdims=True)
        mean_mag = float(np.nanmean(mags))
        dirs = (heads - tails) / np.maximum(mags, 1e-10)
        heads = tails + dirs * mean_mag

    mat = gfx.MeshPhongMaterial(color=color, side="front")
    if opacity < 1.0:
        mat.opacity = opacity
        mat.alpha_mode = "weighted_blend"
    mesh = gfx.InstancedMesh(_ARROW_GEO, mat, len(arrows))
    Ms = _arrow_matrices_batch(tails, heads, size=size)
    mesh.instance_buffer.data["matrix"][:] = Ms.transpose(0, 2, 1)  # pygfx stores column-major
    mesh.instance_buffer.update_full()
    return mesh


def make_surface_mesh(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    color: tuple = (0.2, 0.4, 0.9, 1.0),
    opacity: float = 1.0,
    constraint_mask: np.ndarray | None = None,
    constraint_values: np.ndarray | None = None,
    z_raw: np.ndarray | None = None,
    colormap: str | None = None,
    colormap_reversed: bool = False,
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
    # Compute gradients once; _grid_normals and any downstream consumers share these arrays.
    dz_dx, dz_dy = _grid_gradients(x, y, z_pos)
    normals   = _grid_normals(dz_dx, dz_dy)

    if constraint_values is not None:
        positions, indices, normals = _clip_mesh_to_mask(positions, indices, normals, constraint_values.ravel())
    elif constraint_mask is not None:
        f = constraint_mask.ravel().astype(np.float32) * 2 - 1
        positions, indices, normals = _clip_mesh_to_mask(positions, indices, normals, f)

    if len(indices) == 0:
        # Degenerate mesh (e.g. slider at zero collapses surface) — return invisible placeholder
        positions = np.zeros((3, 3), dtype=np.float32)
        indices   = np.array([[0, 1, 2]], dtype=np.int32)
        normals   = np.zeros((3, 3), dtype=np.float32)
        if colormap is not None:
            colors = np.zeros((3, 4), dtype=np.float32)
            geo = gfx.Geometry(positions=positions, indices=indices, normals=normals, colors=colors)
            mat = gfx.MeshBasicMaterial(color_mode="vertex", side="both")
        else:
            geo = gfx.Geometry(positions=positions, indices=indices, normals=normals)
            mat = gfx.MeshPhongMaterial(color=color, side="both")
        mat.opacity = 0.0
        return gfx.Mesh(geo, mat)

    if colormap is not None:
        if constraint_mask is not None:
            cmap_min = float(np.nanmin(z))
            cmap_max = float(np.nanmax(z))
        else:
            cmap_min = cmap_max = None
        colors = _apply_colormap(positions[:, 2], colormap, colormap_reversed,
                                 v_min=cmap_min, v_max=cmap_max)
        geo = gfx.Geometry(positions=positions, indices=indices, normals=normals, colors=colors)
        mat = gfx.MeshBasicMaterial(color_mode="vertex", side="both")
    else:
        geo = gfx.Geometry(positions=positions, indices=indices, normals=normals)
        mat = gfx.MeshPhongMaterial(color=color, side="both")
    if opacity < 1.0:
        mat.opacity = opacity
        mat.alpha_mode = "weighted_blend"
    return gfx.Mesh(geo, mat)


def make_parametric_surface_mesh(
    xyz: np.ndarray,
    color: tuple = (0.2, 0.4, 0.9, 1.0),
    opacity: float = 1.0,
    colormap: str | None = None,
    colormap_reversed: bool = False,
) -> gfx.Mesh:
    """Build a pygfx Mesh from a (3, N, M) parametric surface array."""
    _, rows, cols = xyz.shape
    positions = xyz.reshape(3, -1).T.astype(np.float32)
    indices   = _grid_indices(rows, cols)
    normals   = _parametric_normals(xyz)
    if colormap is not None:
        colors = _apply_colormap(positions[:, 2], colormap, colormap_reversed)
        geo = gfx.Geometry(positions=positions, indices=indices, normals=normals, colors=colors)
        mat = gfx.MeshBasicMaterial(color_mode="vertex", side="both")
    else:
        geo = gfx.Geometry(positions=positions, indices=indices, normals=normals)
        mat = gfx.MeshPhongMaterial(color=color, side="both")
    if opacity < 1.0:
        mat.opacity = opacity
        mat.alpha_mode = "weighted_blend"
    return gfx.Mesh(geo, mat)


def make_line_mesh(
    points: np.ndarray,
    color: tuple = (0.9, 0.4, 0.2, 1.0),
    opacity: float = 1.0,
    thickness: float = 0.05,
    colormap: str | None = None,
    colormap_reversed: bool = False,
    vertex_colors: np.ndarray | None = None,
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

    if len(pts) == 0:
        pts = np.zeros((1, 3), dtype=np.float32)
        geo = gfx.Geometry(positions=pts)
        mat = gfx.LineMaterial(color=color, thickness=thickness, thickness_space="world")
        mat.opacity = 0.0
        return gfx.Line(geo, mat)

    if vertex_colors is not None or colormap is not None:
        if vertex_colors is not None:
            colors = vertex_colors
        else:
            valid = ~np.any(np.isnan(pts), axis=1)
            n_valid = int(valid.sum())
            colors = np.zeros((len(pts), 4), dtype=np.float32)
            if n_valid > 0:
                idx_vals = np.linspace(0.0, 1.0, n_valid, dtype=np.float32)
                colors[valid] = _apply_colormap(idx_vals, colormap, colormap_reversed)
        geo = gfx.Geometry(positions=pts, colors=colors)
        mat = gfx.LineMaterial(color_mode="vertex", thickness=thickness, thickness_space="world")
    else:
        geo = gfx.Geometry(positions=pts)
        mat = gfx.LineMaterial(color=color, thickness=thickness, thickness_space="world")
    if opacity < 1.0:
        mat.opacity = opacity
        mat.alpha_mode = "weighted_blend"
    return gfx.Line(geo, mat)


def make_scatter_mesh(
    points: np.ndarray,
    color: tuple = (0.9, 0.6, 0.1, 1.0),
    opacity: float = 1.0,
    size: float = 0.1,
    as_spheres: bool = False,
    colormap: str | None = None,
    colormap_reversed: bool = False,
    vertex_colors: np.ndarray | None = None,
) -> gfx.Points | gfx.InstancedMesh:
    """
    Build a pygfx Points object from an (N, 3) or (N, 2) array.
    """
    pts = np.asarray(points, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] not in (2, 3):
        raise ValueError(f"points must be (N, 2) or (N, 3), got {pts.shape}")
    if pts.shape[1] == 2:
        pts = np.column_stack([pts, np.zeros(len(pts), dtype=np.float32)])

    if len(pts) == 0:
        pts = np.zeros((1, 3), dtype=np.float32)
        geo = gfx.Geometry(positions=pts)
        mat = gfx.PointsMaterial(color=color, size=size, size_space="world")
        mat.opacity = 0.0
        return gfx.Points(geo, mat)

    if as_spheres:
        sphere_geo = gfx.sphere_geometry(
            radius=size / 2,
            width_segments=16,
            height_segments=16,
        )
        mat = gfx.MeshPhongMaterial(color=color, side="front")
        if opacity < 1.0:
            mat.opacity = opacity
            mat.alpha_mode = "weighted_blend"
        mesh = gfx.InstancedMesh(sphere_geo, mat, len(pts))
        for i, pos in enumerate(pts):
            mesh.set_matrix_at(i, la.mat_from_translation(pos))
        return mesh

    if vertex_colors is not None or colormap is not None:
        if vertex_colors is not None:
            colors = vertex_colors
        else:
            idx_vals = np.linspace(0.0, 1.0, len(pts), dtype=np.float32)
            colors = _apply_colormap(idx_vals, colormap, colormap_reversed)
        geo = gfx.Geometry(positions=pts, colors=colors)
        mat = gfx.PointsMaterial(color_mode="vertex", size=size, size_space="world")
    else:
        geo = gfx.Geometry(positions=pts)
        mat = gfx.PointsMaterial(color=color, size=size, size_space="world")
    if opacity < 1.0:
        mat.opacity = opacity
        mat.alpha_mode = "weighted_blend"
    return gfx.Points(geo, mat)


# ---------------------------------------------------------------------------
# Incremental orbit event handler (BUG-013)
# ---------------------------------------------------------------------------

class _IncrementalOrbitHandler:
    """
    Wires mouse events to OrbitController using per-frame incremental deltas.

    The stock OrbitController.register_events() snapshots the camera state at
    drag-start and recomputes the full camera position from that snapshot on every
    pointer_move.  This makes it impossible for WASD panning to take effect during
    a mouse drag — the next mouse-move event always overwrites the WASD delta.

    This handler instead calls controller.rotate() / .pan() / .zoom() with the
    small delta since the *previous* pointer_move, so the controller always reads
    the live camera state.  WASD and mouse orbit can run simultaneously without
    either path clobbering the other.

    Bindings:
      - Left-drag  (button 1) : orbit (azimuth + elevation)
      - Right/Middle-drag (2/3): pan  (translate camera + target together)
      - Wheel                  : zoom (change camera-to-target distance)
    """

    _ORBIT_SENSITIVITY = 0.005   # radians per screen pixel
    _ZOOM_SENSITIVITY  = -0.001  # fractional scale per wheel unit (matches gfx default)

    def __init__(self, controller: gfx.OrbitController, renderer, canvas) -> None:
        self._controller = controller
        self._canvas     = canvas
        self._drag_button: int | None = None
        self._last_x: float = 0.0
        self._last_y: float = 0.0
        # Coast state: (ω_az, ω_el) in rad/s; None = not coasting.
        self._coast_velocity: tuple[float, float] | None = None
        self._vel_samples: collections.deque = collections.deque(maxlen=10)
        renderer.add_event_handler(
            self._handle,
            "pointer_down",
            "pointer_move",
            "pointer_up",
            "wheel",
        )

    def _rect(self) -> tuple[float, float, float, float]:
        w, h = self._canvas.get_logical_size()
        return (0.0, 0.0, float(w), float(h))

    def _handle(self, event) -> None:
        t = event.type
        if t == "pointer_down":
            if self._drag_button is None:
                self._coast_velocity = None
                self._vel_samples.clear()
                self._drag_button = event.button
                self._last_x = float(event.x)
                self._last_y = float(event.y)
        elif t == "pointer_move":
            if self._drag_button is None:
                return
            dx = float(event.x) - self._last_x
            dy = float(event.y) - self._last_y
            self._last_x = float(event.x)
            self._last_y = float(event.y)
            if self._drag_button == 1:
                daz = dx * self._ORBIT_SENSITIVITY
                del_ = dy * self._ORBIT_SENSITIVITY
                self._vel_samples.append((daz, del_, time.perf_counter()))
                self._controller.rotate((daz, del_), self._rect())
            elif self._drag_button in (2, 3):
                self._controller.pan((dx, dy), self._rect())
        elif t == "pointer_up":
            if event.button == self._drag_button:
                if self._drag_button == 1:
                    self._compute_coast_velocity()
                self._drag_button = None
        elif t == "wheel":
            d = (event.dy or event.dx) * self._ZOOM_SENSITIVITY
            self._controller.zoom((d, d), self._rect())

    def _compute_coast_velocity(self) -> None:
        """Compute (ω_az, ω_el) in rad/s from the last ~100ms of drag samples."""
        _WINDOW = 0.1
        if not self._vel_samples:
            self._coast_velocity = None
            return
        t_cutoff = self._vel_samples[-1][2] - _WINDOW
        recent = [(daz, del_, t) for daz, del_, t in self._vel_samples if t >= t_cutoff]
        if len(recent) < 2:
            self._coast_velocity = None
            return
        dt = recent[-1][2] - recent[0][2]
        if dt < 1e-3:
            self._coast_velocity = None
            return
        total_daz = sum(s[0] for s in recent)
        total_del = sum(s[1] for s in recent)
        self._coast_velocity = (total_daz / dt, total_del / dt)
        self._vel_samples.clear()


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

        # Live surface geometry cache (PERF-002)
        # Keyed by cell_id; only populated for unconstrained surfaces.
        # Stores the gfx.Geometry and gfx.Mesh from the last full build so
        # that subsequent animation frames can update buffers in-place without
        # rebuilding geometry or triggering a full GPU buffer upload.
        self._surface_geo:  dict[str, gfx.Geometry] = {}
        self._surface_mesh: dict[str, gfx.Mesh]     = {}
        # Topology signature: (rows, cols, has_colormap).
        # If this changes between frames, the cache is invalidated and a full
        # rebuild is performed.
        self._surface_sig:  dict[str, tuple]         = {}

        # Live arrow mesh cache (PERF-017)
        # Keyed by cell_id. Stores the InstancedMesh so that on frames where N
        # is unchanged we can write the new matrix batch directly into the
        # existing instance_buffer instead of rebuilding the pygfx object.
        self._arrow_mesh:  dict[str, gfx.InstancedMesh] = {}
        self._arrow_count: dict[str, int]                = {}

        # Lighting
        self._scene.add(gfx.AmbientLight(intensity=0.4))
        sun = gfx.DirectionalLight(intensity=1.5)
        sun.local.position = (5, 8, 10)
        self._scene.add(sun)

        # Background
        self._bg = gfx.Background(None, gfx.BackgroundMaterial((0.067, 0.067, 0.067, 1.0)))
        self._scene.add(self._bg)

        # Camera — PerspectiveCamera with a sensible default position.
        # fit_camera() should be called after objects are added to reframe properly.
        self._camera = gfx.PerspectiveCamera(50, depth_range=(0.01, 100_000))
        self._camera.local.position = (6, -8, 6)
        self._camera.look_at((0, 0, 0))

        # Orbit controller — _IncrementalOrbitHandler wires mouse/wheel events
        # using per-frame deltas so WASD and mouse orbit can run simultaneously.
        self._controller = gfx.OrbitController(self._camera)
        self._orbit_handler = _IncrementalOrbitHandler(
            self._controller, self._renderer, canvas
        )

        # Keyboard panning is handled at the Qt level in PringleViewport,
        # not here, so that event.accept() can suppress macOS accent popovers.

        # Drop shadows — projected silhouettes at the z_min floor plane
        self._shadow_objects: dict[str, gfx.WorldObject] = {}
        self._shadow_visible: bool = False
        self._shadow_opacity: float = 0.5
        # Light color so shadows show against the default dark background
        self._shadow_color: tuple[float, float, float] = (0.15, 0.15, 0.15)

        # Overlay: axis lines + wireframe bounding box + orbit crosshair
        self._axes_visible = True
        self._bbox_visible = True
        self._crosshair_visible = True
        self._overlay: list[gfx.WorldObject] = []
        self._overlay_bounds = (-5.0, 5.0, -5.0, 5.0, -5.0, 5.0)  # xn,xx,yn,yx,zn,zx
        self._crosshair_group: gfx.WorldObject | None = None
        self._crosshair_shadow_group: gfx.Group | None = None
        self._rebuild_overlay()
        self._rebuild_crosshair()

    def _pan_target(self, dx: float, dy: float, dz: float) -> None:
        """Translate the orbit target (and camera by the same delta) in world space."""
        delta = np.array([dx, dy, dz], dtype=np.float64)
        cam_pos = np.array(self._camera.local.position, dtype=np.float64)
        new_target = np.array(self._controller.target, dtype=np.float64) + delta
        # Move camera first: the target setter calls camera.look_at(new_target),
        # which must read the updated camera position or the look direction tilts
        # slightly each step, accumulating into visible crosshair drift.
        self._camera.local.position = cam_pos + delta
        self._controller.target = new_target

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
        old_zfloor = self._overlay_bounds[4]
        self._overlay_bounds = (x_min, x_max, y_min, y_max, z_min, z_max)
        self._rebuild_overlay()
        self._rebuild_crosshair()
        if z_min != old_zfloor:
            self._rebuild_shadows()

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
        if self._crosshair_shadow_group is not None:
            self._crosshair_shadow_group.visible = self._shadow_visible and visible

    def _rebuild_crosshair(self) -> None:
        if self._crosshair_group is not None:
            self._scene.remove(self._crosshair_group)
        if self._crosshair_shadow_group is not None:
            self._scene.remove(self._crosshair_shadow_group)

        xn, xx, yn, yx, zn, zx = self._overlay_bounds
        arm = max(xx - xn, yx - yn, zx - zn) * 0.0125

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

        # Shadow: X and Y arms only (Z arm collapses to a point at z_floor)
        sc = (*self._shadow_color, self._shadow_opacity)
        shadow_group = gfx.Group()
        for p0, p1 in [
            ((-arm, 0, 0), (arm, 0, 0)),
            ((0, -arm, 0), (0, arm, 0)),
        ]:
            pts = np.array([p0, p1], dtype=np.float32)
            geo = gfx.Geometry(positions=pts)
            mat = gfx.LineMaterial(color=sc, thickness=2.5)
            shadow_group.add(gfx.Line(geo, mat))
        shadow_group.visible = self._shadow_visible and self._crosshair_visible
        self._scene.add(shadow_group)
        self._crosshair_shadow_group = shadow_group

    def get_scene_bsphere(self) -> tuple | None:
        """Return (cx, cy, cz, radius) of the scene bounding sphere, or None."""
        bs = self._scene.get_world_bounding_sphere()
        if bs is None:
            return None
        return tuple(bs)

    # ------------------------------------------------------------------
    # Shadow management
    # ------------------------------------------------------------------

    def _make_shadow_object(self, obj: gfx.WorldObject) -> gfx.WorldObject | None:
        """Build a flattened copy of obj projected down onto the z_min floor."""
        z_floor = float(self._overlay_bounds[4]) + 1e-3  # tiny offset avoids z-fighting
        color = (*self._shadow_color, self._shadow_opacity)
        try:
            geom = obj.geometry
            if geom is None or geom.positions is None:
                return None
            pos = np.array(geom.positions.data, dtype=np.float32).copy()
            if pos.shape[1] < 3 or len(pos) == 0:
                return None
            pos[:, 2] = z_floor

            if isinstance(obj, gfx.Mesh):
                indices = (np.array(geom.indices.data, dtype=np.int32)
                           if geom.indices is not None else None)
                shadow_geo = gfx.Geometry(positions=pos, indices=indices)
                mat = gfx.MeshBasicMaterial(color=color, side="both")
                return gfx.Mesh(shadow_geo, mat)
            elif isinstance(obj, gfx.Line):
                shadow_geo = gfx.Geometry(positions=pos)
                mat = gfx.LineMaterial(
                    color=color,
                    thickness=obj.material.thickness,
                    thickness_space="world",
                )
                return gfx.Line(shadow_geo, mat)
            elif isinstance(obj, gfx.Points):
                shadow_geo = gfx.Geometry(positions=pos)
                mat = gfx.PointsMaterial(
                    color=color,
                    size=obj.material.size,
                    size_space="world",
                )
                return gfx.Points(shadow_geo, mat)
        except Exception:
            pass
        return None

    def _rebuild_shadows(self) -> None:
        """Recreate all shadow objects (called when z_min floor changes)."""
        for shadow in list(self._shadow_objects.values()):
            self._scene.remove(shadow)
        self._shadow_objects.clear()
        for cell_id, obj in self._objects.items():
            shadow = self._make_shadow_object(obj)
            if shadow is not None:
                shadow.visible = self._shadow_visible and obj.visible
                self._scene.add(shadow)
                self._shadow_objects[cell_id] = shadow

    def set_shadow_visible(self, visible: bool) -> None:
        self._shadow_visible = visible
        for cell_id, shadow in self._shadow_objects.items():
            src = self._objects.get(cell_id)
            shadow.visible = visible and (src is None or src.visible)
        if self._crosshair_shadow_group is not None:
            self._crosshair_shadow_group.visible = visible and self._crosshair_visible

    def set_shadow_opacity(self, opacity: float) -> None:
        self._shadow_opacity = opacity
        color = (*self._shadow_color, opacity)
        for shadow in self._shadow_objects.values():
            shadow.material.color = color
        if self._crosshair_shadow_group is not None:
            for line in self._crosshair_shadow_group.children:
                line.material.color = color

    def set_shadow_color_for_bg(self, light_bg: bool) -> None:
        """Switch shadow colour to contrast with the active background."""
        self._shadow_color = (0.8, 0.8, 0.8) if light_bg else (0.15, 0.15, 0.15)
        color = (*self._shadow_color, self._shadow_opacity)
        for shadow in self._shadow_objects.values():
            shadow.material.color = color
        if self._crosshair_shadow_group is not None:
            for line in self._crosshair_shadow_group.children:
                line.material.color = color

    # ------------------------------------------------------------------
    # Object management
    # ------------------------------------------------------------------

    def add_object(self, cell_id: str, obj: gfx.WorldObject) -> bool:
        """Add or replace an object. Returns True if cell_id is new to the scene."""
        is_new = cell_id not in self._objects
        self.remove_object(cell_id)
        self._objects[cell_id] = obj
        self._scene.add(obj)
        shadow = self._make_shadow_object(obj)
        if shadow is not None:
            shadow.visible = self._shadow_visible
            self._scene.add(shadow)
            self._shadow_objects[cell_id] = shadow
        return is_new

    def remove_object(self, cell_id: str) -> None:
        if cell_id in self._objects:
            self._scene.remove(self._objects.pop(cell_id))
        if cell_id in self._shadow_objects:
            self._scene.remove(self._shadow_objects.pop(cell_id))
        self._surface_geo.pop(cell_id, None)
        self._surface_mesh.pop(cell_id, None)
        self._surface_sig.pop(cell_id, None)
        self._arrow_mesh.pop(cell_id, None)
        self._arrow_count.pop(cell_id, None)

    def set_visible(self, cell_id: str, visible: bool) -> None:
        if cell_id in self._objects:
            self._objects[cell_id].visible = visible
        if cell_id in self._shadow_objects:
            self._shadow_objects[cell_id].visible = visible and self._shadow_visible

    def update_surface(
        self,
        cell_id: str,
        x: np.ndarray, y: np.ndarray, z: np.ndarray,
        color: tuple, opacity: float,
        constraint_mask, constraint_values, z_raw,
        colormap: str | None, colormap_reversed: bool,
    ) -> bool:
        """Add or update a surface cell. Returns True if the cell is new (caller should fit camera).

        When no constraint is active and the grid shape and colormap mode are
        unchanged from the previous frame, geometry buffers are updated in-place:
        only the z column of positions and the full normals array are re-uploaded
        to the GPU. The index buffer (387 KB) is never re-uploaded on these frames.

        Falls back to a full make_surface_mesh + add_object rebuild when:
        - a constraint is active (topology may change)
        - the grid shape changed
        - colormap mode changed (MeshPhongMaterial ↔ MeshBasicMaterial)
        - first frame for this cell
        """
        rows, cols = z.shape
        sig = (rows, cols, colormap is not None)
        has_constraint = constraint_mask is not None or constraint_values is not None

        if (
            not has_constraint
            and cell_id in self._surface_geo
            and self._surface_sig.get(cell_id) == sig
        ):
            self._update_surface_inplace(cell_id, x, y, z, color, opacity, colormap, colormap_reversed)
            return False

        # Full rebuild path
        mesh = make_surface_mesh(
            x, y, z, color, opacity,
            constraint_mask, constraint_values, z_raw,
            colormap, colormap_reversed,
        )
        is_new = self.add_object(cell_id, mesh)

        # Cache live geometry for future in-place updates (not for constrained
        # or degenerate meshes — placeholder has only 3 vertices).
        if not has_constraint and mesh.geometry.positions.nitems > 3:
            self._surface_geo[cell_id]  = mesh.geometry
            self._surface_mesh[cell_id] = mesh
            self._surface_sig[cell_id]  = sig

        return is_new

    def _update_surface_inplace(
        self,
        cell_id: str,
        x: np.ndarray, y: np.ndarray, z: np.ndarray,
        color: tuple, opacity: float,
        colormap: str | None, colormap_reversed: bool,
    ) -> None:
        """Write z + normals (and optionally colors) into existing GPU buffers."""
        geo  = self._surface_geo[cell_id]
        mesh = self._surface_mesh[cell_id]

        geo.positions.data[:, 2] = z.ravel()
        geo.positions.update_full()

        dz_dx, dz_dy = _grid_gradients(x, y, z)
        geo.normals.data[:] = _grid_normals(dz_dx, dz_dy)
        geo.normals.update_full()

        if colormap is not None:
            geo.colors.data[:] = _apply_colormap(z.ravel(), colormap, colormap_reversed)
            geo.colors.update_full()
        else:
            mesh.material.color = color

        if opacity < 1.0:
            mesh.material.opacity = opacity
            mesh.material.alpha_mode = "weighted_blend"
        else:
            mesh.material.opacity = 1.0

    def update_arrows(
        self,
        cell_id: str,
        arrows: np.ndarray,   # (N, 6): [tail_x,y,z, head_x,y,z]
        color: tuple,
        opacity: float,
        normalize: bool = False,
        size: float = 0.1,
    ) -> bool:
        """Add or update an arrow cell. Returns True if the cell is new (caller should fit camera).

        When N is unchanged from the previous frame, writes the new matrix batch
        directly into the existing InstancedMesh.instance_buffer (no pygfx object
        rebuild, no full GPU buffer re-upload). Falls back to a full rebuild on
        N change or first frame.
        """
        arrows = np.asarray(arrows, dtype=np.float32)
        tails = arrows[:, :3]
        heads = arrows[:, 3:]

        if normalize:
            mags = np.linalg.norm(heads - tails, axis=1, keepdims=True)
            mean_mag = float(np.nanmean(mags))
            dirs = (heads - tails) / np.maximum(mags, 1e-10)
            heads = tails + dirs * mean_mag

        N = len(arrows)
        if cell_id in self._arrow_mesh and self._arrow_count.get(cell_id) == N:
            Ms = _arrow_matrices_batch(tails, heads, size=size)
            ib = self._arrow_mesh[cell_id].instance_buffer
            ib.data["matrix"][:] = Ms.transpose(0, 2, 1)  # pygfx stores column-major
            ib.update_full()
            mesh = self._arrow_mesh[cell_id]
            if opacity < 1.0:
                mesh.material.opacity = opacity
                mesh.material.alpha_mode = "weighted_blend"
            else:
                mesh.material.opacity = 1.0
            return False

        # Full rebuild (first frame or N changed)
        norm_arrows = np.concatenate([tails, heads], axis=1)
        mesh = make_arrow_mesh(norm_arrows, color=color, opacity=opacity,
                               normalize=False, size=size)
        is_new = self.add_object(cell_id, mesh)
        self._arrow_mesh[cell_id]  = mesh
        self._arrow_count[cell_id] = N
        return is_new

    def set_background_color(self, color: tuple) -> None:
        self._bg.material = gfx.BackgroundMaterial(color)

    def fit_camera(self) -> None:
        # Temporarily hide shadows so they don't inflate the bounding sphere
        for shadow in self._shadow_objects.values():
            shadow.visible = False
        if self._crosshair_shadow_group is not None:
            self._crosshair_shadow_group.visible = False
        bsphere = self._scene.get_world_bounding_sphere()
        if bsphere is not None:
            self._camera.show_object(self._scene, up=(0, 0, 1))
            # Always orbit around the coordinate origin, not the bounding sphere
            # center.  A surface constrained to z>0 would otherwise pull the
            # orbit target upward, making the origin appear off-screen.
            self._controller.target = (0.0, 0.0, 0.0)
        for cell_id, shadow in self._shadow_objects.items():
            src = self._objects.get(cell_id)
            shadow.visible = self._shadow_visible and (src is None or src.visible)
        if self._crosshair_shadow_group is not None:
            self._crosshair_shadow_group.visible = self._shadow_visible and self._crosshair_visible

    def render(self) -> None:
        if self._crosshair_group is not None:
            t = self._controller.target
            self._crosshair_group.local.position = (float(t[0]), float(t[1]), float(t[2]))
        if self._crosshair_shadow_group is not None:
            t = self._controller.target
            z_floor = float(self._overlay_bounds[4]) + 1e-3
            self._crosshair_shadow_group.local.position = (float(t[0]), float(t[1]), z_floor)
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
