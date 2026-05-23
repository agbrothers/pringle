"""
FEAT-045 tests: expression references in slider bounds and axis limits.

Tests validate:
- Typing a constant name (e.g. 'pi') into a slider min field resolves to the correct value
- Typing a slider name into a slider max field resolves from the namespace and updates via re_resolve
- Invalid expression causes red border flash and reverts to the previous value
- Array-valued expression is rejected (not a scalar)
- Session round-trip: save slider with max_expr="pi", reload, verify expr and value
- Old sessions without *_expr fields load cleanly with _raw_expr=None
- _make_resolver filters to scalar values only
- _ExprBox.setValue clears expression state
"""

import sys
import math
import tempfile
import os
import pytest
import numpy as np

from PyQt6.QtWidgets import QApplication

from pringle.grid import GridConfig, make_grid


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
# _ExprBox unit tests (no CellListWidget needed)
# ---------------------------------------------------------------------------

class TestExprBox:
    def test_initial_value_displayed_as_integer(self, qapp):
        from pringle.slider_widget import _ExprBox
        box = _ExprBox(5.0)
        assert box.text() == "5"
        assert box.value() == 5.0
        assert box.expr() is None

    def test_initial_value_displayed_as_float(self, qapp):
        from pringle.slider_widget import _ExprBox
        box = _ExprBox(0.1)
        assert box.text() == "0.1"
        assert box.value() == pytest.approx(0.1)

    def test_set_value_clears_expr(self, qapp):
        from pringle.slider_widget import _ExprBox
        box = _ExprBox(1.0)
        box._raw_expr = "pi"
        box.setValue(3.0)
        assert box.expr() is None
        assert box.text() == "3"
        assert box.value() == 3.0

    def test_commit_plain_float(self, qapp):
        from pringle.slider_widget import _ExprBox
        emitted = []
        box = _ExprBox(0.0)
        box.committed.connect(emitted.append)
        box.setText("7.5")
        box._on_commit()
        assert emitted == [7.5]
        assert box.value() == 7.5
        assert box.expr() is None

    def test_commit_expression_resolves_pi(self, qapp):
        from pringle.slider_widget import _ExprBox
        import math as _math
        emitted = []
        box = _ExprBox(0.0)
        box.committed.connect(emitted.append)
        box.set_resolve(lambda expr: _math.pi if expr == "pi" else None)
        box.setText("pi")
        box._on_commit()
        assert len(emitted) == 1
        assert emitted[0] == pytest.approx(_math.pi)
        assert box.expr() == "pi"
        assert box.value() == pytest.approx(_math.pi)

    def test_commit_invalid_expression_reverts(self, qapp):
        from pringle.slider_widget import _ExprBox
        emitted = []
        box = _ExprBox(3.0)
        box.committed.connect(emitted.append)
        box.set_resolve(lambda expr: None)
        box.setText("not_a_var")
        box._on_commit()
        assert emitted == []
        assert box.value() == 3.0
        assert box.expr() is None
        assert box.text() == "3"

    def test_commit_array_expression_rejected(self, qapp):
        from pringle.slider_widget import _ExprBox
        emitted = []
        box = _ExprBox(1.0)
        box.committed.connect(emitted.append)
        arr = np.array([1.0, 2.0, 3.0])
        box.set_resolve(lambda expr: arr if expr == "x" else None)
        box.setText("x")
        box._on_commit()
        # arrays are not scalar floats — should be rejected
        assert emitted == []
        assert box.value() == 1.0
        assert box.expr() is None

    def test_re_resolve_updates_last_valid(self, qapp):
        from pringle.slider_widget import _ExprBox
        emitted = []
        box = _ExprBox(0.0)
        box.committed.connect(emitted.append)
        box._raw_expr = "a"
        box._last_valid = 5.0
        resolver = lambda expr: 10.0 if expr == "a" else None
        box.re_resolve(resolver)
        assert box.value() == 10.0
        assert emitted == [10.0]

    def test_re_resolve_noop_when_no_expr(self, qapp):
        from pringle.slider_widget import _ExprBox
        emitted = []
        box = _ExprBox(5.0)
        box.committed.connect(emitted.append)
        box.re_resolve(lambda expr: 99.0)
        assert emitted == []
        assert box.value() == 5.0

    def test_re_resolve_keeps_last_valid_on_failed_resolution(self, qapp):
        from pringle.slider_widget import _ExprBox
        emitted = []
        box = _ExprBox(0.0)
        box.committed.connect(emitted.append)
        box._raw_expr = "b"
        box._last_valid = 7.0
        box.re_resolve(lambda expr: None)  # b no longer exists
        assert emitted == []
        assert box.value() == 7.0


# ---------------------------------------------------------------------------
# _make_resolver unit tests
# ---------------------------------------------------------------------------

