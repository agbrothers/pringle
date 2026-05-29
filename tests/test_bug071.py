"""
BUG-071: LinAlgError crash when arrow field has zero-length vectors with colormap/vertex_colors.

make_arrow_mesh must filter degenerate (zero-length) arrows before passing transforms to
_merge_colored_mesh, which inverts the 3x3 rotation block and crashes on singular matrices.
"""

from __future__ import annotations

import numpy as np
import pytest


class TestDegenerateArrowsColoredPath:
    """No GPU required — None is returned before any gfx object is constructed."""

    def test_all_degenerate_colormap_returns_none(self):
        from pringle.renderer import make_arrow_mesh
        arrows = np.zeros((5, 6), dtype=np.float32)  # all tails == heads
        result = make_arrow_mesh(arrows, colormap="viridis")
        assert result is None

    def test_all_degenerate_vertex_colors_returns_none(self):
        from pringle.renderer import make_arrow_mesh
        arrows = np.zeros((5, 6), dtype=np.float32)
        colors = np.ones((5, 4), dtype=np.float32)
        result = make_arrow_mesh(arrows, vertex_colors=colors)
        assert result is None

    def test_flat_color_path_unaffected(self):
        """InstancedMesh path (no colormap) must still work with degenerate arrows."""
        import pygfx as gfx
        from pringle.renderer import make_arrow_mesh
        arrows = np.zeros((3, 6), dtype=np.float32)
        result = make_arrow_mesh(arrows)  # flat color — no colormap
        assert isinstance(result, gfx.InstancedMesh)
