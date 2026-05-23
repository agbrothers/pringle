"""
BUG-045 — Slider value clamped to range bounds instead of flagging the offending bound.

When the user types a value outside [min, max], it must be stored as-is and a
red border placed on the offending bound field. The border clears once the
bound is widened to cover the value.
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.slider_widget import SliderWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class TestBoundsValidation:
    def test_value_above_max_flags_max(self, qapp):
        s = SliderWidget(name="a", value=5.0, min_val=0.0, max_val=10.0)
        s.set_value(15.0, emit=False)
        assert s.value == pytest.approx(15.0)
        assert "red" in s._max_box.styleSheet() or "#c0392b" in s._max_box.styleSheet()
        assert s._min_box.styleSheet() == ""

    def test_value_below_min_flags_min(self, qapp):
        s = SliderWidget(name="a", value=5.0, min_val=0.0, max_val=10.0)
        s.set_value(-3.0, emit=False)
        assert s.value == pytest.approx(-3.0)
        assert "red" in s._min_box.styleSheet() or "#c0392b" in s._min_box.styleSheet()
        assert s._max_box.styleSheet() == ""

    def test_in_range_value_no_border(self, qapp):
        s = SliderWidget(name="a", value=5.0, min_val=0.0, max_val=10.0)
        s.set_value(7.0, emit=False)
        assert s._min_box.styleSheet() == ""
        assert s._max_box.styleSheet() == ""

    def test_max_border_clears_when_range_widened(self, qapp):
        s = SliderWidget(name="a", value=5.0, min_val=0.0, max_val=10.0)
        s.set_value(15.0, emit=False)
        assert "#c0392b" in s._max_box.styleSheet()

        # Simulate user widening max to 20
        s._max_box.setValue(20.0)
        s._on_range_changed()
        assert s._max_box.styleSheet() == ""

    def test_min_border_clears_when_range_widened(self, qapp):
        s = SliderWidget(name="a", value=5.0, min_val=0.0, max_val=10.0)
        s.set_value(-3.0, emit=False)
        assert "#c0392b" in s._min_box.styleSheet()

        s._min_box.setValue(-10.0)
        s._on_range_changed()
        assert s._min_box.styleSheet() == ""

    def test_value_emitted_unclamped(self, qapp):
        s = SliderWidget(name="a", value=5.0, min_val=0.0, max_val=10.0)
        received: list[float] = []
        s.value_changed.connect(lambda n, v: received.append(v))
        s.set_value(15.0)
        assert received == [pytest.approx(15.0)]