class TestMakeResolver:
    def test_resolves_scalar_from_namespace(self, qapp):
        from pringle.cell_list import _make_resolver
        ns = {"a": 5.0, "b": 3}
        resolve = _make_resolver(ns)
        assert resolve("a") == 5.0
        assert resolve("b") == 3.0

    def test_resolves_numpy_constants(self, qapp):
        from pringle.cell_list import _make_resolver
        ns = {"pi": np.pi, "e": np.e}
        resolve = _make_resolver(ns)
        assert resolve("pi") == pytest.approx(math.pi)

    def test_resolves_expression(self, qapp):
        from pringle.cell_list import _make_resolver
        ns = {"a": 2.0, "b": 3.0}
        resolve = _make_resolver(ns)
        assert resolve("a + b") == 5.0
        assert resolve("a * b") == 6.0

    def test_filters_arrays_from_namespace(self, qapp):
        from pringle.cell_list import _make_resolver
        ns = {"x": np.linspace(0, 1, 10), "a": 5.0}
        resolve = _make_resolver(ns)
        assert resolve("x") is None   # array filtered out
        assert resolve("a") == 5.0

    def test_returns_none_for_unknown_name(self, qapp):
        from pringle.cell_list import _make_resolver
        resolve = _make_resolver({})
        assert resolve("not_defined") is None

    def test_returns_none_for_syntax_error(self, qapp):
        from pringle.cell_list import _make_resolver
        resolve = _make_resolver({"a": 1.0})
        assert resolve("a +") is None

    def test_cannot_access_builtins(self, qapp):
        from pringle.cell_list import _make_resolver
        resolve = _make_resolver({})
        assert resolve("__import__('os')") is None
        assert resolve("open('/etc/passwd')") is None


# ---------------------------------------------------------------------------
# SliderWidget resolver integration
# ---------------------------------------------------------------------------

class TestSliderWidgetResolver:
    def test_set_resolver_and_commit_pi(self, cell_list):
        """Typing 'pi' into min field resolves to math.pi."""
        from pringle.cell_list import _make_resolver
        slider = cell_list.add_cell("a = 5")
        from pringle.slider_widget import SliderWidget
        assert isinstance(slider, SliderWidget)

        ns = {"pi": np.pi}
        slider.set_resolver(_make_resolver(ns))

        emitted = []
        slider._min_box.committed.connect(emitted.append)
        slider._min_box.setText("pi")
        slider._min_box._on_commit()

        assert slider._min_box.expr() == "pi"
        assert slider._min_box.value() == pytest.approx(math.pi)

    def test_re_resolve_updates_max_from_other_slider(self, cell_list):
        """After re_resolve, max box tracking 'b' updates to b's new value."""
        from pringle.cell_list import _make_resolver
        from pringle.slider_widget import SliderWidget

        slider_a = cell_list.add_cell("a = 5")
        assert isinstance(slider_a, SliderWidget)

        # Set max_expr to "a" manually
        slider_a._max_box._raw_expr = "a"
        slider_a._max_box._last_valid = 5.0

        # Simulate a change: a is now 10
        resolver = _make_resolver({"a": 10.0})
        slider_a.re_resolve(resolver)

        assert slider_a._max_box.value() == 10.0

    def test_rebuild_updates_resolver_on_existing_sliders(self, qapp, grid):
        """After rebuild, existing sliders' resolvers include newly added slider values."""
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget

        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        slider_a = cl.add_cell("a = 5")
        assert isinstance(slider_a, SliderWidget)
        # At this point slider_a knows about pi but not b (b doesn't exist yet)
        assert slider_a._min_box._resolve("pi") == pytest.approx(math.pi)

        slider_b = cl.add_cell("b = 3")
        assert isinstance(slider_b, SliderWidget)

        # After the rebuild triggered by adding b, slider_a should know about b
        assert slider_a._min_box._resolve("b") == pytest.approx(3.0)
        # slider_b should know about a
        assert slider_b._min_box._resolve("a") == pytest.approx(5.0)

    def test_morph_to_slider_sets_resolver(self, qapp, grid):
        """Sliders created via cell morph (not add_cell) also get a resolver."""
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget

        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        # Add a constant to namespace
        cl.add_cell("k = 7")
        # Add a non-slider cell first, then edit it to become a slider
        cl._rebuild_namespace()
        # _maybe_morph_to_slider fires on the edit path; simulate directly
        eq_cell = cl.add_cell("z = sin(x)")
        from pringle.cell_widget import CellWidget
        assert isinstance(eq_cell, CellWidget)
        eq_cell._text_edit.setPlainText("m = 2")
        cl._maybe_morph_to_slider(eq_cell.cell_id)

        # Find the morphed slider
        morphed = next(c for c in cl._cells if isinstance(c, SliderWidget) and c.name == "m")
        assert hasattr(morphed._min_box, "_resolve")
        assert morphed._min_box._resolve("k") == pytest.approx(7.0)
        assert morphed._min_box._resolve("pi") == pytest.approx(math.pi)

    def test_namespace_rebuilt_signal_fires_after_rebuild(self, cell_list):
        """CellListWidget.namespace_rebuilt fires after _rebuild_namespace."""
        fired = []
        cell_list.namespace_rebuilt.connect(lambda: fired.append(True))
        cell_list._rebuild_namespace()
        assert len(fired) >= 1

    def test_new_slider_gets_resolver(self, qapp, grid):
        """Newly created slider receives the current namespace resolver."""
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget

        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        # Add a constant to namespace first
        cl.add_cell("k = 7")
        cl._rebuild_namespace()

        slider = cl.add_cell("a = 1")
        assert isinstance(slider, SliderWidget)
        # Resolver should be set; "k" in namespace
        assert hasattr(slider._min_box, "_resolve")
        assert slider._min_box._resolve("k") == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# Session round-trip
