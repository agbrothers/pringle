"""
FEAT-063 — Syntax highlighting in expression cells.

Tests cover:
- PringleHighlighter constructs without error
- Magic variable positions are colored with MAGIC_COLOR
- Function name positions are colored with FUNCTION_COLOR
- Opening bracket at depth 0 uses RAINBOW_BRACKETS[0]
- Nested brackets increment and decrement depth correctly
- Block state reflects unmatched open brackets
- set_colors() triggers rehighlight without raising
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QTextDocument, QTextCharFormat, QColor

import pringle.syntax_theme as theme
from pringle.syntax_highlighter import PringleHighlighter


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------------------
# Capture helper — intercepts setFormat and setCurrentBlockState calls
# ---------------------------------------------------------------------------

class _CapturingHighlighter(PringleHighlighter):
    """Records setFormat calls so tests can verify token colors without
    relying on QTextLayout's layout engine running in headless mode."""

    def __init__(self, doc: QTextDocument):
        self._captures: list[tuple[int, int, str]] = []
        self._block_state: int = -1
        self._doc_ref = doc   # prevent Python GC from deleting the C++ object
        super().__init__(doc)

    def setFormat(self, start: int, length: int, fmt: QTextCharFormat) -> None:
        self._captures.append((start, length, fmt.foreground().color().name().upper()))
        super().setFormat(start, length, fmt)

    def setCurrentBlockState(self, state: int) -> None:
        self._block_state = state
        super().setCurrentBlockState(state)

    def run(self, text: str) -> None:
        """Set document text and wait for highlightBlock to fire."""
        self._captures.clear()
        self._block_state = -1
        self.document().setPlainText(text)
        # Force the layout engine so highlighting runs synchronously
        self.document().documentLayout().documentSize()

    def color_at(self, pos: int) -> str:
        """Return the last color applied to position pos, or '' if none."""
        result = ""
        for start, length, color in self._captures:
            if start <= pos < start + length:
                result = color   # later rules overwrite earlier ones
        return result


@pytest.fixture
def cap(qapp) -> _CapturingHighlighter:
    doc = QTextDocument()
    return _CapturingHighlighter(doc)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_constructs_without_error(self, qapp):
        doc = QTextDocument()
        h = PringleHighlighter(doc)
        assert h is not None


# ---------------------------------------------------------------------------
# Magic variable colors
# ---------------------------------------------------------------------------

class TestMagicColors:
    def test_z_is_magic_color(self, cap):
        cap.run("z = x**2")
        assert cap.color_at(0) == QColor(theme.MAGIC_COLOR).name().upper()

    def test_x_is_magic_color(self, cap):
        cap.run("z = x + y")
        # 'x' at index 4
        assert cap.color_at(4) == QColor(theme.MAGIC_COLOR).name().upper()

    def test_magic_covers_full_token(self, cap):
        cap.run("xyz")
        # all three chars of 'xyz' should share the magic color
        for pos in range(3):
            assert cap.color_at(pos) == QColor(theme.MAGIC_COLOR).name().upper()


# ---------------------------------------------------------------------------
# Function name colors
# ---------------------------------------------------------------------------

class TestFunctionColors:
    def test_sin_is_function_color(self, cap):
        cap.run("z = sin(x)")
        # 'sin' starts at index 4
        assert cap.color_at(4) == QColor(theme.FUNCTION_COLOR).name().upper()

    def test_sqrt_is_function_color(self, cap):
        cap.run("z = sqrt(x)")
        assert cap.color_at(4) == QColor(theme.FUNCTION_COLOR).name().upper()

    def test_function_not_in_magic(self, cap):
        cap.run("sin")
        assert cap.color_at(0) == QColor(theme.FUNCTION_COLOR).name().upper()
        assert cap.color_at(0) != QColor(theme.MAGIC_COLOR).name().upper()


# ---------------------------------------------------------------------------
# Rainbow bracket colors
# ---------------------------------------------------------------------------

class TestRainbowBrackets:
    def test_opening_paren_depth0(self, cap):
        cap.run("sin(x)")
        # '(' at index 3 → depth 0
        assert cap.color_at(3) == QColor(theme.RAINBOW_BRACKETS[0]).name().upper()

    def test_nested_open_paren_depth1(self, cap):
        cap.run("((x))")
        # inner '(' at index 1 → depth 1
        assert cap.color_at(1) == QColor(theme.RAINBOW_BRACKETS[1]).name().upper()

    def test_closing_paren_uses_decremented_depth(self, cap):
        cap.run("((x))")
        # inner ')' at index 3 → depth 2 decrements to 1, colored at depth 1
        assert cap.color_at(3) == QColor(theme.RAINBOW_BRACKETS[1]).name().upper()

    def test_opening_bracket_depth0(self, cap):
        cap.run("x[0]")
        # '[' at index 1 → depth 0
        assert cap.color_at(1) == QColor(theme.RAINBOW_BRACKETS[0]).name().upper()


# ---------------------------------------------------------------------------
# Block state (bracket depth tracking)
# ---------------------------------------------------------------------------

class TestBlockState:
    def test_unmatched_opens_set_state(self, cap):
        cap.run("((")
        assert cap._block_state == 2

    def test_balanced_brackets_state_zero(self, cap):
        cap.run("(x + y)")
        assert cap._block_state == 0

    def test_single_open_state_one(self, cap):
        cap.run("sin(")
        assert cap._block_state == 1


# ---------------------------------------------------------------------------
# set_colors
# ---------------------------------------------------------------------------

class TestSetColors:
    def test_set_colors_does_not_raise(self, cap, qapp):
        cap.set_colors({
            "magic": "#FF0000",
            "functions": "#00FF00",
            "numbers": "#0000FF",
            "operators": "#FFFF00",
            "rainbow": ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF"],
        })
        qapp.processEvents()

    def test_set_colors_updates_magic(self, qapp):
        doc = QTextDocument()
        h = _CapturingHighlighter(doc)
        h.set_colors({"magic": "#ABCDEF"})
        h.run("z = 1")
        assert h.color_at(0) == QColor("#ABCDEF").name().upper()

    def test_set_colors_updates_rainbow(self, qapp):
        doc = QTextDocument()
        h = _CapturingHighlighter(doc)
        h.set_colors({"rainbow": ["#FF1234"] * 6})
        h.run("(x)")
        assert h.color_at(0) == QColor("#FF1234").name().upper()
