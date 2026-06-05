"""
Whitelisted evaluation namespace for equation cells.

Defines every name reachable from cell expressions. Adding a name requires
an explicit line here — not just `import numpy as np`. See
design-docs/14-namespace-reference.md for the full reference with rationale.
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
    Return a fresh namespace dict for exec()ing one equation cell.

    Contains whitelisted numpy/scipy names plus a curated set of safe Python
    builtins. '__builtins__' is set to {} to block all other builtins.
    See design-docs/14-namespace-reference.md for the full list and rationale.
    """
    ns: dict = {
        # --- numpy: trig ---
        "sin": sin, "cos": cos, "tan": tan,
        "arcsin": arcsin, "arccos": arccos, "arctan": arctan,
        "arctan2": arctan2, "hypot": hypot,
        "sinh": sinh, "cosh": cosh, "tanh": tanh,
        "arcsinh": arcsinh, "arccosh": arccosh, "arctanh": arctanh,
        # --- numpy: rounding / casting ---
        "abs": abs, "floor": floor, "ceil": ceil, "round": round,
        "sign": sign, "clip": clip, "mod": mod,
        "int_": int_, "intp": intp,
        # --- numpy: exponential / log ---
        "exp": exp, "exp2": exp2, "log": log, "log2": log2,
        "log10": log10, "sqrt": sqrt, "cbrt": cbrt, "power": power,
        # --- numpy: array creation ---
        "zeros": zeros, "ones": ones, "empty": empty, "full": full,
        "zeros_like": zeros_like, "ones_like": ones_like,
        "empty_like": empty_like, "full_like": full_like,
        "linspace": linspace, "arange": arange, "meshgrid": meshgrid,
        "array": array, "asarray": asarray,
        "concatenate": concatenate, "stack": stack,
        "column_stack": column_stack, "row_stack": row_stack,
        "hstack": hstack, "vstack": vstack,
        # --- numpy: shape ---
        "reshape": reshape, "ravel": ravel,
        "transpose": transpose, "squeeze": squeeze,
        # --- numpy: math ---
        "sum": sum, "prod": prod, "cumsum": cumsum, "cumprod": cumprod,
        "min": min, "max": max, "mean": mean, "median": median,
        "std": std, "var": var, "maximum": maximum, "minimum": minimum,
        "diff": diff, "gradient": gradient,
        "dot": dot, "cross": cross, "outer": outer, "einsum": einsum,
        # --- numpy: boolean / masking ---
        "where": where, "select": select,
        "isnan": isnan, "isinf": isinf, "isfinite": isfinite,
        "logical_and": logical_and, "logical_or": logical_or,
        "logical_not": logical_not,
        "any": any, "all": all,
        # --- numpy: constants ---
        "pi": pi, "e": e, "inf": inf, "nan": nan,
        # --- numpy: dtypes ---
        "float32": float32, "float64": float64,
        "int32": int32, "int64": int64,
        "complex64": complex64, "complex128": complex128,
        "bool_": bool_,
        # --- numpy: random ---
        "random": random,
        # --- scipy.special ---
        "gamma": gamma, "factorial": factorial, "comb": comb,
        "erf": erf, "erfc": erfc, "erfinv": erfinv,
        "j0": j0, "j1": j1, "jn": jn, "yn": yn,
        "legendre": legendre,
        "logsumexp": logsumexp,
        # --- scipy.linalg ---
        "norm": norm, "det": det, "inv": inv, "solve": solve,
        "eig": eig, "eigvals": eigvals, "svd": svd,
        # --- safe Python builtins ---
        # Type constructors: safe — dunder block prevents class-hierarchy traversal
        "bool": bool, "int": int, "float": float, "complex": complex,
        "str": str, "bytes": bytes,
        "tuple": tuple, "list": list, "dict": dict, "set": set,
        # Iterators / sequences
        "range": range, "enumerate": enumerate, "zip": zip,
        "sorted": sorted, "reversed": reversed, "len": len,
        # Type inspection
        "isinstance": isinstance, "issubclass": issubclass, "callable": callable,
        # No builtins beyond the above
        "__builtins__": {},
    }
    return ns
