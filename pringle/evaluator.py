"""
Expression cell evaluator.

Handles the full pipeline for a single equation cell:
  preprocess → safety check → exec → output detection →
  piecewise detection → constraint application → shape validation

Returns a CellResult describing what (if anything) should be rendered.
"""

from __future__ import annotations

import ast
import math
import traceback
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pringle.preprocess import (
    preprocess, is_comment_cell, is_slider_cell, get_func_auto_render,
    MAGIC_NAMES, SPATIAL_NAMES,
)
from pringle.safety import check_ast, SecurityError, get_free_names, get_store_names
from pringle.namespace import build_equation_namespace, build_data_namespace
from pringle.grid import Grid, grid_vars


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CellResult:
    """The outcome of evaluating one cell."""
    render_type: str | None = None   # "surface" | "curve" | "scatter" | "line" | None
    data: Any = None                  # numpy array ready for renderer (NaN where masked)
    data_unmasked: Any = None         # z array before constraint masking (all valid)
    constraint_mask: Any = None       # bool array, True = inside constraint
    x: np.ndarray | None = None      # grid x (surface only)
    y: np.ndarray | None = None      # grid y (surface only)
    warning: str | None = None       # shape mismatch / undefined var
    error: str | None = None         # execution error
    exports: dict = field(default_factory=dict)  # names to add to shared namespace
    is_slider: bool = False
    slider_name: str = ""
    slider_value: float = 0.0
    is_comment: bool = False
    free_names: set = field(default_factory=set)  # names this cell reads
    preview: str | None = None        # value preview: scalar value or 1D array elements
    shape_preview: str | None = None  # shape string shown in bottom-right for array outputs
    from_shape_inference: bool = False  # True when scatter was inferred from shape, not explicit magic name


# ---------------------------------------------------------------------------
# Output detection
# ---------------------------------------------------------------------------

def _detect_magic(local_ns: dict, grid: Grid, user_stores: set[str]) -> tuple[str | None, Any]:
    """
    Check local namespace for magic variable assignments made by the user.

    user_stores: names actually assigned by the cell source (from AST analysis).
    We only look for magic names in this set — grid-injected vars are excluded.

    Priority: z > xyz > y > x > points > vectors
    Returns (render_type, data) or (None, None).
    """
    if "z" in user_stores:
        return "surface", local_ns.get("z")
    if "xyz" in user_stores:
        return "parametric", local_ns.get("xyz")
    if "y" in user_stores:
        val = local_ns.get("y")
        if isinstance(val, np.ndarray) and val.ndim == 1:
            return "curve", val
        if isinstance(val, np.ndarray):
            return "surface_y", val
    if "x" in user_stores:
        val = local_ns.get("x")
        if isinstance(val, np.ndarray) and val.ndim == 1:
            return "curve_x", val
    if "points" in user_stores:
        return "scatter", local_ns.get("points")

    # Fallback: any user-assigned variable whose shape looks plottable
    for name in user_stores:
        if name in MAGIC_NAMES or name in SPATIAL_NAMES:
            continue
        rt, data = _detect_shape(local_ns.get(name))
        if rt is not None:
            return rt, data

    return None, None


def _detect_shape(val: Any) -> tuple[str | None, Any]:
    """
    Infer render type from the shape of a bare expression return value.

    Returns (render_type, data) or (None, None) if not plottable.
    """
    if not isinstance(val, np.ndarray):
        return None, None
    if val.ndim == 2 and val.shape[1] == 3:
        return "scatter", val
    if val.ndim == 2 and val.shape[1] == 2:
        return "scatter_2d", val
    if val.shape == (3,):
        return "scatter", val.reshape(1, 3)
    if val.shape == (2,):
        return "scatter_2d", val.reshape(1, 2)
    return None, None


def _fmt_scalar(x) -> str:
    f = float(x)
    if not math.isfinite(f):
        return str(f)
    return str(int(f)) if f == int(f) and abs(f) < 1e15 else f"{f:g}"