# ---------------------------------------------------------------------------

class TestSessionRoundTrip:
    def test_slider_with_max_expr_round_trips(self, qapp, grid):
        """Save slider with max_expr='pi', reload: expr preserved; re-resolves to pi after rebuild."""
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget
        from pringle.session import cell_to_dict, restore_cell_list

        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        slider = cl.add_cell("a = 1")
        assert isinstance(slider, SliderWidget)

        # Inject expr directly (simulating user typing "pi" into max box)
        slider._max_box._raw_expr = "pi"
        slider._max_box._last_valid = math.pi
        slider._max_box.setText("pi")
        slider._max = math.pi  # keep cell._max consistent

        d = cell_to_dict(slider)
        assert d.get("max_expr") == "pi"
        assert "max_val" in d

        # Restore into a fresh cell list
        cl2 = CellListWidget(on_cell_result=_noop_result, grid=grid)
        restore_cell_list(cl2, [d])  # triggers _rebuild_namespace at end

        restored = cl2._cells[0]
        assert isinstance(restored, SliderWidget)
        # Expression string preserved
        assert restored._max_box.expr() == "pi"
        # After the rebuild that fires at end of restore_cell_list, re_resolve updates _last_valid
        assert restored._max_box.value() == pytest.approx(math.pi)

    def test_old_session_without_expr_keys_loads_cleanly(self, qapp, grid):
        """Sessions lacking *_expr keys load with _raw_expr=None."""
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget
        from pringle.session import restore_cell_list

        old_data = [{
            "id": "test-001",
            "type": "slider",
            "source": "b = 2.0",
            "name": "b",
            "value": 2.0,
            "min_val": 0.0,
            "max_val": 10.0,
            "step": 0.1,
            "is_playing": False,
            "anim_mode": "pingpong",
            "sub_cells": [],
            "style": {"color": [0.2, 0.4, 0.8, 1.0], "opacity": 1.0,
                      "line_width": 0.05, "point_size": 0.1,
                      "scatter_render_mode": "circles",
                      "colormap": None, "colormap_reversed": False,
                      "normalize_arrows": False},
        }]

        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        restore_cell_list(cl, old_data)

        cell = cl._cells[0]
        assert isinstance(cell, SliderWidget)
        assert cell._min_box.expr() is None
        assert cell._max_box.expr() is None
        assert cell._step_box.expr() is None
        assert cell._min_box.value() == pytest.approx(0.0)
        assert cell._max_box.value() == pytest.approx(10.0)

    def test_slider_without_expr_omits_expr_keys(self, qapp, grid):
        """cell_to_dict for a plain-numeric slider omits *_expr keys."""
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget
        from pringle.session import cell_to_dict

        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        slider = cl.add_cell("c = 3")
        assert isinstance(slider, SliderWidget)

        d = cell_to_dict(slider)
        assert "min_expr" not in d
        assert "max_expr" not in d
        assert "step_expr" not in d

    def test_full_save_load_with_expr(self, qapp, grid):
        """Full save/load round-trip preserves expression strings."""
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget
        from pringle.session import save_session, load_session, restore_cell_list

        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        slider = cl.add_cell("d = 1")
        assert isinstance(slider, SliderWidget)
        slider._min_box._raw_expr = "pi"
        slider._min_box._last_valid = math.pi
        slider._min_box.setText("pi")

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name
        try:
            save_session(path, cl, grid.config)
            data = load_session(path)
            cl2 = CellListWidget(on_cell_result=_noop_result, grid=grid)
            restore_cell_list(cl2, data["cells"])
            restored = cl2._cells[0]
            assert isinstance(restored, SliderWidget)
            assert restored._min_box.expr() == "pi"
            assert restored._min_box.value() == pytest.approx(math.pi)
        finally:
            os.unlink(path)
