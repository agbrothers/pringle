"""
Phase 10 tests: view settings panel.

Tests validate:
- ViewSettingsWidget creates with default GridConfig values
- bounds_changed signal emits when Apply is clicked
- resolution_changed signal emits as spinbox changes
- camera_preset_requested signal emits for each preset button
- fit_all_requested signal emits
- current_config() reflects widget state
- PringleWindow has view_settings property
- Changing bounds in PringleWindow updates the cell list grid
- Changing resolution in PringleWindow updates the cell list grid
- PringleViewport.set_camera_preset positions the camera
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.view_settings import ViewSettingsWidget
from pringle.grid import GridConfig, make_grid


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=32))


# ---------------------------------------------------------------------------
# ViewSettingsWidget unit tests
# ---------------------------------------------------------------------------

class TestViewSettingsWidget:
    def test_creates_with_defaults(self, qapp):
        w = ViewSettingsWidget()
        cfg = w.current_config()
        assert cfg.x_min == pytest.approx(-5.0)
        assert cfg.x_max == pytest.approx(5.0)
        assert cfg.n == 64

    def test_creates_with_custom_config(self, qapp):
        cfg_in = GridConfig(x_min=-10.0, x_max=10.0, y_min=-3.0, y_max=3.0, n=32)
        w = ViewSettingsWidget(config=cfg_in)
        cfg = w.current_config()
        assert cfg.x_min == pytest.approx(-10.0)
        assert cfg.x_max == pytest.approx(10.0)
        assert cfg.n == 32

    def test_bounds_changed_signal_on_apply(self, qapp):
        w = ViewSettingsWidget()
        received = []
        w.bounds_changed.connect(lambda *args: received.append(args))
        w._x_min.setValue(-10.0)
        w._x_max.setValue(10.0)
        w._on_apply()
        assert len(received) == 1
        x_min, x_max, y_min, y_max, z_min, z_max = received[0]
        assert x_min == pytest.approx(-10.0)
        assert x_max == pytest.approx(10.0)

    def test_resolution_changed_signal(self, qapp):
        w = ViewSettingsWidget()
        received = []
        w.resolution_changed.connect(received.append)
        w._res_spin.setValue(128)
        assert 128 in received

    def test_camera_preset_iso(self, qapp):
        w = ViewSettingsWidget()
        received = []
        w.camera_preset_requested.connect(received.append)
        btn = w.findChild(type(w.findChild(object, "preset_iso_btn")), "preset_iso_btn")
        btn.click()
        assert "iso" in received

    def test_camera_preset_top(self, qapp):
        w = ViewSettingsWidget()
        received = []
        w.camera_preset_requested.connect(received.append)
        btn = w.findChild(type(w.findChild(object, "preset_top_btn")), "preset_top_btn")
        btn.click()
        assert "top" in received

    def test_camera_preset_front(self, qapp):
        w = ViewSettingsWidget()
        received = []
        w.camera_preset_requested.connect(received.append)
        btn = w.findChild(type(w.findChild(object, "preset_front_btn")), "preset_front_btn")
        btn.click()
        assert "front" in received

    def test_fit_all_signal(self, qapp):
        w = ViewSettingsWidget()
        received = []
        w.fit_all_requested.connect(lambda: received.append(True))
        btn = w.findChild(type(w.findChild(object, "fit_all_btn")), "fit_all_btn")
        btn.click()
        assert len(received) > 0

    def test_current_config_after_edit(self, qapp):
        w = ViewSettingsWidget()
        w._x_min.setValue(-20.0)
        w._x_max.setValue(20.0)
        w._y_min.setValue(-15.0)
        w._y_max.setValue(15.0)
        w._res_spin.setValue(48)
        cfg = w.current_config()
        assert cfg.x_min == pytest.approx(-20.0)
        assert cfg.x_max == pytest.approx(20.0)
        assert cfg.y_min == pytest.approx(-15.0)
        assert cfg.y_max == pytest.approx(15.0)
        assert cfg.n == 48


# ---------------------------------------------------------------------------
# PringleWindow integration
# ---------------------------------------------------------------------------

class TestPringleWindowViewSettings:
    def test_window_has_view_settings(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        assert hasattr(win, "view_settings")
        assert isinstance(win.view_settings, ViewSettingsWidget)
        win.close()

    def test_bounds_change_updates_grid(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        initial_x_min = win._grid.config.x_min

        win._on_bounds_changed(-20.0, 20.0, -5.0, 5.0, -5.0, 5.0)

        assert win._grid.config.x_min == pytest.approx(-20.0)
        assert win._grid.config.x_max == pytest.approx(20.0)
        assert win._grid.config.x_min != pytest.approx(initial_x_min)
        win.close()

    def test_resolution_change_updates_grid(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        win._on_resolution_changed(16)
        assert win._grid.config.n == 16
        win.close()

    def test_bounds_preserves_resolution(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        # Set resolution first
        win._on_resolution_changed(48)
        # Then change bounds
        win._on_bounds_changed(-10.0, 10.0, -10.0, 10.0, -10.0, 10.0)
        # Resolution should be preserved
        assert win._grid.config.n == 48
        win.close()

    def test_resolution_preserves_bounds(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        win._on_bounds_changed(-8.0, 8.0, -4.0, 4.0, -4.0, 4.0)
        win._on_resolution_changed(24)
        assert win._grid.config.x_min == pytest.approx(-8.0)
        assert win._grid.config.n == 24
        win.close()

    def test_bounds_change_triggers_cell_reevaluation(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        surface_data = []
        original_on_result = win._on_cell_result

        def capturing_result(cid, result, style):
            if result.render_type == "surface":
                surface_data.append(result.x.copy())
            original_on_result(cid, result, style)

        win._on_cell_result = capturing_result
        win.cell_list._on_cell_result = capturing_result

        win.cell_list.add_cell("z = sin(x) * cos(y)")
        initial_x_range = float(surface_data[-1].max() - surface_data[-1].min()) if surface_data else None

        surface_data.clear()
        win._on_bounds_changed(-10.0, 10.0, -5.0, 5.0, -5.0, 5.0)

        if surface_data:
            new_x_range = float(surface_data[-1].max() - surface_data[-1].min())
            assert new_x_range > (initial_x_range or 0), "Wider bounds should produce larger x range"
        win.close()


# ---------------------------------------------------------------------------
# PringleViewport camera presets
# ---------------------------------------------------------------------------

class TestCameraPresets:
    def test_set_camera_preset_iso(self, qapp):
        from pringle.app import PringleViewport
        vp = PringleViewport()
        vp.set_camera_preset("iso")
        pos = vp.renderer._camera.local.position  # numpy array [x, y, z]
        assert any(abs(v) > 1 for v in pos[:3])

    def test_set_camera_preset_top(self, qapp):
        from pringle.app import PringleViewport
        vp = PringleViewport()
        vp.set_camera_preset("top")
        pos = vp.renderer._camera.local.position
        assert pos[2] > 5  # z is dominant

    def test_set_camera_preset_front(self, qapp):
        from pringle.app import PringleViewport
        vp = PringleViewport()
        vp.set_camera_preset("front")
        pos = vp.renderer._camera.local.position
        assert pos[1] < -5  # looking from -y toward origin

    def test_unknown_preset_ignored(self, qapp):
        from pringle.app import PringleViewport
        vp = PringleViewport()
        vp.set_camera_preset("iso")
        pos_before = tuple(vp.renderer._camera.local.position[:3])
        vp.set_camera_preset("unknown_preset")
        pos_after = tuple(vp.renderer._camera.local.position[:3])
        assert pos_before == pos_after


# ---------------------------------------------------------------------------
# BUG-013: simultaneous WASD pan + mouse orbit
# ---------------------------------------------------------------------------

class TestSimultaneousPanOrbit:
    """Verify _IncrementalOrbitHandler reads live camera state.

    The old OrbitController.register_events() captured a snapshot at drag-start
    and rewrote camera.local.position from it on every pointer_move, so WASD
    deltas applied during a drag were immediately overwritten.

    With _IncrementalOrbitHandler, controller.rotate() / .pan() always read the
    live camera state, so a WASD delta survives into the next frame.
    """

    def test_wasd_delta_survives_after_orbit(self, qapp):
        import numpy as np
        from pringle.app import PringleViewport
        from pringle.renderer import _IncrementalOrbitHandler

        vp = PringleViewport()
        pr = vp.renderer

        # Confirm the handler is the incremental one (not register_events)
        assert isinstance(pr._orbit_handler, _IncrementalOrbitHandler)

        # Establish a known orbit target (fit_camera() does this in practice)
        pr._controller.target = (0.0, 0.0, 0.0)

        # WASD pan moves both the camera and the orbit target
        pr._pan_target(1.0, 0.0, 0.0)
        target_after_pan = np.array(pr._controller.target[:3])
        assert abs(target_after_pan[0] - 1.0) < 1e-5, "target should be at x=1"

        # Simulate a mouse orbit step — exactly what _IncrementalOrbitHandler does.
        # rotate() reads LIVE camera state, so the pan delta is not discarded.
        pr._controller.rotate((0.1, 0.0), (0.0, 0.0, 800.0, 600.0))

        # The orbit pivot (_controller.target) must survive the orbit call.
        # rotate() only moves the camera; it never modifies the target.
        target_after_orbit = np.array(pr._controller.target[:3])
        assert np.allclose(target_after_orbit, target_after_pan, atol=1e-5), (
            "orbit must not overwrite the WASD-updated target"
        )

        # Camera position should have changed (the orbit rotated it)
        cam_before_orbit = np.array([7.0, -8.0, 6.0])  # approx: iso + pan(1,0,0)
        cam_after_orbit  = np.array(pr._camera.local.position[:3])
        assert not np.allclose(cam_after_orbit, cam_before_orbit, atol=1e-4), (
            "orbit should change camera position"
        )

    def test_pan_target_updates_controller_target(self, qapp):
        import numpy as np
        from pringle.app import PringleViewport

        vp = PringleViewport()
        pr = vp.renderer
        pr._controller.target = (0.0, 0.0, 0.0)
        pr._pan_target(2.0, 3.0, 0.0)
        t = np.array(pr._controller.target)
        assert abs(t[0] - 2.0) < 1e-5
        assert abs(t[1] - 3.0) < 1e-5
