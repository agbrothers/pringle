"""
Source preprocessing for equation cells.

Transforms are applied before AST parsing to handle syntax that is not
valid Python but is natural for a math expression tool:

  f(x, y) = x**2 + y**2   →   f = lambda x, y: x**2 + y**2

Comment-cell detection also lives here.
"""

from __future__ import annotations
import ast
import re

# Matches: name(arg, ...) = expr
# Captures: (name, args_string, expr_string)
# Must be a single-line expression (no newlines in the match group).
_FUNC_DEF = re.compile(r"^(\w+)\(([^)]*)\)\s*=\s*(.+)$", re.DOTALL)

# Magic variable names consumed by the renderer (never exported)
MAGIC_NAMES = frozenset({"z", "y", "x", "xyz", "points", "vectors"})

# Spatial grid variables — these are reserved and injected per-execution
SPATIAL_NAMES = frozenset({"x", "y", "u", "v", "t"})


def preprocess(source: str) -> tuple[str, str | None]:
    """
    Preprocess a cell's source string.

    Returns (transformed_source, func_name_if_lambda).

    - `f(x, y) = expr` → `f = lambda x, y: expr`.  func_name is set.
    - All other source passes through unchanged.  func_name is None.
    """
    stripped = source.strip()
    m = _FUNC_DEF.match(stripped)
    if m:
        name, args, body = m.groups()
        args = args.strip()
        transformed = f"{name} = lambda {args}: {body}"
        return transformed, name
    return source, None


def is_comment_cell(source: str) -> bool:
    """
    Return True if the cell is a comment / documentation cell.

    A comment cell is one whose entire content is either:
    - Only `#`-prefixed lines (Python comment style)
    - A bare string literal (docstring style)
    """
    stripped = source.strip()
    if not stripped:
        return True  # empty cell treated as comment

    # All lines are comments
    lines = stripped.splitlines()
    if all(ln.strip().startswith("#") or not ln.strip() for ln in lines):
        return True

    # Bare string literal
    try:
        tree = ast.parse(stripped, mode="exec")
        if (
            len(tree.body) == 1
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            return True
    except SyntaxError:
        pass

    return False


def is_slider_cell(source: str) -> tuple[bool, str, float]:
    """
    Return (is_slider, name, value) for bare scalar assignments like `a = 1.5`.

    Only single-target, single-expression assignments to non-magic,
    non-spatial names are treated as sliders.
    """
    stripped = source.strip()
    try:
        tree = ast.parse(stripped, mode="exec")
    except SyntaxError:
        return False, "", 0.0

    if len(tree.body) != 1:
        return False, "", 0.0
    node = tree.body[0]
    if not isinstance(node, ast.Assign):
        return False, "", 0.0
    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
        return False, "", 0.0

    name = node.targets[0].id
    if name in MAGIC_NAMES or name in SPATIAL_NAMES:
        return False, "", 0.0

    if not isinstance(node.value, ast.Constant):
        return False, "", 0.0
    if not isinstance(node.value.value, (int, float)):
        return False, "", 0.0

    return True, name, float(node.value.value)


def get_func_auto_render(func_name: str, args_str: str) -> str | None:
    """
    Given a function definition `f(args) = expr`, return the magic variable
    name that its auto-render will produce, or None if no auto-render.

    Spatial auto-render rules (from design doc 05):
      f(x, y)  → "z"
      f(x)     → "y"
      f(u, v)  → "xyz"  (parametric surface)
      other    → None
    """
    args = [a.strip() for a in args_str.split(",") if a.strip()]
    if args == ["x", "y"]:
        return "z"
    if args == ["x"]:
        return "y"
    if args == ["u", "v"]:
        return "xyz"
    return None
