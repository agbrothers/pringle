"""
BUG-074 — Segfault changing cell color while a slider animates.

Fix 1: _tick() and _anim_tick() skip their bodies when a modal dialog is active,
        preventing wgpu scene-graph mutation during an active draw.
Fix 2: make_scatter_mesh() drops non-finite (NaN/Inf) points before GPU upload
        so a degenerate single-point scatter cell never corrupts a buffer.
"""

import numpy as np
import pytest

from pringle.renderer import make_scatter_mesh


def _positions(obj):
    """Return the positions array from a gfx Points or InstancedMesh object."""
    import pygfx as gfx
    if isinstance(obj, gfx.Points):
        return np.asarray(obj.geometry.positions.data)
    return None  # InstancedMesh doesn't expose positions the same way


# ---------------------------------------------------------------------------
# make_scatter_mesh NaN/Inf guard (Fix 2)
# ---------------------------------------------------------------------------

def test_scatter_all_nan_returns_invisible_placeholder():
    """All-NaN input must return a zero-opacity placeholder, not crash."""
    pts = np.full((5, 3), np.nan, dtype=np.float32)
    obj = make_scatter_mesh(pts)
    import pygfx as gfx
    assert isinstance(obj, gfx.Points)
    assert obj.material.opacity == 0.0


def test_scatter_all_inf_returns_invisible_placeholder():
    """All-Inf input must return a zero-opacity placeholder, not crash."""
    pts = np.full((3, 3), np.inf, dtype=np.float32)
    obj = make_scatter_mesh(pts)
    import pygfx as gfx
    assert isinstance(obj, gfx.Points)
    assert obj.material.opacity == 0.0


def test_scatter_mixed_finite_and_nan_keeps_finite_points():
    """NaN rows are dropped; finite rows are preserved in the output geometry."""
    pts = np.array([
        [1.0, 2.0, 3.0],
        [np.nan, 0.0, 0.0],
        [4.0, 5.0, 6.0],
        [0.0, np.inf, 0.0],
    ], dtype=np.float32)
    obj = make_scatter_mesh(pts)
    import pygfx as gfx
    assert isinstance(obj, gfx.Points)
    pos = np.asarray(obj.geometry.positions.data)
    assert len(pos) == 2
    assert np.allclose(pos[0], [1.0, 2.0, 3.0])
    assert np.allclose(pos[1], [4.0, 5.0, 6.0])


def test_scatter_single_nan_point_returns_invisible_placeholder():
    """Single-point NaN input (mirrors the repro session 'p' cell) → placeholder."""
    pts = np.array([[np.nan, np.nan, np.nan]], dtype=np.float32)
    obj = make_scatter_mesh(pts)
    import pygfx as gfx
    assert isinstance(obj, gfx.Points)
    assert obj.material.opacity == 0.0


def test_scatter_nan_with_vertex_colors_filters_colors_too():
    """vertex_colors must be filtered to match filtered pts (no shape mismatch crash)."""
    pts = np.array([
        [1.0, 2.0, 3.0],
        [np.nan, 0.0, 0.0],
        [4.0, 5.0, 6.0],
    ], dtype=np.float32)
    colors = np.array([
        [1.0, 0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0, 1.0],  # this row should be dropped
        [0.0, 0.0, 1.0, 1.0],
    ], dtype=np.float32)
    obj = make_scatter_mesh(pts, vertex_colors=colors)
    import pygfx as gfx
    assert isinstance(obj, gfx.Points)
    pos = np.asarray(obj.geometry.positions.data)
    assert len(pos) == 2


def test_scatter_fully_finite_points_unaffected():
    """Normal finite input must pass through without modification."""
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]], dtype=np.float32)
    obj = make_scatter_mesh(pts)
    import pygfx as gfx
    assert isinstance(obj, gfx.Points)
    pos = np.asarray(obj.geometry.positions.data)
    assert len(pos) == 2
