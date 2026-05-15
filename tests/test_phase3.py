"""
Phase 3 tests: Qt + pygfx integration.

Structural tests (no GPU required) validate the widget tree and class
hierarchy.  The full interactive rendering test requires a native display
and is marked accordingly — run it manually with:

    python -m pringle.app

The offscreen rendering from Phase 1+2 already proves the GPU pipeline
works.  Phase 3 proves the Qt widget wrapping is correct.
"""

import sys
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# Structural tests — no display required
# ---------------------------------------------------------------------------

def test_imports():
    """All Phase 3 modules import without error."""
    import PyQt6  # noqa: F401
    from pringle.app import PringleWindow, PringleViewport, LeftPanelPlaceholder, launch
    assert PringleWindow is not None


def test_viewport_is_qwidget():
    """PringleViewport is a proper QWidget subclass."""
    import PyQt6  # noqa: F401
    from rendercanvas.qt import QRenderWidget
    from pringle.app import PringleViewport
    assert issubclass(PringleViewport, QRenderWidget)


def test_window_subclass():
    """PringleWindow is a QMainWindow subclass."""
    from PyQt6.QtWidgets import QMainWindow
    from pringle.app import PringleWindow
    assert issubclass(PringleWindow, QMainWindow)


# ---------------------------------------------------------------------------
# Qt widget tests — require QApplication (but no GPU)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    """Module-scoped QApplication for Qt widget tests."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_window_creates(qapp):
    """PringleWindow instantiates and has the expected layout."""
    from PyQt6.QtWidgets import QSplitter
    from pringle.app import PringleWindow
    win = PringleWindow()
    assert win.windowTitle() == "pringle"
    # Central widget should be a splitter
    assert isinstance(win.centralWidget(), QSplitter)
    win.close()


def test_window_has_viewport(qapp):
    """PringleWindow exposes a viewport property."""
    from pringle.app import PringleWindow, PringleViewport
    win = PringleWindow()
    assert isinstance(win.viewport, PringleViewport)
    win.close()


def test_splitter_proportions(qapp):
    """Splitter has two panels; viewport is configured wider than left panel."""
    from pringle.app import PringleWindow
    win = PringleWindow()
    win.resize(1400, 900)
    win.show()
    qapp.processEvents()  # let Qt compute layout
    sizes = win.centralWidget().sizes()
    assert len(sizes) == 2
    assert sizes[0] >= 260, f"Left panel too narrow: {sizes[0]}"
    assert sizes[1] > sizes[0], "Viewport should be wider than left panel"
    win.close()


def test_add_remove_object(qapp):
    """add_object / remove_object on viewport don't raise."""
    import pygfx as gfx
    from pringle.app import PringleWindow
    from pringle.renderer import make_surface_mesh
    import numpy as np

    win = PringleWindow()
    n = 16
    x1d = np.linspace(-2, 2, n, dtype=np.float32)
    x, y = np.meshgrid(x1d, x1d)
    z = np.sin(x) * np.cos(y)

    mesh = make_surface_mesh(x, y, z)
    win.viewport.add_object("test", mesh)
    win.viewport.remove_object("test")
    win.close()


def test_evalulate_and_add(qapp):
    """Full pipeline: evaluate an expression and add the result to viewport."""
    from pringle.app import PringleWindow
    from pringle.renderer import make_surface_mesh
    from pringle.grid import GridConfig, make_grid
    from pringle.evaluator import run_cell

    win = PringleWindow()
    grid = make_grid(GridConfig(n=32))
    result = run_cell("z = sin(x) * cos(y)", {}, grid)

    assert result.render_type == "surface"
    mesh = make_surface_mesh(result.x, result.y, result.data)
    win.viewport.add_object("cell-1", mesh)
    assert "cell-1" in win.viewport.renderer._objects
    win.close()
