"""
Whitelisted evaluation namespace for equation panel cells.

Only explicitly imported numpy/scipy names are available.  No builtins,
no __import__, no exec/eval inside expressions.  The safety AST checker
(safety.py) provides a second layer of protection.

Design note: we import individual names so the set of available functions
is enumerable and auditable.  Adding a new function requires an explicit
line here — not just "import numpy as np".
"""

from numpy import (
    # Trig
    sin, cos, tan, arcsin, arccos, arctan, arctan2, hypot,
    sinh, cosh, tanh, arcsinh, arccosh, arctanh,
    # Rounding / sign / integer casting
    abs, floor, ceil, round, sign, clip, mod, int_, intp,
    # Exponential / log
    exp, exp2, log, log2, log10, sqrt, cbrt, power,
    # Array creation
    zeros, ones, empty, full,
    zeros_like, ones_like, empty_like, full_like,
    linspace, arange, meshgrid,
    array, asarray, concatenate,
    stack, column_stack, row_stack, hstack, vstack,
    # Shape
    reshape, ravel, transpose, squeeze,
    # Math
    sum, prod, cumsum, cumprod,
    min, max, mean, median, std, var, maximum, minimum,
    diff, gradient, dot, cross, outer, einsum,
    # Boolean / masking
    where, select, isnan, isinf, isfinite, logical_and, logical_or, logical_not,
    any, all,
    # Constants
    pi, e, inf, nan,
    # Dtypes
    float32, float64, int32, int64, complex64, complex128, bool_,
    # Random (numpy.random) — available as `random` sub-namespace
)
import numpy.random as random  # noqa: F401 — expose as `random`

from scipy.special import (
    gamma, factorial, comb,
    erf, erfc, erfinv,
    j0, j1, jn, yn,           # Bessel functions
    legendre,
    logsumexp,
)
from scipy.linalg import (
    norm, det, inv, solve,
    eig, eigvals, svd,
)

# ---------------------------------------------------------------------------

def build_equation_namespace() -> dict:
    """
    Return a fresh namespace dict suitable for exec()ing one equation cell.

    The namespace contains the whitelisted numpy/scipy names only.
    '__builtins__' is explicitly removed (set to {}) to prevent access
    to Python built-ins (open, import, eval, exec, etc.).
    """
    ns: dict = {
        # numpy names
        "sin": sin, "cos": cos, "tan": tan,
        "arcsin": arcsin, "arccos": arccos, "arctan": arctan,
        "arctan2": arctan2, "hypot": hypot,
        "sinh": sinh, "cosh": cosh, "tanh": tanh,
        "arcsinh": arcsinh, "arccosh": arccosh, "arctanh": arctanh,
        "abs": abs, "floor": floor, "ceil": ceil, "round": round,
        "sign": sign, "clip": clip, "mod": mod,
        "int_": int_, "intp": intp,
        "exp": exp, "exp2": exp2, "log": log, "log2": log2,
        "log10": log10, "sqrt": sqrt, "cbrt": cbrt, "power": power,
        "zeros": zeros, "ones": ones, "empty": empty, "full": full,
        "zeros_like": zeros_like, "ones_like": ones_like,
        "empty_like": empty_like, "full_like": full_like,
        "linspace": linspace, "arange": arange, "meshgrid": meshgrid,
        "array": array, "asarray": asarray,
        "concatenate": concatenate, "stack": stack,
        "column_stack": column_stack, "row_stack": row_stack,
        "hstack": hstack, "vstack": vstack,
        "reshape": reshape, "ravel": ravel,
        "transpose": transpose, "squeeze": squeeze,
        "sum": sum, "prod": prod, "cumsum": cumsum, "cumprod": cumprod,
        "min": min, "max": max, "mean": mean, "median": median,
        "std": std, "var": var, "maximum": maximum, "minimum": minimum, 
        "diff": diff, "gradient": gradient,
        "dot": dot, "cross": cross, "outer": outer, "einsum": einsum,
        "where": where, "select": select,
        "isnan": isnan, "isinf": isinf, "isfinite": isfinite,
        "logical_and": logical_and, "logical_or": logical_or,
        "logical_not": logical_not,
        "any": any, "all": all,
        "pi": pi, "e": e, "inf": inf, "nan": nan,
        # Dtypes
        "float32": float32, "float64": float64,
        "int32": int32, "int64": int64,
        "complex64": complex64, "complex128": complex128,
        "bool_": bool_,
        "int": int,  # safe builtin — needed for array indexing (e.g. path[int(t)])
        "random": random,
        # scipy.special
        "gamma": gamma, "factorial": factorial, "comb": comb,
        "erf": erf, "erfc": erfc, "erfinv": erfinv,
        "j0": j0, "j1": j1, "jn": jn, "yn": yn,
        "legendre": legendre,
        "logsumexp": logsumexp,
        # scipy.linalg
        "norm": norm, "det": det, "inv": inv, "solve": solve,
        "eig": eig, "eigvals": eigvals, "svd": svd,
        # No builtins
        "__builtins__": {},
    }
    return ns