def _make_preview(val, max_chars: int = 60) -> str | None:
    """Format a scalar or short 1D array for the cell preview label."""
    if isinstance(val, (bool, np.bool_)):
        return str(bool(val))
    if isinstance(val, (int, np.integer)):
        return str(int(val))
    if isinstance(val, (float, np.floating)):
        return _fmt_scalar(val)
    if isinstance(val, np.ndarray) and val.ndim == 1:
        parts = [_fmt_scalar(x) for x in val]
        full = "[" + ", ".join(parts) + "]"
        if len(full) <= max_chars:
            return full
        shown: list[str] = []
        for p in parts:
            if shown and len("[" + ", ".join(shown + [p]) + ", ...]") > max_chars:
                break
            shown.append(p)
        return "[" + ", ".join(shown) + ", ...]"
    return None


# ---------------------------------------------------------------------------
# Constraint application
# ---------------------------------------------------------------------------

def apply_constraints(
    z: np.ndarray,
    constraint_exprs: list[str],
    ns: dict,
    return_mask: bool = False,
) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
    """
    Apply boolean constraint expressions to a surface array.

    Each constraint is eval()ed with x, y, and z in scope.  The combined
    mask is the AND of all constraints.  Masked positions become NaN
    (degenerate triangles are skipped by the renderer).

    If return_mask is True, returns (z_masked, inside_mask) where inside_mask
    is the boolean array of vertices inside all constraints.
    """
    if not constraint_exprs:
        if return_mask:
            return z, np.ones(z.shape, dtype=bool)
        return z

    masks = []
    for expr in constraint_exprs:
        try:
            local = {**ns, "z": z}
            mask = eval(expr, {"__builtins__": {}}, local)  # noqa: S307
            masks.append(np.asarray(mask, dtype=bool))
        except Exception:
            pass  # bad constraint — ignore, don't crash

    if not masks:
        if return_mask:
            return z, np.ones(z.shape, dtype=bool)
        return z

    combined = np.logical_and.reduce(masks)
    z_masked = np.where(combined, z, np.nan)
    if return_mask:
        return z_masked, combined
    return z_masked


# ---------------------------------------------------------------------------
# Piecewise detection and evaluation
# ---------------------------------------------------------------------------

def _handle_piecewise(
    piece_list: list,
    condition_exprs: list[str],
    ns: dict,
    grid: Grid,
) -> tuple[np.ndarray, str | None]:
    """
    Evaluate a piecewise surface from a list of callables/arrays and condition expressions.

    Returns (z_array, warning_or_None).
    """
    if len(piece_list) != len(condition_exprs):
        return np.full(grid.x.shape, np.nan), (
            f"Piecewise: {len(piece_list)} pieces but "
            f"{len(condition_exprs)} conditions — rendering suppressed"
        )

    # Evaluate each piece over the grid
    pieces = []
    for p in piece_list:
        if callable(p):
            try:
                pieces.append(np.asarray(p(grid.x, grid.y), dtype=np.float32))
            except Exception as exc:
                return np.full(grid.x.shape, np.nan), f"Piecewise piece error: {exc}"
        else:
            pieces.append(np.asarray(p, dtype=np.float32))

    # Build exclusive conditions (implicit prior-negation)
    raw_conditions = []
    for expr in condition_exprs:
        try:
            raw_conditions.append(
                np.asarray(eval(expr, {"__builtins__": {}}, ns), dtype=bool)  # noqa: S307
            )
        except Exception:
            raw_conditions.append(np.zeros(grid.x.shape, dtype=bool))

    exclusive, accumulated = [], np.zeros(grid.x.shape, dtype=bool)
    for cond in raw_conditions:
        excl = cond & ~accumulated
        exclusive.append(excl)
        accumulated |= cond

    z = np.select(exclusive, pieces, default=np.nan).astype(np.float32)
    return z, None


# ---------------------------------------------------------------------------
# Shape validation
# ---------------------------------------------------------------------------

