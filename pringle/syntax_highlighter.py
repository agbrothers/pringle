"""Token-based syntax highlighter for expression cells (FEAT-063)."""

from __future__ import annotations

import re

from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor

from pringle.preprocess import MAGIC_NAMES, SPATIAL_NAMES
from pringle.namespace import build_equation_namespace
import pringle.syntax_theme as _theme

# ---------------------------------------------------------------------------
# Token sets — built once at module load
# ---------------------------------------------------------------------------

_MAGIC_NAMES: frozenset[str] = MAGIC_NAMES | SPATIAL_NAMES | {"n", "cfg"}
_FUNC_NAMES: frozenset[str] = (
    frozenset(build_equation_namespace().keys()) - _MAGIC_NAMES - {"__builtins__"}
)

# Patterns sorted longest-first to avoid partial matches (e.g. arctan2 > arctan)
_RE_MAGIC    = re.compile(r'\b(' + '|'.join(sorted(_MAGIC_NAMES, key=len, reverse=True)) + r')\b')
_RE_FUNC     = re.compile(r'\b(' + '|'.join(sorted(_FUNC_NAMES,  key=len, reverse=True)) + r')\b')
_RE_NUMBER   = re.compile(r'\b\d+\.?\d*(?:[eE][+-]?\d+)?\b')
_RE_OPERATOR = re.compile(r'[+\-*/%=<>!&|~^]+')
_RE_BRACKET  = re.compile(r'[\[\]()\{\}]')


def _make_fmt(hex_color: str) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(hex_color))
    return fmt


class PringleHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for Pringle expression cells."""

    def __init__(self, document):
        super().__init__(document)
        self._build_formats()

    def _build_formats(self, overrides: dict | None = None) -> None:
        ov = overrides or {}
        magic_color    = ov.get("magic",    _theme.MAGIC_COLOR)
        func_color     = ov.get("functions", _theme.FUNCTION_COLOR)
        number_color   = ov.get("numbers",  _theme.NUMBER_COLOR)
        operator_color = ov.get("operators", _theme.OPERATOR_COLOR)
        rainbow        = ov.get("rainbow",  _theme.RAINBOW_BRACKETS)
        # comment color is stored for FEAT-064 settings panel but not applied
        # by the highlighter — CommentCellWidget applies it via stylesheet
        self.comment_color: str = ov.get("comment", _theme.COMMENT_COLOR)

        self._static_rules: list[tuple[re.Pattern, QTextCharFormat]] = [
            (_RE_MAGIC,    _make_fmt(magic_color)),
            (_RE_FUNC,     _make_fmt(func_color)),
            (_RE_NUMBER,   _make_fmt(number_color)),
            (_RE_OPERATOR, _make_fmt(operator_color)),
        ]
        self._rainbow_fmts: list[QTextCharFormat] = [_make_fmt(c) for c in rainbow]

    def _rainbow_fmt(self, depth: int) -> QTextCharFormat:
        return self._rainbow_fmts[depth % len(self._rainbow_fmts)]

    def highlightBlock(self, text: str) -> None:
        depth = max(0, self.previousBlockState())

        for pattern, fmt in self._static_rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)

        for m in _RE_BRACKET.finditer(text):
            ch = m.group()
            if ch in "([{":
                self.setFormat(m.start(), 1, self._rainbow_fmt(depth))
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
                self.setFormat(m.start(), 1, self._rainbow_fmt(depth))

        self.setCurrentBlockState(depth)

    def set_colors(self, overrides: dict) -> None:
        """Rebuild formats from color overrides and rehighlight all blocks."""
        self._build_formats(overrides)
        self.rehighlight()
