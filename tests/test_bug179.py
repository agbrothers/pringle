"""
BUG-179 — Resolution spinbox shows stale default (64) after session load.

Root cause: _on_open rebuilt the grid from cfg.n but never pushed cfg.n to
_res_spin, so the spinbox always showed the widget-init default of 64.

Fix: after set_bounds(), update _res_spin with blockSignals so the grid is
not rebuilt a second time.
"""

import sys
import importlib.resources
import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


class TestResolutionSpinboxOnLoad:
    def test_memory_yml_shows_128(self, qapp):
        """Loading memory.yml (n=128) must display 128 in the resolution spinbox."""
        from pringle.app import PringleWindow
        win = PringleWindow()
        examples_dir = str(importlib.resources.files("pringle") / "examples")
        path = f"{examples_dir}/memory.yml"
        from pringle.session import load_session, restore_cell_list
        from pringle.session import grid_config_from_dict
        from pringle.grid import make_grid
        data = load_session(path)
        cfg = grid_config_from_dict(data["grid"])
        win._grid = make_grid(cfg)
        win._cell_list.update_grid(win._grid)
        win._view_settings.set_bounds(
            cfg.x_min, cfg.x_max, cfg.y_min, cfg.y_max, cfg.z_min, cfg.z_max
        )
        win._view_settings._res_spin.blockSignals(True)
        win._view_settings._res_spin.setValue(cfg.n)
        win._view_settings._res_spin.blockSignals(False)
        assert win._view_settings._res_spin.value() == 128

    def test_spinbox_reflects_loaded_n(self, qapp):
        """_res_spin.value() must equal cfg.n after the load sequence."""
        from pringle.view_settings import ViewSettingsWidget
        from pringle.session import load_session, grid_config_from_dict
        import importlib.resources
        examples_dir = str(importlib.resources.files("pringle") / "examples")
        data = load_session(f"{examples_dir}/memory.yml")
        cfg = grid_config_from_dict(data["grid"])
        w = ViewSettingsWidget()
        assert w._res_spin.value() == 64  # default before load
        w._res_spin.blockSignals(True)
        w._res_spin.setValue(cfg.n)
        w._res_spin.blockSignals(False)
        assert w._res_spin.value() == cfg.n

    def test_no_signal_emitted_during_load(self, qapp):
        """blockSignals must prevent resolution_changed from firing during load."""
        from pringle.view_settings import ViewSettingsWidget
        w = ViewSettingsWidget()
        received = []
        w.resolution_changed.connect(received.append)
        w._res_spin.blockSignals(True)
        w._res_spin.setValue(128)
        w._res_spin.blockSignals(False)
        assert received == [], "resolution_changed must not fire during blocked setValue"

    def test_spinbox_still_works_after_load(self, qapp):
        """Changing the spinbox after a load must still emit resolution_changed."""
        from pringle.view_settings import ViewSettingsWidget
        w = ViewSettingsWidget()
        received = []
        w.resolution_changed.connect(received.append)
        # Simulate load
        w._res_spin.blockSignals(True)
        w._res_spin.setValue(128)
        w._res_spin.blockSignals(False)
        # User changes spinbox post-load
        w._res_spin.setValue(32)
        assert received == [32]

    def test_session_without_grid_keeps_default(self, qapp):
        """A session with no grid block must not crash and must leave spinbox at 64."""
        from pringle.view_settings import ViewSettingsWidget
        w = ViewSettingsWidget()
        # No grid data — spinbox untouched
        assert w._res_spin.value() == 64
