"""
Theme loading for the Qt application.

Qt style sheets have no native variables, so tunable colours are declared once
as ``@var name: value;`` lines inside a comment block at the top of ``theme.qss``
and substituted into the stylesheet at load time. ``theme_var()`` exposes the
same values to code and tests, so each colour has a single source of truth and
can be retuned by editing only ``theme.qss``.
"""

from __future__ import annotations

import re
from importlib.resources import files

_VAR_RE = re.compile(r"@var\s+([\w-]+)\s*:\s*([^;]+);")


def _read_qss() -> str:
    return files("pringle").joinpath("theme.qss").read_text(encoding="utf-8")


def theme_vars() -> dict[str, str]:
    """Return the ``@var name: value;`` definitions declared in theme.qss."""
    return {m.group(1): m.group(2).strip() for m in _VAR_RE.finditer(_read_qss())}


def theme_var(name: str) -> str:
    """Return one theme variable's value, e.g. ``theme_var("active-cell-bg")``."""
    return theme_vars()[name]


def load_stylesheet() -> str:
    """Return theme.qss with every ``@var`` token substituted — ready for setStyleSheet."""
    qss = _read_qss()
    for name, value in theme_vars().items():
        qss = re.sub(rf"@{re.escape(name)}\b", value, qss)
    return qss
