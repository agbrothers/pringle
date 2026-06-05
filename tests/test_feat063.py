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


# ---------------------------------------------------------------------------
# FEAT-147 — keyword, def-name, argument, and inline-comment highlighting
# ---------------------------------------------------------------------------

class TestKeywordColors:
    """Keywords must render in OPERATOR_COLOR."""

    def test_for_keyword(self, cap):
        cap.run("for i in arange(10):")
        assert cap.color_at(0) == QColor(theme.OPERATOR_COLOR).name().upper()

    def test_def_keyword(self, cap):
        cap.run("def foo(x):")
        assert cap.color_at(0) == QColor(theme.OPERATOR_COLOR).name().upper()

    def test_return_keyword(self, cap):
        cap.run("    return x")
        assert cap.color_at(4) == QColor(theme.OPERATOR_COLOR).name().upper()

    def test_in_keyword(self, cap):
        # 'in' at position 7 in "for i in arange(10):"
        cap.run("for i in arange(10):")
        assert cap.color_at(7) == QColor(theme.OPERATOR_COLOR).name().upper()

    def test_if_keyword(self, cap):
        cap.run("if x > 0:")
        assert cap.color_at(0) == QColor(theme.OPERATOR_COLOR).name().upper()

    def test_else_keyword(self, cap):
        cap.run("else:")
        assert cap.color_at(0) == QColor(theme.OPERATOR_COLOR).name().upper()

    def test_import_keyword_highlighted(self, cap):
        # 'import' is now a keyword (imports allowed via trust model)
        cap.run("import os")
        assert cap.color_at(0) == QColor(theme.OPERATOR_COLOR).name().upper()


class TestDefNameColor:
    """The identifier after 'def' must be FUNCTION_COLOR; 'def' itself stays OPERATOR_COLOR."""

    def test_defname_is_function_color(self, cap):
        cap.run("def bifurcate(x):")
        # 'bifurcate' starts at index 4
        assert cap.color_at(4) == QColor(theme.FUNCTION_COLOR).name().upper()

    def test_def_token_is_operator_color(self, cap):
        cap.run("def bifurcate(x):")
        assert cap.color_at(0) == QColor(theme.OPERATOR_COLOR).name().upper()

    def test_defname_full_span(self, cap):
        cap.run("def foo(x):")
        for pos in range(4, 7):
            assert cap.color_at(pos) == QColor(theme.FUNCTION_COLOR).name().upper()


class TestArgumentColors:
    """Parameters from def signatures must be MAGIC_COLOR in the signature and body."""

    def _make_cap(self, qapp) -> _CapturingHighlighter:
        doc = QTextDocument()
        return _CapturingHighlighter(doc)

    def test_arg_in_signature(self, qapp):
        h = self._make_cap(qapp)
        h.document().setPlainText("def f(memories, k):\n    return memories")
        h.document().documentLayout().documentSize()
        h._captures.clear()
        h.highlightBlock("def f(memories, k):")
        assert h.color_at(6) == QColor(theme.MAGIC_COLOR).name().upper()

    def test_arg_in_body(self, qapp):
        h = self._make_cap(qapp)
        h.document().setPlainText("def f(memories, k):\n    return memories")
        h.document().documentLayout().documentSize()
        h._captures.clear()
        h.highlightBlock("    return memories")
        assert h.color_at(11) == QColor(theme.MAGIC_COLOR).name().upper()

    def test_unicode_arg(self, qapp):
        h = self._make_cap(qapp)
        h.document().setPlainText("def f(β):\n    return β")
        h.document().documentLayout().documentSize()
        h._captures.clear()
        h.highlightBlock("def f(β):")
        assert h.color_at(6) == QColor(theme.MAGIC_COLOR).name().upper()

    def test_annotation_type_not_magic(self, qapp):
        # 'k:int' — 'k' is magic, 'int' is NOT magic (not a param name)
        h = self._make_cap(qapp)
        h.document().setPlainText("def f(k:int):\n    return k")
        h.document().documentLayout().documentSize()
        h._captures.clear()
        h.highlightBlock("def f(k:int):")
        assert h.color_at(6) == QColor(theme.MAGIC_COLOR).name().upper()
        assert h.color_at(8) != QColor(theme.MAGIC_COLOR).name().upper()

    def test_non_param_not_magic(self, qapp):
        # 'pts' is a local variable, not a parameter — must not be MAGIC_COLOR
        h = self._make_cap(qapp)
        h.document().setPlainText("def f(k):\n    pts = k + 1")
        h.document().documentLayout().documentSize()
        h._captures.clear()
        h.highlightBlock("    pts = k + 1")
        assert h.color_at(4) != QColor(theme.MAGIC_COLOR).name().upper()


