"""
FEAT-052 tests: strip trailing zeros from float display in style and axis settings panels.

Tests cover:
- _fmt unit tests: trailing zeros removed, decimal stripped when unnecessary
- StylePopoverWidget opacity field displays compact value (no trailing zeros)
- _CompactDoubleSpinBox.textFromValue strips trailing zeros
"""

import sys
import pytest

from pringle.style_popover import _fmt, _CompactDoubleSpinBox


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class TestFmt:
    def test_whole_number(self):
        assert _fmt(1.0) == "1"

    def test_half(self):
        assert _fmt(0.5) == "0.5"

    def test_zero(self):
        assert _fmt(0.0) == "0"

    def test_ten(self):
        assert _fmt(10.0) == "10"

    def test_many_decimals(self):
        assert _fmt(0.123456) == "0.123456"


class TestCompactSpinBox:
    def test_text_from_value_strips_trailing_zeros(self, qapp):
        spin = _CompactDoubleSpinBox()
        spin.setDecimals(6)
        assert spin.textFromValue(0.5) == "0.5"
        assert spin.textFromValue(1.0) == "1"
        assert spin.textFromValue(0.0) == "0"
        assert spin.textFromValue(0.123456) == "0.123456"

    def test_opacity_field_displays_compact(self, qapp):
        from pringle.style import CellStyle
        from pringle.style_popover import StylePopoverWidget
        style = CellStyle(opacity=0.5)
        popover = StylePopoverWidget(style)
        assert popover._opacity_spin.textFromValue(0.5) == "0.5"
        assert popover._opacity_spin.textFromValue(1.0) == "1"
