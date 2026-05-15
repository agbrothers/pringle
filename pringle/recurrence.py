"""
Recurrence relation parser and executor for data panel cells.

A recurrence cell consists of:
  Main expression:        path = zeros((50, 2))
  Initial condition(s):   path[0] = array([1.0, 0.0])
  Recursion rule:         path[n] = path[n-1] * 0.9

The executor allocates the array, applies initial conditions, then loops
from index 1 to len-1, evaluating the right-hand side with `n` in scope.
"""

from __future__ import annotations

import re
import numpy as np

# Matches: array_name[n] = rhs_expression  (spaces around n are allowed)
_RULE_RE = re.compile(r"^\s*(\w+)\s*\[\s*n\s*\]\s*=\s*(.+)$", re.DOTALL)


def parse_recurrence(rule_expr: str) -> tuple[bool, str, str]:
    """
    Parse a recurrence rule.

    Returns (is_valid, array_name, rhs_expression).
    Example: "path[n] = path[n-1] * 0.9" → (True, "path", "path[n-1] * 0.9")
    """
    m = _RULE_RE.match(rule_expr.strip())
    if m:
        return True, m.group(1), m.group(2).strip()
    return False, "", ""


def execute_recurrence(
    array_name: str,
    array: np.ndarray,
    initial_exprs: list[str],
    rule_expr: str,
    namespace: dict,
) -> tuple[np.ndarray, str | None]:
    """
    Execute a recurrence relation.

    Steps:
    1. Copy the seed array.
    2. Execute each initial_condition expression with the array in scope.
    3. Parse `rule_expr` as ``array_name[n] = rhs``.
    4. Loop n = 1 … len(array)-1, evaluating rhs and storing the result.

    Returns (result_array, warning_or_None).
    """
    result = array.copy()

    # Apply initial conditions
    for expr in initial_exprs:
        local = {**namespace, array_name: result}
        try:
            exec(expr, {"__builtins__": {}}, local)  # noqa: S102
            # Sync back — exec may have modified the array in-place or replaced it
            result = local.get(array_name, result)
        except Exception as exc:
            return result, f"Initial condition error: {exc}"

    # Parse rule
    is_valid, _, rhs = parse_recurrence(rule_expr)
    if not is_valid:
        return result, f"Cannot parse recurrence rule: {rule_expr!r}"

    n_steps = result.shape[0]
    nan_found = False

    for n in range(1, n_steps):
        local = {**namespace, array_name: result, "n": n}
        try:
            with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
                val = eval(rhs, {"__builtins__": {}}, local)  # noqa: S307
            result[n] = val
        except Exception as exc:
            return result, f"Recurrence step {n} error: {exc}"
        if np.any(~np.isfinite(result[n])):
            nan_found = True

    return result, "NaN/Inf detected in recurrence output" if nan_found else None
