"""
Phase 11 tests: YAML session persistence.

Tests validate:
- cell_to_dict serialises equation, slider, and data cells correctly
- grid_config_to_dict / grid_config_from_dict round-trips
- save_session writes a valid YAML file
- load_session returns a dict with expected keys
- load_session raises ValueError on unknown version
- restore_cell_list rebuilds cells from saved data (equation, slider, sub-cells)
- Full round-trip: save then load produces equivalent cell list
- PringleWindow title reflects unsaved-changes state (_mark_modified / _update_title)
- _on_new clears cells and resets session path
- _write_session updates _session_path and clears _modified
"""

import sys
import pytest
import tempfile
import os

from PyQt6.QtWidgets import QApplication

from pringle.grid import GridConfig, make_grid
from pringle.session import (
    cell_to_dict,
    grid_config_to_dict,
    grid_config_from_dict,
    save_session,
    load_session,
    restore_cell_list,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=16))


def _noop_result(cid, result, style):
    pass


@pytest.fixture
def cell_list(qapp, grid):
    from pringle.cell_list import CellListWidget
    return CellListWidget(on_cell_result=_noop_result, grid=grid)


# ---------------------------------------------------------------------------
# cell_to_dict
# ---------------------------------------------------------------------------

class TestCellToDict:
    def test_equation_cell_type(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("z = x + y")
        d = cell_to_dict(cell)
        assert d["type"] == "equation"
        assert d["source"] == "z = x + y"
        assert "color" in d["style"]
        assert "visible" in d

    def test_equation_cell_has_cell_id(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("z = 0")
        d = cell_to_dict(cell)
        assert d["id"] == cell.cell_id

    def test_equation_cell_sub_cells(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("z = x")
        cell.add_sub_cell("constraint")
        cell._sub_cells[-1]._edit.setPlainText("x > 0")
        d = cell_to_dict(cell)
        assert len(d["sub_cells"]) == 1
        assert d["sub_cells"][0]["type"] == "constraint"
        assert d["sub_cells"][0]["source"] == "x > 0"

    def test_slider_cell_type(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("a = 3.0")
        d = cell_to_dict(cell)
        assert d["type"] == "slider"
        assert "value" in d
        assert "min_val" in d
        assert "max_val" in d
        assert d["sub_cells"] == []

    def test_slider_cell_value(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("k = 7.5")
        d = cell_to_dict(cell)
        assert pytest.approx(d["value"]) == 7.5

    def test_color_serialized_as_list(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("z = 0")
        d = cell_to_dict(cell)
        assert isinstance(d["style"]["color"], list)
        assert len(d["style"]["color"]) == 4


# ---------------------------------------------------------------------------
# GridConfig round-trip
# ---------------------------------------------------------------------------

class TestGridConfigSerialization:
    def test_round_trip(self):
        cfg = GridConfig(x_min=-3.0, x_max=3.0, y_min=-2.0, y_max=2.0, n=32)
        d = grid_config_to_dict(cfg)
        restored = grid_config_from_dict(d)
        assert restored.x_min == pytest.approx(-3.0)
        assert restored.x_max == pytest.approx(3.0)
        assert restored.y_min == pytest.approx(-2.0)
        assert restored.y_max == pytest.approx(2.0)
        assert restored.n == 32

    def test_defaults_on_empty_dict(self):
        cfg = grid_config_from_dict({})
        assert cfg.x_min == pytest.approx(-5.0)
        assert cfg.n == 64


# ---------------------------------------------------------------------------
# save_session / load_session
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_save_creates_file(self, qapp, grid, cell_list):
        cell_list.add_cell("z = sin(x)")
        with tempfile.NamedTemporaryFile(suffix=".pringle", delete=False) as f:
            path = f.name
        try:
            save_session(path, cell_list, grid.config)
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
        finally:
            os.unlink(path)

    def test_load_returns_dict(self, qapp, grid, cell_list):
        with tempfile.NamedTemporaryFile(suffix=".pringle", delete=False) as f:
            path = f.name
        try:
            save_session(path, cell_list, grid.config)
            data = load_session(path)
            assert isinstance(data, dict)
            assert "version" in data
            assert "grid" in data
            assert "cells" in data
        finally:
            os.unlink(path)

    def test_load_unknown_version_raises(self, qapp, grid, cell_list):
        import yaml
        with tempfile.NamedTemporaryFile(
            suffix=".pringle", delete=False, mode="w"
        ) as f:
            yaml.dump({"version": 99, "grid": {}, "cells": []}, f)
            path = f.name
        try:
            with pytest.raises(ValueError, match="Unsupported"):
                load_session(path)
        finally:
            os.unlink(path)

    def test_cells_preserved_in_file(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.add_cell("z = x * y")
        cl.add_cell("a = 2.5")

        with tempfile.NamedTemporaryFile(suffix=".pringle", delete=False) as f:
            path = f.name
        try:
            save_session(path, cl, grid.config)
            data = load_session(path)
            sources = [c["source"] for c in data["cells"]]
            assert "z = x * y" in sources
            assert any("2.5" in s for s in sources)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# restore_cell_list
# ---------------------------------------------------------------------------

class TestRestoreCellList:
    def test_restores_equation_cell(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cells_data = [{"type": "equation", "source": "z = x + y",
                       "style": {"color": [0.2, 0.4, 0.8, 1.0]},
                       "visible": True, "sub_cells": []}]
        restore_cell_list(cl, cells_data)
        assert len(cl._cells) == 1
        assert cl._cells[0].source() == "z = x + y"

    def test_restores_slider_cell(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cells_data = [{"type": "slider", "source": "a = 5.0",
                       "style": {"color": [0.2, 0.4, 0.8, 1.0]},
                       "name": "a", "value": 5.0,
                       "min_val": 0.0, "max_val": 10.0,
                       "sub_cells": []}]
        restore_cell_list(cl, cells_data)
        assert len(cl._cells) == 1
        assert isinstance(cl._cells[0], SliderWidget)
        assert pytest.approx(cl._cells[0].value) == 5.0

    def test_restore_clears_existing(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.add_cell("z = 0")
        cl.add_cell("z = 1")
        restore_cell_list(cl, [])
        assert len(cl._cells) == 0

    def test_restores_sub_cells(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        from pringle.cell_widget import CellWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cells_data = [{
            "type": "equation",
            "source": "z = x",
            "style": {"color": [0.2, 0.4, 0.8, 1.0]},
            "visible": True,
            "sub_cells": [{"type": "constraint", "source": "x > 0"}],
        }]
        restore_cell_list(cl, cells_data)
        cell = cl._cells[0]
        assert isinstance(cell, CellWidget)
        assert len(cell._sub_cells) == 1
        assert cell._sub_cells[0].source() == "x > 0"

    def test_restores_visibility_false(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cells_data = [{
            "type": "equation",
            "source": "z = y",
            "style": {"color": [0.2, 0.4, 0.8, 1.0]},
            "visible": False,
            "sub_cells": [],
        }]
        restore_cell_list(cl, cells_data)
        assert not cl._cells[0].is_visible_cell()

    def test_restores_slider_range(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cells_data = [{"type": "slider", "source": "b = 3.0",
                       "style": {"color": [0.2, 0.4, 0.8, 1.0]},
                       "name": "b", "value": 3.0,
                       "min_val": -5.0, "max_val": 5.0,
                       "sub_cells": []}]
        restore_cell_list(cl, cells_data)
        slider = cl._cells[0]
        assert isinstance(slider, SliderWidget)
        assert pytest.approx(slider._min) == -5.0
        assert pytest.approx(slider._max) == 5.0


# ---------------------------------------------------------------------------
# Full round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_equation_round_trip(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl_orig = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl_orig.add_cell("z = cos(x) * sin(y)")

        with tempfile.NamedTemporaryFile(suffix=".pringle", delete=False) as f:
            path = f.name
        try:
            save_session(path, cl_orig, grid.config)
            data = load_session(path)
            cl_new = CellListWidget(on_cell_result=_noop_result, grid=grid)
            restore_cell_list(cl_new, data["cells"])
            assert len(cl_new._cells) == 1
            assert cl_new._cells[0].source() == "z = cos(x) * sin(y)"
        finally:
            os.unlink(path)

    def test_mixed_cell_round_trip(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget
        cl_orig = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl_orig.add_cell("k = 2.0")
        cl_orig.add_cell("z = k * x")

        with tempfile.NamedTemporaryFile(suffix=".pringle", delete=False) as f:
            path = f.name
        try:
            save_session(path, cl_orig, grid.config)
            data = load_session(path)
            cl_new = CellListWidget(on_cell_result=_noop_result, grid=grid)
            restore_cell_list(cl_new, data["cells"])
            assert len(cl_new._cells) == 2
            assert isinstance(cl_new._cells[0], SliderWidget)
            assert cl_new._cells[1].source() == "z = k * x"
        finally:
            os.unlink(path)

    def test_grid_config_round_trip(self, qapp):
        from pringle.cell_list import CellListWidget
        cfg = GridConfig(x_min=-10.0, x_max=10.0, y_min=-4.0, y_max=4.0, n=32)
        g = make_grid(cfg)
        cl = CellListWidget(on_cell_result=_noop_result, grid=g)

        with tempfile.NamedTemporaryFile(suffix=".pringle", delete=False) as f:
            path = f.name
        try:
            save_session(path, cl, cfg)
            data = load_session(path)
            restored_cfg = grid_config_from_dict(data["grid"])
            assert restored_cfg.x_min == pytest.approx(-10.0)
            assert restored_cfg.n == 32
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# PringleWindow session state
# ---------------------------------------------------------------------------

class TestPringleWindowSession:
    @pytest.fixture(autouse=True)
    def _auto_discard(self, monkeypatch):
        """Keep the modal 'Unsaved changes' dialog from blocking headless runs.

        `_on_new` / `_on_open` call `_confirm_discard`, which runs `QDialog.exec()`
        — a modal that blocks the event loop until a button is clicked. On a
        modified session this hangs the suite waiting for input that never comes.
        No test drives that dialog, so patch it to proceed as if "Discard" was
        chosen.
        """
        from pringle.app import PringleWindow
        monkeypatch.setattr(PringleWindow, "_confirm_discard", lambda self: True)

    def test_initial_title_is_untitled(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        assert "pringle" in win.windowTitle().lower()
        win.close()

    def test_mark_modified_adds_asterisk(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        assert not win._modified
        win._mark_modified()
        assert win._modified
        assert "*" in win.windowTitle()
        win.close()

    def test_write_session_clears_modified(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        win._mark_modified()
        with tempfile.NamedTemporaryFile(suffix=".pringle", delete=False) as f:
            path = f.name
        try:
            win._write_session(path)
            assert not win._modified
            assert win._session_path == path
            assert "*" not in win.windowTitle()
        finally:
            os.unlink(path)
        win.close()

    def test_on_new_clears_cells(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        win.cell_list.add_cell("z = x")
        win._on_new()
        assert len(win.cell_list._cells) == 0
        win.close()

    def test_on_new_resets_session_path(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        win._session_path = "/tmp/fake.pringle"
        win._modified = False
        win._on_new()
        assert win._session_path is None
        win.close()
