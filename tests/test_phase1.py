"""
Phase 1 tests: GPU baseline — offscreen rendering of surfaces, lines, and scatter.

Each test saves a PNG to tests/frames/ for visual inspection and asserts
that the frame is non-trivial (not all black or all one color).
"""

import numpy as np
import imageio.v3 as iio
import pytest
from pathlib import Path

from rendercanvas.offscreen import OffscreenRenderCanvas
from pringle.renderer import (
    PringleRenderer,
    make_surface_mesh,
    make_line_mesh,
    make_scatter_mesh,
)

FRAMES = Path(__file__).parent / "frames"


def _make_renderer(w=600, h=400) -> tuple[OffscreenRenderCanvas, PringleRenderer]:
    canvas = OffscreenRenderCanvas(size=(w, h))
    pr = PringleRenderer(canvas)
    return canvas, pr


def _save_and_check(img: np.ndarray, name: str) -> None:
    path = FRAMES / name
    iio.imwrite(path, img)
    # Not all black
    assert img[..., :3].max() > 20, f"{name}: frame is all black"
    # Not all one color (some variation in the image)
    assert img[..., :3].std() > 5.0, f"{name}: frame has no variation (uniform color)"


# ---------------------------------------------------------------------------

def test_surface_render():
    """sin(x)*cos(y) surface renders with Phong shading."""
    n = 64
    x1d = np.linspace(-4, 4, n, dtype=np.float32)
    y1d = np.linspace(-4, 4, n, dtype=np.float32)
    x, y = np.meshgrid(x1d, y1d)
    z = np.sin(x) * np.cos(y)

    _, pr = _make_renderer()
    pr.add_object("s1", make_surface_mesh(x, y, z))
    pr.fit_camera()
    img = pr.snapshot()

    _save_and_check(img, "phase1_surface.png")


def test_surface_with_nan():
    """Surface with NaN values (from constraint masking) renders without crash."""
    n = 64
    x1d = np.linspace(-4, 4, n, dtype=np.float32)
    y1d = np.linspace(-4, 4, n, dtype=np.float32)
    x, y = np.meshgrid(x1d, y1d)
    z = np.sin(x) * np.cos(y)
    # Mask: only show within a circle of radius 3
    z[x**2 + y**2 > 9] = np.nan

    _, pr = _make_renderer()
    pr.add_object("s1", make_surface_mesh(x, y, z))
    pr.fit_camera()
    img = pr.snapshot()

    _save_and_check(img, "phase1_surface_masked.png")


def test_two_surfaces():
    """Two independent surfaces coexist in the scene."""
    n = 48
    x1d = np.linspace(-3, 3, n, dtype=np.float32)
    y1d = np.linspace(-3, 3, n, dtype=np.float32)
    x, y = np.meshgrid(x1d, y1d)

    _, pr = _make_renderer()
    pr.add_object("s1", make_surface_mesh(x, y,  np.sin(x) * np.cos(y), color=(0.2, 0.4, 0.9, 1.0)))
    pr.add_object("s2", make_surface_mesh(x, y, -np.sin(x) * np.cos(y), color=(0.9, 0.3, 0.2, 1.0)))
    pr.fit_camera()
    img = pr.snapshot()

    _save_and_check(img, "phase1_two_surfaces.png")


def test_line_render():
    """3D helix renders as a line."""
    t = np.linspace(0, 4 * np.pi, 300, dtype=np.float32)
    points = np.column_stack([np.cos(t), np.sin(t), t / (4 * np.pi) * 4])

    _, pr = _make_renderer()
    pr.add_object("l1", make_line_mesh(points))
    pr.fit_camera()
    img = pr.snapshot()

    _save_and_check(img, "phase1_line.png")


def test_scatter_render():
    """Scatter points from a sphere surface render correctly."""
    rng = np.random.default_rng(42)
    n = 500
    theta = rng.uniform(0, np.pi, n).astype(np.float32)
    phi   = rng.uniform(0, 2 * np.pi, n).astype(np.float32)
    points = np.column_stack([
        np.sin(theta) * np.cos(phi),
        np.sin(theta) * np.sin(phi),
        np.cos(theta),
    ])

    _, pr = _make_renderer()
    pr.add_object("sc1", make_scatter_mesh(points, size=5.0))
    pr.fit_camera()
    img = pr.snapshot()

    _save_and_check(img, "phase1_scatter.png")


def test_visibility_toggle():
    """Hiding an object removes it from the rendered frame."""
    n = 48
    x1d = np.linspace(-3, 3, n, dtype=np.float32)
    y1d = np.linspace(-3, 3, n, dtype=np.float32)
    x, y = np.meshgrid(x1d, y1d)
    z = x**2 - y**2

    _, pr = _make_renderer()
    pr.add_object("s1", make_surface_mesh(x, y, z))
    pr.fit_camera()

    img_visible = pr.snapshot()
    pr.set_visible("s1", False)
    img_hidden   = pr.snapshot()

    # Visible mesh adds color variation; hidden → uniform background (low std)
    std_visible = float(img_visible[..., :3].astype(float).std())
    std_hidden  = float(img_hidden[..., :3].astype(float).std())
    assert std_visible > std_hidden, (
        f"Hiding object should reduce frame variation: {std_visible:.1f} > {std_hidden:.1f}"
    )

    iio.imwrite(FRAMES / "phase1_visibility_visible.png", img_visible)
    iio.imwrite(FRAMES / "phase1_visibility_hidden.png",  img_hidden)


def test_remove_object():
    """Removing an object clears it from the scene."""
    n = 32
    x1d = np.linspace(-2, 2, n, dtype=np.float32)
    y1d = np.linspace(-2, 2, n, dtype=np.float32)
    x, y = np.meshgrid(x1d, y1d)
    z = x * y

    _, pr = _make_renderer()
    pr.add_object("s1", make_surface_mesh(x, y, z))
    pr.fit_camera()
    img_before = pr.snapshot()

    pr.remove_object("s1")
    img_after = pr.snapshot()

    std_before = float(img_before[..., :3].astype(float).std())
    std_after  = float(img_after[..., :3].astype(float).std())
    assert std_before > std_after, (
        f"Removing object should reduce frame variation: {std_before:.1f} > {std_after:.1f}"
    )
