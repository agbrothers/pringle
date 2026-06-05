"""Token-based syntax highlighter for expression cells (FEAT-063)."""

from __future__ import annotations

import re

from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor

from pringle.preprocess import MAGIC_NAMES, SPATIAL_NAMES
from pringle.namespace import build_equation_namespace
from pringle.ast_utils import get_param_names
import pringle.syntax_theme as _theme

# ---------------------------------------------------------------------------
# Token sets — built once at module load
# ---------------------------------------------------------------------------

_MAGIC_NAMES: frozenset[str] = MAGIC_NAMES | SPATIAL_NAMES | {"n", "cfg", "camera"}
_FUNC_NAMES: frozenset[str] = (
    frozenset(k for k in build_equation_namespace().keys() if not k.startswith("_"))
    - _MAGIC_NAMES
)

# Keywords (None/True/False excluded — they color as NUMBER_COLOR literals).
_KEYWORDS = frozenset({
    "def", "return", "for", "while", "continue", "break", "not", "in",
    "if", "elif", "else", "and", "or", "is", "pass", "lambda",
    "del", "assert", "raise", "try", "except", "finally", "with", "as",
    "import", "from",
})

# Patterns sorted longest-first to avoid partial matches (e.g. arctan2 > arctan)
_RE_MAGIC    = re.compile(r'\b(' + '|'.join(sorted(_MAGIC_NAMES, key=len, reverse=True)) + r')\b')
_RE_FUNC     = re.compile(r'\b(' + '|'.join(sorted(_FUNC_NAMES,  key=len, reverse=True)) + r')\b')
_RE_KEYWORD  = re.compile(r'\b(' + '|'.join(sorted(_KEYWORDS, key=len, reverse=True)) + r')\b')
_RE_NUMBER   = re.compile(r'\b\d+\.?\d*(?:[eE][+-]?\d+)?\b')
_RE_LITERAL  = re.compile(r'\b(None|True|False)\b')   # boolean/None literals → NUMBER_COLOR
_RE_OPERATOR = re.compile(r'[+\-*/%=<>!&|~^]+')
_RE_BRACKET  = re.compile(r'[\[\]()\{\}]')
_RE_CALL        = re.compile(r'\b(\w+)(?=\s*\()')        # identifier immediately before (
_RE_DEFNAME     = re.compile(r'\bdef\s+(\w+)')
_RE_IDENT       = re.compile(r'\b\w+\b')
_RE_COMMENT     = re.compile(r'#.*')
_RE_IMPORT_MOD  = re.compile(r'\b(?:from|import)\s+([\w.]+)')   # module name → MAGIC_COLOR
_RE_FROM_NAMES  = re.compile(r'\bfrom\s+[\w.]+\s+import\s+(.*)')  # imported names → FUNC_COLOR


def _make_fmt(hex_color: str) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(hex_color))
    return fmt


class PringleHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for Pringle expression cells."""

    def __init__(self, document):
        self._arg_names: frozenset[str] = frozenset()
        super().__init__(document)
        self._build_formats()
        self.document().contentsChanged.connect(self._on_contents_changed)

    def _build_formats(self, overrides: dict | None = None) -> None:
        ov = overrides or {}
        magic_color    = ov.get("magic",    _theme.MAGIC_COLOR)
        func_color     = ov.get("functions", _theme.FUNCTION_COLOR)
        number_color   = ov.get("numbers",  _theme.NUMBER_COLOR)
        operator_color = ov.get("operators", _theme.OPERATOR_COLOR)
        rainbow        = ov.get("rainbow",  _theme.RAINBOW_BRACKETS)
        self.comment_color: str = ov.get("comment", _theme.COMMENT_COLOR)

        self._func_fmt    = _make_fmt(func_color)
        self._magic_fmt   = _make_fmt(magic_color)
        self._comment_fmt = _make_fmt(self.comment_color)

        self._static_rules: list[tuple[re.Pattern, QTextCharFormat]] = [
            (_RE_MAGIC,    _make_fmt(magic_color)),
            (_RE_FUNC,     _make_fmt(func_color)),
            (_RE_NUMBER,   _make_fmt(number_color)),
            (_RE_LITERAL,  _make_fmt(number_color)),   # None/True/False as literals
            (_RE_KEYWORD,  _make_fmt(operator_color)),
            (_RE_OPERATOR, _make_fmt(operator_color)),
        ]
        self._rainbow_fmts: list[QTextCharFormat] = [_make_fmt(c) for c in rainbow]

    def _on_contents_changed(self) -> None:
        new = frozenset(get_param_names(self.document().toPlainText()))
        if new != self._arg_names:
            self._arg_names = new
            self.rehighlight()

    def _rainbow_fmt(self, depth: int) -> QTextCharFormat:
        return self._rainbow_fmts[depth % len(self._rainbow_fmts)]

    def highlightBlock(self, text: str) -> None:
        depth = max(0, self.previousBlockState())

        # Find comment boundary for this line
        cm = _RE_COMMENT.search(text)
        code_end = cm.start() if cm else len(text)

        # Static rules (magic, func, number, literals, keyword, operator) — code region only
        for pattern, fmt in self._static_rules:
            for m in pattern.finditer(text):
                if m.start() < code_end:
                    self.setFormat(m.start(), m.end() - m.start(), fmt)

        # Function calls: word before ( → FUNCTION_COLOR for unknown (non-keyword) identifiers
        for m in _RE_CALL.finditer(text):
            name = m.group()
            if m.start() < code_end and name not in _KEYWORDS and name not in _MAGIC_NAMES:
                self.setFormat(m.start(), len(name), self._func_fmt)

        # def-name → FUNCTION_COLOR
        for m in _RE_DEFNAME.finditer(text):
            if m.start() < code_end:
                self.setFormat(m.start(1), m.end(1) - m.start(1), self._func_fmt)

        # Argument names → MAGIC_COLOR (after func pass so args win over whitelisted names)
        if self._arg_names:
            for m in _RE_IDENT.finditer(text):
                if m.start() < code_end and m.group() in self._arg_names:
                    self.setFormat(m.start(), m.end() - m.start(), self._magic_fmt)

        # Import module names → MAGIC_COLOR (e.g. 'scipy' in 'import scipy as sc')
        for m in _RE_IMPORT_MOD.finditer(text):
            if m.start() < code_end:
                self.setFormat(m.start(1), m.end(1) - m.start(1), self._magic_fmt)

        # Imported names → FUNCTION_COLOR (e.g. 'norm', 'erf' in 'from scipy import norm, erf')
        for m in _RE_FROM_NAMES.finditer(text):
            if m.start() < code_end:
                pos = m.start(1)
                for segment in m.group(1).split(","):
                    name_m = re.match(r'\s*(\w+)', segment)
                    if name_m:
                        word_pos = pos + name_m.start(1)
                        if word_pos < code_end:
                            self.setFormat(word_pos, len(name_m.group(1)), self._func_fmt)
                    pos += len(segment) + 1

        # Rainbow brackets — code region only (so # comments don't affect depth)
        for m in _RE_BRACKET.finditer(text):
            if m.start() >= code_end:
                continue
            ch = m.group()
            if ch in "([{":
                self.setFormat(m.start(), 1, self._rainbow_fmt(depth))
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
                self.setFormat(m.start(), 1, self._rainbow_fmt(depth))

        self.setCurrentBlockState(depth)

        # Comment span (last — overwrites all other formatting in the comment)
        if cm:
            self.setFormat(cm.start(), len(text) - cm.start(), self._comment_fmt)

    def set_colors(self, overrides: dict) -> None:
        """Rebuild formats from color overrides and rehighlight all blocks."""
        self._build_formats(overrides)
        self.rehighlight()
