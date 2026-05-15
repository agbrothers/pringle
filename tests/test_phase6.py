"""
Phase 6 tests: slider cells.

Tests validate:
- SliderWidget structure, signals, and animation
- CellListWidget detects slider source and creates SliderWidget
- Slider value injected into shared namespace
- Downstream surface cell evaluates with slider value
- Slider value change triggers downstream re-evaluation
- Slider delete removes from namespace
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.slider_widget import SliderWidget
from pringle.cell_list import CellListWidget
from pringle.style import CellStyle
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=32))


# ---------------------------------------------------------------------------
# SliderWidget unit tests
# ---------------------------------------------------------------------------

class TestSliderWidget:
    def test_creates(self, qapp):
        s = SliderWidget(name="a", value=3.0, min_val=0.0, max_val=10.0)
        assert s.name == "a"
        assert s.value == pytest.approx(3.0)
        assert s.cell_id != ""

    def test_source(self, qapp):
        s = SliderWidget(name="k", value=2.5)
        assert s.source() == "k = 2.5"

    def test_is_visible_cell(self, qapp):
        s = SliderWidget(name="a", value=1.0)
        assert s.is_visible_cell() is True

    def test_focus_noop(self, qapp):
        s = SliderWidget(name="a", value=1.0)
        s.focus()  # should not raise

    def test_diagnostics_noop(self, qapp):
        s = SliderWidget(name="a", value=1.0)
        s.set_error("oops")
        s.set_warning("hmm")
        s.clear_diagnostics()  # all should be no-ops without raising

    def test_set_value_clamps(self, qapp):
        s = SliderWidget(name="a", value=5.0, min_val=0.0, max_val=10.0)
        s.set_value(15.0, emit=False)
        assert s.value == pytest.approx(10.0)
        s.set_value(-5.0, emit=False)
        assert s.value == pytest.approx(0.0)

    def test_value_changed_signal(self, qapp):
        s = SliderWidget(name="a", value=1.0, min_val=0.0, max_val=10.0)
        received: list[tuple[str, float]] = []
        s.value_changed.connect(lambda n, v: received.append((n, v)))
        s.set_value(3.0)
        assert len(received) == 1
        assert received[0] == ("a", pytest.approx(3.0))

    def test_value_changed_no_emit(self, qapp):
        s = SliderWidget(name="a", value=1.0)
        received: list = []
        s.value_changed.connect(received.append)
        s.set_value(3.0, emit=False)
        assert len(received) == 0

    def test_delete_requested_signal(self, qapp):
        s = SliderWidget(name="a", value=1.0)
        received: list[str] = []
        s.delete_requested.connect(received.append)
        s._delete_btn.click()
        assert len(received) == 1
        assert received[0] == s.cell_id

    def test_play_pause_animation(self, qapp):
        s = SliderWidget(name="a", value=0.0, min_val=0.0, max_val=10.0)
        assert not s._anim_timer.isActive()
        s._play_btn.setChecked(True)
        s._on_play_toggled(True)
        assert s._anim_timer.isActive()
        s._on_play_toggled(False)
        assert not s._anim_timer.isActive()

    def test_anim_tick_bounces(self, qapp):
        s = SliderWidget(name="a", value=9.99, min_val=0.0, max_val=10.0)
        s._anim_dir = 1
        s._anim_tick()
        assert s.value == pytest.approx(10.0)
        assert s._anim_dir == -1  # bounced

    def test_range_change_repositions_slider(self, qapp):
        s = SliderWidget(name="a", value=5.0, min_val=0.0, max_val=10.0)
        s._min_box.setValue(0.0)
        s._max_box.setValue(20.0)
        s._on_range_changed()
        assert s._min == pytest.approx(0.0)
        assert s._max == pytest.approx(20.0)
        # Value should still be 5.0 (within new range)
        assert s.value == pytest.approx(5.0)

    def test_unique_cell_ids(self, qapp):
        a = SliderWidget(name="a", value=1.0)
        b = SliderWidget(name="b", value=1.0)
        assert a.cell_id != b.cell_id

    def test_custom_cell_id(self, qapp):
        s = SliderWidget(name="a", value=1.0, cell_id="my-id")
        assert s.cell_id == "my-id"


# ---------------------------------------------------------------------------
# CellListWidget slider integration
# ---------------------------------------------------------------------------

class TestCellListSlider:
    def _make_list(self, qapp, grid):
        results = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: results.append((cid, r, s)),
            grid=grid,
        )
        return clist, results

    def test_slider_source_creates_slider_widget(self, qapp, grid):
        clist, _ = self._make_list(qapp, grid)
        cell = clist.add_cell("a = 2.0")
        assert isinstance(cell, SliderWidget)
        assert cell.name == "a"
        assert cell.value == pytest.approx(2.0)

    def test_non_slider_source_creates_cell_widget(self, qapp, grid):
        from pringle.cell_widget import CellWidget
        clist, _ = self._make_list(qapp, grid)
        cell = clist.add_cell("z = sin(x)")
        assert isinstance(cell, CellWidget)

    def test_slider_in_cells_list(self, qapp, grid):
        clist, _ = self._make_list(qapp, grid)
        cell = clist.add_cell("k = 3.0")
        assert clist._cells[0] is cell

    def test_slider_value_in_namespace(self, qapp, grid):
        clist, _ = self._make_list(qapp, grid)
        clist.add_cell("a = 5.0")
        assert "a" in clist._shared_ns
        assert clist._shared_ns["a"] == pytest.approx(5.0)

    def test_slider_not_rendered(self, qapp, grid):
        """Slider cells don't produce render callbacks."""
        clist, results = self._make_list(qapp, grid)
        clist.add_cell("a = 2.0")
        # No result should have been passed to the viewport callback for a slider
        assert all(cid != clist._cells[0].cell_id for cid, _, _ in results)

    def test_downstream_uses_slider_value(self, qapp, grid):
        """Surface cell evaluates correctly using slider value."""
        import numpy as np
        captured = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: captured.append((cid, r, s)),
            grid=grid,
        )
        clist.add_cell("a = 3.0")
        clist.add_cell("z = a * sin(x) * cos(y)")

        surface_results = [(cid, r) for cid, r, _ in captured if r.render_type == "surface"]
        assert len(surface_results) > 0
        _, surf = surface_results[-1]
        assert surf.data is not None
        # Peak value should be ~3.0 (a * 1 * 1 at x≈π/2, y≈0)
        assert np.max(np.abs(surf.data)) == pytest.approx(3.0, abs=0.2)

    def test_slider_change_triggers_downstream(self, qapp, grid):
        """Changing a slider value re-evaluates downstream cells."""
        import numpy as np
        surface_data = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: surface_data.append(r.data)
            if r.render_type == "surface" else None,
            grid=grid,
        )
        slider = clist.add_cell("a = 1.0")
        clist.add_cell("z = a * sin(x) * cos(y)")

        surface_data.clear()
        slider.set_value(4.0)  # emits value_changed → _rebuild_namespace

        assert len(surface_data) > 0
        # Max value should now be ~4.0
        assert np.max(np.abs(surface_data[-1])) == pytest.approx(4.0, abs=0.3)

    def test_slider_delete_removes_from_namespace(self, qapp, grid):
        clist, _ = self._make_list(qapp, grid)
        slider = clist.add_cell("b = 7.0")
        assert "b" in clist._shared_ns
        clist.remove_cell(slider.cell_id)
        assert "b" not in clist._shared_ns

    def test_slider_and_cell_ordering(self, qapp, grid):
        """Slider inserted after another cell maintains correct order."""
        clist, _ = self._make_list(qapp, grid)
        c1 = clist.add_cell("z = sin(x)")
        sl = clist.add_cell("a = 1.0", after_id=c1.cell_id)
        c2 = clist.add_cell("z = cos(x)")
        assert clist._cells.index(c1) == 0
        assert clist._cells.index(sl) == 1
        assert clist._cells.index(c2) == 2

    def test_multiple_sliders(self, qapp, grid):
        """Multiple slider cells all inject into namespace."""
        clist, _ = self._make_list(qapp, grid)
        clist.add_cell("a = 2.0")
        clist.add_cell("b = 3.0")
        clist.add_cell("z = a + b")
        assert clist._shared_ns.get("a") == pytest.approx(2.0)
        assert clist._shared_ns.get("b") == pytest.approx(3.0)