_EXPECTED_SHAPES = {
    "surface":     "2D array matching grid shape",
    "parametric":  "(3, N, M) or (3, N) array",
    "curve":       "1D array matching x-grid length",
    "scatter":     "(N, 3) or (N, 2) array",
}


def validate_shape(render_type: str, data: Any, grid: Grid) -> str | None:
    """
    Return a warning string if data has an unexpected shape, else None.
    """
    if data is None:
        return None

    if render_type == "surface":
        if not isinstance(data, np.ndarray) or data.ndim != 2:
            return f"Expected 2D array for z, got {type(data).__name__}"
        if data.shape != grid.x.shape:
            return f"z shape {data.shape} doesn't match grid {grid.x.shape}"

    elif render_type == "curve":
        if not isinstance(data, np.ndarray) or data.ndim != 1:
            return f"Expected 1D array for y, got shape {getattr(data, 'shape', '?')}"
        if len(data) != len(grid.x1d):
            return f"y length {len(data)} doesn't match x-grid length {len(grid.x1d)}"

    elif render_type == "scatter":
        if not isinstance(data, np.ndarray) or data.ndim != 2:
            return f"Expected (N, 2) or (N, 3) array for points, got {getattr(data, 'shape', '?')}"
        if data.shape[1] not in (2, 3):
            return f"points must have 2 or 3 columns, got {data.shape[1]}"

    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_cell(
    source: str,
    shared_namespace: dict,
    grid: Grid,
    t: float = 0.0,
    constraint_exprs: list[str] | None = None,
    condition_exprs: list[str] | None = None,
    is_data_cell: bool = False,
) -> CellResult:
    """
    Evaluate one cell and return a CellResult.

    Parameters
    ----------
    source            : raw cell source text
    shared_namespace  : the cumulative namespace from all prior cells
    grid              : current spatial grid
    t                 : current animation time
    constraint_exprs  : list of boolean expr strings (constraint sub-cells)
    condition_exprs   : list of boolean expr strings (piecewise conditions)
    is_data_cell      : skip AST safety check for data panel cells
    """
    result = CellResult()
    constraint_exprs = constraint_exprs or []
    condition_exprs  = condition_exprs  or []

    # --- Comment cell ---
    if is_comment_cell(source):
        result.is_comment = True
        return result

    # --- Slider cell ---
    ok, sname, sval = is_slider_cell(source)
    if ok:
        result.is_slider    = True
        result.slider_name  = sname
        result.slider_value = sval
        result.exports      = {sname: sval}
        result.free_names   = set()
        return result

    # --- Free-variable analysis (always) ---
    try:
        preprocessed, func_name = preprocess(source)
    except Exception as exc:
        result.error = f"Preprocess error: {exc}"
        return result

    result.free_names = get_free_names(preprocessed)
    user_stores = get_store_names(preprocessed)

    # --- Safety check (equation cells only) ---
    if not is_data_cell:
        try:
            check_ast(preprocessed)
        except (SecurityError, SyntaxError) as exc:
            result.error = str(exc)
            return result

    # --- Build execution namespace ---
    # Layer 1: whitelist (data cells get full numpy alias `np`)
    local_ns = build_data_namespace() if is_data_cell else build_equation_namespace()
    # Layer 2+3+4: shared namespace (sliders, lambdas, data outputs)
    local_ns.update(shared_namespace)
    # Layer 5: grid vars (highest priority — cannot be shadowed)
    local_ns.update(grid_vars(grid, t))

    # --- Execute ---
    # np.errstate suppresses floating-point warnings (NaN from sqrt of negative,
    # divide by zero, etc.) so they don't trigger __import__ via the warning
    # system — which would fail because __builtins__ is disabled.
    try:
        with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
            exec(preprocessed, local_ns)  # noqa: S102
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    # --- Export: anything new the cell defined goes to shared namespace ---
    # Exclude magic names, grid vars, and the whitelist.
    base_keys = set(build_equation_namespace().keys()) | set(grid_vars(grid).keys())
    for k, v in local_ns.items():
        if k.startswith("__"):
            continue
        if k in base_keys:
            continue
        if k not in MAGIC_NAMES:
            result.exports[k] = v

    # --- Output detection ---
    render_type, data = _detect_magic(local_ns, grid, user_stores)
    # Scatter detected via shape (not explicit `points = ...`) → data-array mode
    result.from_shape_inference = (
        render_type in ("scatter", "scatter_2d") and "points" not in user_stores
    )

    # Auto-render for function definitions: f(x,y) = expr → evaluate as surface
    if render_type is None and func_name is not None:
        # Determine what spatial args the function expects
        m = __import__("re").match(r"(\w+)\s*=\s*lambda\s*([^:]+):", preprocessed)
        if m:
            args_str = m.group(2)
            magic = get_func_auto_render(func_name, args_str)
            if magic == "z":
                try:
                    z_auto = local_ns[func_name](grid.x, grid.y)
                    render_type, data = "surface", np.asarray(z_auto, dtype=np.float32)
                except Exception:
                    pass
            elif magic == "y":
                try:
                    y_auto = local_ns[func_name](grid.x1d)
                    render_type, data = "curve", np.asarray(y_auto, dtype=np.float32)
                except Exception:
                    pass
            elif magic == "xyz":
                try:
                    xyz_auto = local_ns[func_name](grid.u, grid.v)
                    render_type, data = "parametric", np.asarray(xyz_auto, dtype=np.float32)
                except Exception:
                    pass

    # No magic name, no func → check for piecewise list
    if render_type is None:
        for magic in MAGIC_NAMES:
            if magic in local_ns and isinstance(local_ns[magic], list):
                piece_list = local_ns[magic]
                if condition_exprs:
                    z, warn = _handle_piecewise(piece_list, condition_exprs, local_ns, grid)
                    render_type, data = "surface", z
                    if warn:
                        result.warning = warn
                        return result
                else:
                    result.warning = (
                        f"'{magic}' is a list of {len(piece_list)} pieces "
                        f"but no condition sub-cells are defined"
                    )
                break

    # Value preview: first previewable (scalar or 1D) user-defined variable
    for name in user_stores:
        if name in MAGIC_NAMES or name in SPATIAL_NAMES:
            continue
        try:
            preview = _make_preview(local_ns.get(name))
        except Exception:
            preview = None
        if preview is not None:
            result.preview = preview
            break

    # Bare expression (no assignment): eval source to capture value for preview
    if result.preview is None and not user_stores and func_name is None:
        try:
            val = eval(preprocessed, local_ns, {})  # noqa: S307
            result.preview = _make_preview(val)
            if isinstance(val, np.ndarray):
                result.shape_preview = str(val.shape)
        except Exception:
            pass

    if render_type is None:
        return result

    # --- Piecewise evaluation (if z is already a list and conditions given) ---
    if render_type == "surface" and isinstance(data, list):
        z, warn = _handle_piecewise(data, condition_exprs, local_ns, grid)
        data = z
        if warn:
            result.warning = warn
            return result

    # --- Normalize surface data ---
    if render_type == "surface":
        data = np.asarray(data, dtype=np.float32)
        # Apply constraints — keep raw z for smooth boundary clipping in renderer
        if constraint_exprs:
            z_raw = data.copy()
            data, inside_mask = apply_constraints(data, constraint_exprs, local_ns, return_mask=True)
            result.data_unmasked = z_raw
            result.constraint_mask = inside_mask
        result.x = grid.x
        result.y = grid.y

    elif render_type == "curve":
        data = np.asarray(data, dtype=np.float32)

    elif render_type in ("scatter", "scatter_2d"):
        data = np.asarray(data, dtype=np.float32)

    elif render_type == "parametric":
        data = np.asarray(data, dtype=np.float32)

    # --- Shape validation ---
    warn = validate_shape(render_type, data, grid)
    if warn:
        result.warning = warn
        return result

    result.render_type = render_type
    result.data = data
    if isinstance(data, np.ndarray):
        result.shape_preview = str(data.shape)
    return result
