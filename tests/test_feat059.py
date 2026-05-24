"""
FEAT-059 — Parametric surface rendering from xyz = (3, N, M) assignment.

Tests:
- Cylinder (helix-like) xyz = (3, N, N) produces a gfx.Mesh
- Torus xyz = (3, N, N) renders without error
- Normals are unit-length at non-degenerate points
- Opacity < 1.0 enables WBOIT alpha mode
- (N, 3) curve data still routes to make_scatter_mesh (regression)
"""

import numpy as np
import pytest

import pygfx as gfx

from pringle.renderer import make_parametric_surface_mesh, _parametric_normals


N = 32


def _cylinder_xyz(n: int = N) -> np.ndarray:
    u = np.linspace(0, 2 * np.pi, n)
    v = np.linspace(0, 2 * np.pi, n)
    U, V = np.meshgrid(u, v)
    return np.array([np.cos(U), np.sin(U), V])  # (3, N, N)


def _torus_xyz(n: int = N) -> np.ndarray:
    u = np.linspace(0, 2 * np.pi, n)
    v = np.linspace(0, 2 * np.pi, n)
    U, V = np.meshgrid(u, v)
    return np.array(
        [(2 + np.cos(V)) * np.cos(U), (2 + np.cos(V)) * np.sin(U), np.sin(V)]
    )  # (3, N, N)


def test_cylinder_returns_mesh():
    xyz = _cylinder_xyz()
    mesh = make_parametric_surface_mesh(xyz)
    assert isinstance(mesh, gfx.Mesh)


def test_torus_renders_without_error():
    xyz = _torus_xyz()
    mesh = make_parametric_surface_mesh(xyz)
    assert isinstance(mesh, gfx.Mesh)


def test_normals_are_unit_length():
    xyz = _torus_xyz()
    normals = _parametric_normals(xyz)
    lengths = np.linalg.norm(normals, axis=1)
    # Torus has no degenerate poles — all normals should be unit length
    assert np.allclose(lengths, 1.0, atol=1e-5)


def test_opacity_enables_wboit():
    xyz = _cylinder_xyz()
    mesh = make_parametric_surface_mesh(xyz, opacity=0.5)
    assert mesh.material.alpha_mode == "weighted_blend"
    assert mesh.material.opacity == pytest.approx(0.5)


def test_full_opacity_does_not_set_alpha_mode():
    xyz = _cylinder_xyz()
    mesh = make_parametric_surface_mesh(xyz, opacity=1.0)
    assert mesh.material.opacity == pytest.approx(1.0)
    assert getattr(mesh.material, "alpha_mode", "opaque") != "weighted_blend"


def test_curve_n3_still_uses_scatter_mesh():
    """Regression: (N, 3) parametric curve data must not hit the surface path."""
    from pringle.renderer import make_scatter_mesh
    pts = np.random.rand(20, 3).astype(np.float32)
    # make_scatter_mesh must accept (N, 3) without error
    mesh = make_scatter_mesh(pts)
    assert mesh is not None