class TestInlineCommentColors:
    """Inline # comments must render in COMMENT_COLOR; prior tokens are overwritten."""

    def test_comment_line_is_comment_color(self, cap):
        cap.run("## BUILD OUTPUT DATA")
        assert cap.color_at(0) == QColor(theme.COMMENT_COLOR).name().upper()

    def test_inline_comment_suffix(self, cap):
        # 'x + 1  # comment' — the # and beyond must be COMMENT_COLOR
        cap.run("x + 1  # comment")
        assert cap.color_at(7) == QColor(theme.COMMENT_COLOR).name().upper()

    def test_code_before_comment_not_comment_color(self, cap):
        cap.run("x + 1  # comment")
        assert cap.color_at(0) != QColor(theme.COMMENT_COLOR).name().upper()

    def test_bracket_inside_comment_no_depth_change(self, cap):
        # A bracket inside a # comment must not affect rainbow depth
        cap.run("x  # (unclosed")
        assert cap._block_state == 0


class TestLiteralColors:
    """None/True/False must render in NUMBER_COLOR, not OPERATOR_COLOR."""

    def test_none_is_number_color(self, cap):
        cap.run("enrg[:, None]")
        # 'None' starts at index 8 (space at 7)
        assert cap.color_at(8) == QColor(theme.NUMBER_COLOR).name().upper()

    def test_none_not_operator_color(self, cap):
        cap.run("enrg[:, None]")
        assert cap.color_at(8) != QColor(theme.OPERATOR_COLOR).name().upper()

    def test_true_is_number_color(self, cap):
        cap.run("flag = True")
        assert cap.color_at(7) == QColor(theme.NUMBER_COLOR).name().upper()

    def test_false_is_number_color(self, cap):
        cap.run("flag = False")
        assert cap.color_at(7) == QColor(theme.NUMBER_COLOR).name().upper()


class TestFunctionCallColors:
    """Unknown identifiers immediately before ( must be colored FUNCTION_COLOR."""

    def test_unknown_call_is_function_color(self, cap):
        # 'bifurcate' is not in the numpy whitelist — detected via call pattern
        cap.run("result = bifurcate(M, k)")
        # 'bifurcate' starts at index 9
        assert cap.color_at(9) == QColor(theme.FUNCTION_COLOR).name().upper()

    def test_keyword_before_paren_not_function_color(self, cap):
        # 'return' followed by ( must stay OPERATOR_COLOR
        cap.run("return(x)")
        assert cap.color_at(0) == QColor(theme.OPERATOR_COLOR).name().upper()

    def test_magic_before_paren_not_overridden(self, cap):
        # magic names that happen to be called must NOT change from MAGIC_COLOR
        # (function-call pass skips _MAGIC_NAMES)
        cap.run("z()")
        assert cap.color_at(0) == QColor(theme.MAGIC_COLOR).name().upper()

    def test_known_func_call_still_function_color(self, cap):
        # Known whitelisted functions are already FUNCTION_COLOR; call pass is idempotent
        cap.run("sin(x)")
        assert cap.color_at(0) == QColor(theme.FUNCTION_COLOR).name().upper()
