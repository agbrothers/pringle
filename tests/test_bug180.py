"""
BUG-180 — Session camera overwritten by fit_camera; duplicate cell also resets camera.

Root cause: _seen_cell_ids starts empty, so the first render of every cell (including
cells loaded from a session) triggered fit_camera(), overwriting the restored camera
position.

Fix 1: fit_camera fires only when the scene transitions from empty to non-empty (first
       cell ever added to a fresh session).
Fix 2: _on_open pre-populates _seen_cell_ids from the loaded session before evaluation.
"""

import sys
import types
import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def viewport(qapp):
    from pringle.app import PringleViewport
    vp = PringleViewport()
    return vp


def _install_fit_counter(vp):
    """Replace fit_camera with a counter and return it."""
    count = [0]
    vp._pr.fit_camera = lambda: count.__setitem__(0, count[0] + 1)
    return count


def _make_surface_args():
    """Minimal surface data accepted by update_surface."""
    import numpy as np
    n = 4
    g = np.linspace(-1, 1, n)
    x, y = np.meshgrid(g, g)
    z = np.zeros_like(x)
    mask = np.zeros(n * n, dtype=bool)
    vals = np.zeros(n * n)
    return x, y, z, (0.5, 0.5, 0.5, 1.0), 1.0, mask, vals, z, None, False


class TestFitCameraGate:
    """fit_camera must only fire on the empty → non-empty transition."""

    def test_fit_fires_for_first_cell_on_empty_scene(self, viewport):
        viewport._seen_cell_ids.clear()
        count = _install_fit_counter(viewport)
        x, y, z, color, opacity, mask, vals, z_raw, cm, cmr = _make_surface_args()
        viewport.update_surface("cell-A", x, y, z, color, opacity, mask, vals, z_raw, cm, cmr)
        assert count[0] == 1, "fit_camera should fire for first cell on empty scene"
        assert "cell-A" in viewport._seen_cell_ids

    def test_fit_does_not_fire_for_second_cell(self, viewport):
        viewport._seen_cell_ids.clear()
        viewport._seen_cell_ids.add("existing-cell")
        count = _install_fit_counter(viewport)
        x, y, z, color, opacity, mask, vals, z_raw, cm, cmr = _make_surface_args()
        viewport.update_surface("cell-B", x, y, z, color, opacity, mask, vals, z_raw, cm, cmr)
        assert count[0] == 0, "fit_camera must not fire when scene is non-empty"

    def test_fit_does_not_fire_for_duplicate_uuid(self, viewport):
        """Duplicating a cell creates a new UUID; since scene is non-empty, no fit_camera."""
        viewport._seen_cell_ids.clear()
        viewport._seen_cell_ids.add("original-cell")
        count = _install_fit_counter(viewport)
        x, y, z, color, opacity, mask, vals, z_raw, cm, cmr = _make_surface_args()
        viewport.update_surface("duplicate-new-uuid", x, y, z, color, opacity, mask, vals, z_raw, cm, cmr)
        assert count[0] == 0, "duplicate cell must not trigger fit_camera"

    def test_fit_does_not_fire_for_already_seen_cell(self, viewport):
        viewport._seen_cell_ids.clear()
        viewport._seen_cell_ids.add("cell-A")
        count = _install_fit_counter(viewport)
        x, y, z, color, opacity, mask, vals, z_raw, cm, cmr = _make_surface_args()
        viewport.update_surface("cell-A", x, y, z, color, opacity, mask, vals, z_raw, cm, cmr)
        assert count[0] == 0, "re-rendering a seen cell must not trigger fit_camera"

    def test_session_prepopulate_blocks_fit(self, viewport):
        """Simulates _on_open: pre-populating _seen_cell_ids prevents fit_camera on play."""
        session_ids = {"cell-1", "cell-2", "cell-3"}
        viewport._seen_cell_ids.clear()
        viewport._seen_cell_ids.update(session_ids)
        count = _install_fit_counter(viewport)
        x, y, z, color, opacity, mask, vals, z_raw, cm, cmr = _make_surface_args()
        for cid in session_ids:
            viewport.update_surface(cid, x, y, z, color, opacity, mask, vals, z_raw, cm, cmr)
        assert count[0] == 0, "session cells must not trigger fit_camera after pre-populate"

    def test_new_cell_after_session_does_not_fit(self, viewport):
        """Adding a new user cell after a loaded session must not re-fit the camera."""
        viewport._seen_cell_ids.clear()
        viewport._seen_cell_ids.update({"cell-1", "cell-2"})
        count = _install_fit_counter(viewport)
        x, y, z, color, opacity, mask, vals, z_raw, cm, cmr = _make_surface_args()
        viewport.update_surface("brand-new-cell", x, y, z, color, opacity, mask, vals, z_raw, cm, cmr)
        assert count[0] == 0
