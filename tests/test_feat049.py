"""
FEAT-049 — Crosshair shadow projected onto z_min floor.

Tests cover:
- _crosshair_shadow_group has exactly 2 Line children (X and Y arms)
- Shadow group z-position equals z_floor after render()
- set_crosshair_visible(False) hides the shadow group
- set_shadow_visible(False) hides the shadow group
- Toggling both independently obeys AND logic
- set_shadow_opacity updates line material color on the crosshair shadow group
- set_shadow_color_for_bg updates line material color
- z_min change via set_overlay_bounds rebuilds shadow at new z_floor
"""

import numpy as np
import pytest
from rendercanvas.offscreen import OffscreenRenderCanvas
from pringle.renderer import PringleRenderer


@pytest.fixture
def renderer():
    canvas = OffscreenRenderCanvas(size=(400, 300))
    return PringleRenderer(canvas)


def _z_floor(pr: PringleRenderer) -> float:
    return float(pr._overlay_bounds[4]) + 1e-3


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_shadow_group_has_two_line_children(renderer):
    """X and Y arms only — 2 Lines, not 3."""
    import pygfx as gfx
    sg = renderer._crosshair_shadow_group
    assert sg is not None
    children = list(sg.children)
    assert len(children) == 2
    assert all(isinstance(c, gfx.Line) for c in children)


# ---------------------------------------------------------------------------
# Per-frame position
# ---------------------------------------------------------------------------

def test_shadow_z_position_equals_z_floor(renderer):
    renderer.render()
    sg = renderer._crosshair_shadow_group
    expected_z = _z_floor(renderer)
    assert abs(sg.local.position[2] - expected_z) < 1e-6


def test_shadow_xy_tracks_orbit_target(renderer):
    renderer._controller.target = (3.0, -2.0, 1.0)
    renderer.render()
    sg = renderer._crosshair_shadow_group
    assert abs(sg.local.position[0] - 3.0) < 1e-6
    assert abs(sg.local.position[1] - (-2.0)) < 1e-6
    # z stays at floor, not 1.0
    assert abs(sg.local.position[2] - _z_floor(renderer)) < 1e-6


# ---------------------------------------------------------------------------
# Visibility toggles
# ---------------------------------------------------------------------------

def test_shadow_visible_false_hides_group(renderer):
    renderer.set_shadow_visible(True)
    renderer.set_crosshair_visible(True)
    renderer.set_shadow_visible(False)
    assert not renderer._crosshair_shadow_group.visible


def test_crosshair_visible_false_hides_group(renderer):
    renderer.set_shadow_visible(True)
    renderer.set_crosshair_visible(True)
    renderer.set_crosshair_visible(False)
    assert not renderer._crosshair_shadow_group.visible


def test_both_on_shows_group(renderer):
    renderer.set_shadow_visible(True)
    renderer.set_crosshair_visible(True)
    assert renderer._crosshair_shadow_group.visible


def test_shadow_on_crosshair_off_hides_group(renderer):
    renderer.set_shadow_visible(True)
    renderer.set_crosshair_visible(False)
    assert not renderer._crosshair_shadow_group.visible


def test_shadow_off_crosshair_on_hides_group(renderer):
    renderer.set_shadow_visible(False)
    renderer.set_crosshair_visible(True)
    assert not renderer._crosshair_shadow_group.visible


# ---------------------------------------------------------------------------
# Color / opacity updates
# ---------------------------------------------------------------------------

def test_set_shadow_opacity_updates_crosshair_shadow(renderer):
    renderer.set_shadow_opacity(0.3)
    for line in renderer._crosshair_shadow_group.children:
        assert abs(line.material.color[3] - 0.3) < 1e-4


def test_set_shadow_color_for_bg_light(renderer):
    renderer.set_shadow_color_for_bg(light_bg=True)
    for line in renderer._crosshair_shadow_group.children:
        r, g, b, _ = line.material.color
        assert r > 0.5 and g > 0.5 and b > 0.5


def test_set_shadow_color_for_bg_dark(renderer):
    renderer.set_shadow_color_for_bg(light_bg=False)
    for line in renderer._crosshair_shadow_group.children:
        r, g, b, _ = line.material.color
        assert r < 0.5 and g < 0.5 and b < 0.5


# ---------------------------------------------------------------------------
# z_min change rebuilds shadow
# ---------------------------------------------------------------------------

def test_zmin_change_rebuilds_shadow_at_new_floor(renderer):
    renderer.set_overlay_bounds(-5, 5, -5, 5, -3.0, 5)
    renderer.render()
    expected_z = -3.0 + 1e-3
    assert abs(renderer._crosshair_shadow_group.local.position[2] - expected_z) < 1e-5
