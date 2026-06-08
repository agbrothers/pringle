"""
Python script exporter for Pringle sessions.

Converts a live CellListWidget into a standalone .py file that reproduces
the session's computed outputs without the Pringle runtime.

Public API
----------
export_as_script(path, cell_list)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pringle.cell_list import CellListWidget


# Names that Pringle pre-imports from each package so cells can use them unqualified.
# Used by export_as_script to emit only the subset actually referenced in the session.
_NUMPY_NAMES: frozenset[str] = frozenset({
    "sin", "cos", "tan", "arcsin", "arccos", "arctan", "arctan2", "hypot",
    "sinh", "cosh", "tanh", "arcsinh", "arccosh", "arctanh",
    "abs", "floor", "ceil", "round", "sign", "clip", "mod", "int_", "intp",
    "exp", "exp2", "log", "log2", "log10", "sqrt", "cbrt", "power",
    "zeros", "ones", "empty", "full",
    "zeros_like", "ones_like", "empty_like", "full_like",
    "linspace", "arange", "meshgrid",
    "array", "asarray", "concatenate",
    "stack", "column_stack", "row_stack", "hstack", "vstack",
    "reshape", "ravel", "transpose", "squeeze",
    "sum", "prod", "cumsum", "cumprod",
    "min", "max", "mean", "median", "std", "var", "maximum", "minimum",
    "diff", "gradient", "dot", "cross", "outer", "einsum",
    "where", "select", "isnan", "isinf", "isfinite",
    "logical_and", "logical_or", "logical_not",
    "any", "all",
    "pi", "e", "inf", "nan",
    "float32", "float64", "int32", "int64", "complex64", "complex128", "bool_",
})
_SCIPY_SPECIAL_NAMES: frozenset[str] = frozenset({
    "gamma", "factorial", "comb", "erf", "erfc", "erfinv",
    "j0", "j1", "jn", "yn", "legendre", "logsumexp",
})
_SCIPY_LINALG_NAMES: frozenset[str] = frozenset({
    "norm", "det", "inv", "solve", "eig", "eigvals", "svd",
})

# Spatial/context variable names injected by Pringle's runtime.
_SPATIAL_NAMES: frozenset[str] = frozenset({"x", "y", "u", "v", "cfg", "camera"})


def _collect_free_names(cells: list) -> set[str]:
    """Return all free names across all evaluable cells (main source + sub-cells)."""
    from pringle.ast_utils import get_free_names
    from pringle.preprocess import preprocess
    from pringle.folder_cell_widget import FolderCellWidget
    from pringle.comment_cell_widget import CommentCellWidget
    from pringle.slider_widget import SliderWidget

    used: set[str] = set()
    for cell in cells:
        if isinstance(cell, (FolderCellWidget, CommentCellWidget, SliderWidget)):
            continue
        src = cell.source().strip()
        if not src:
            continue
        preprocessed, _ = preprocess(src)
        try:
            used.update(get_free_names(preprocessed))
        except Exception:
            pass
        for s in getattr(cell, "_sub_cells", []):
            sub_src = s.source().strip()
            if sub_src:
                try:
                    used.update(get_free_names(sub_src))
                except Exception:
                    pass
    return used


def _build_preamble(used_names: set[str]) -> list[str]:
    """Build minimal import lines for names actually referenced in the session."""
    lines = ["import numpy as np", "import math"]

    numpy_used = sorted(used_names & _NUMPY_NAMES)
    if numpy_used:
        # Wrap at 4 names per line for readability.
        chunks = [numpy_used[i:i + 4] for i in range(0, len(numpy_used), 4)]
        if len(chunks) == 1:
            lines.append(f"from numpy import {', '.join(chunks[0])}")
        else:
            lines.append("from numpy import (")
            for chunk in chunks:
                lines.append(f"    {', '.join(chunk)},")
            lines.append(")")

    if "random" in used_names:
        lines.append("import numpy.random as random")

    scipy_sp = sorted(used_names & _SCIPY_SPECIAL_NAMES)
    if scipy_sp:
        lines.append(f"from scipy.special import {', '.join(scipy_sp)}")

    scipy_la = sorted(used_names & _SCIPY_LINALG_NAMES)
    if scipy_la:
        lines.append(f"from scipy.linalg import {', '.join(scipy_la)}")

    lines.append("")
    return lines


def _build_spatial_setup(used_names: set[str], config) -> list[str]:
    """
    Emit setup code for Pringle runtime variables referenced in the session.

    cfg       — axis bounds config (SimpleNamespace matching AxisConfig fields)
    x, y      — 2-D meshgrid arrays matching the session grid
    u, v      — parametric meshgrid arrays
    camera    — camera state stub (all fields zero / default position)
    """
    needed = used_names & _SPATIAL_NAMES
    if not needed:
        return []

    needs_cfg = "cfg" in needed or bool({"x", "y", "u", "v"} & needed)
    needs_camera = "camera" in needed

    lines: list[str] = ["# --- Pringle spatial setup (from session grid config) ---"]

    if needs_cfg or needs_camera:
        lines.append("import types")

    if needs_cfg:
        lines += [
            "cfg = types.SimpleNamespace(",
            f"    x_min={config.x_min!r}, x_max={config.x_max!r},",
            f"    y_min={config.y_min!r}, y_max={config.y_max!r},",
            f"    z_min={config.z_min!r}, z_max={config.z_max!r},",
            f"    n={config.n},",
            ")",
        ]

    if {"x", "y"} & needed:
        lines += [
            "_x1d = np.linspace(cfg.x_min, cfg.x_max, cfg.n)",
            "_y1d = np.linspace(cfg.y_min, cfg.y_max, cfg.n)",
            "x, y = np.meshgrid(_x1d, _y1d, indexing='xy')",
        ]

    if {"u", "v"} & needed:
        lines += [
            f"_u1d = np.linspace({config.u_min!r}, {config.u_max!r}, cfg.n)",
            f"_v1d = np.linspace({config.v_min!r}, {config.v_max!r}, cfg.n)",
            "u, v = np.meshgrid(_u1d, _v1d, indexing='xy')",
        ]

    if needs_camera:
        lines.append(
            "camera = types.SimpleNamespace("
            "x=0.0, y=0.0, z=10.0, target_x=0.0, target_y=0.0, target_z=0.0, roll=0.0)"
        )

    lines.append("")
    return lines


def _has_top_level_def(source: str) -> bool:
    """Return True if source contains a top-level function definition."""
    import ast as _ast
    try:
        tree = _ast.parse(source, mode="exec")
        return any(isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)) for n in tree.body)
    except SyntaxError:
        return False


def _emit_non_eval(cell, lines: list[str]) -> None:
    """Append the text representation of a folder or comment cell to *lines*."""
    from pringle.folder_cell_widget import FolderCellWidget

    if isinstance(cell, FolderCellWidget):
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"# --- {cell.name} ---")
    else:  # CommentCellWidget
        src = cell.source().strip()
        if not src:
            lines.append("")
            return
        for ln in src.splitlines():
            stripped = ln.strip()
            if stripped.startswith("#") or not stripped:
                lines.append(stripped)
            else:
                lines.append(f"# {stripped}")


def _build_emit_before(
    all_cells: list,
    ordered_evaluable: list,
    cell_folder: dict,
) -> tuple[dict, list]:
    """
    Pre-compute which non-evaluable cells to emit immediately before each
    evaluable cell.

    Folders: anchored to their first evaluable member cell in topo order.
    Comments: anchored to the next evaluable cell in visual order.

    Returns:
        emit_before  dict[cell_id → list of non-eval cells to emit before it]
        trailing     list of non-eval cells with no evaluable anchor
    """
    from pringle.folder_cell_widget import FolderCellWidget
    from pringle.comment_cell_widget import CommentCellWidget

    # folder_id → first evaluable member cell_id (in topo order)
    folder_first_topo: dict[str, str] = {}
    for cell in ordered_evaluable:
        fid = cell_folder.get(cell.cell_id)
        if fid and fid not in folder_first_topo:
            folder_first_topo[fid] = cell.cell_id

    visual_pos = {c.cell_id: i for i, c in enumerate(all_cells)}
    # Evaluable cells sorted by visual position (for comment anchoring)
    eval_by_visual = sorted(
        ordered_evaluable, key=lambda c: visual_pos[c.cell_id]
    )

    emit_before: dict[str, list] = {}
    trailing: list = []

    for cell in all_cells:  # iterate in visual order
        if not isinstance(cell, (FolderCellWidget, CommentCellWidget)):
            continue
        if isinstance(cell, FolderCellWidget):
            anchor_id = folder_first_topo.get(cell.cell_id)
            if anchor_id:
                emit_before.setdefault(anchor_id, []).append(cell)
            else:
                trailing.append(cell)
        else:  # CommentCellWidget — anchor to next evaluable cell in visual order
            vis = visual_pos[cell.cell_id]
            anchor = next(
                (c for c in eval_by_visual if visual_pos[c.cell_id] > vis),
                None,
            )
            if anchor:
                emit_before.setdefault(anchor.cell_id, []).append(cell)
            else:
                trailing.append(cell)

    return emit_before, trailing


def export_as_script(
    path: str | Path,
    cell_list: CellListWidget,
) -> None:
    """
    Write a standalone Python script that reproduces the session's computed outputs.

    Cells are emitted in topological (dependency) order so every name is defined
    before it is used.  Comment and folder cells are anchored to the evaluable
    cell they naturally precede in visual order; folders anchor to the first
    topo-ordered member cell.
    """
    from pringle.dag import build_dag, topo_order
    from pringle.preprocess import preprocess, MAGIC_NAMES
    from pringle.folder_cell_widget import FolderCellWidget
    from pringle.comment_cell_widget import CommentCellWidget
    from pringle.slider_widget import SliderWidget
    from pringle.ast_utils import get_store_names

    all_cells = cell_list._cells
    evaluable = [c for c in all_cells if not isinstance(c, (FolderCellWidget, CommentCellWidget))]

    dag = build_dag(evaluable)
    ordered_evaluable, _ = topo_order(dag, evaluable)

    emit_before, trailing = _build_emit_before(
        all_cells, ordered_evaluable, cell_list._cell_folder
    )

    magic_sinks: list[str] = []
    lines: list[str] = []

    # --- Preamble: only import names actually used in the session ---
    used_names = _collect_free_names(all_cells)
    lines += _build_preamble(used_names)
    lines += _build_spatial_setup(used_names, cell_list._grid.config)

    for cell in ordered_evaluable:
        # Emit any folders/comments anchored before this cell.
        for non_eval_cell in emit_before.get(cell.cell_id, []):
            _emit_non_eval(non_eval_cell, lines)

        if isinstance(cell, SliderWidget):
            val: int | float = int(round(cell.value)) if cell.value % 1 == 0 else cell.value
            lines.append(f"{cell.name} = {val!r}  # slider")
            continue

        src = cell.source().strip()
        if not src:
            continue

        preprocessed, _func_name = preprocess(src)
        sub_cells = getattr(cell, "_sub_cells", [])

        rec_rules = [s.source().strip() for s in sub_cells
                     if s.sub_type() == "recursion" and s.source().strip()]
        init_conds = [s.source().strip() for s in sub_cells
                      if s.sub_type() == "initial_condition" and s.source().strip()]

        if rec_rules or init_conds:
            # --- Recurrence cell: emit init → initial conditions → for loop ---
            import re as _re
            lines.append(preprocessed)
            for ic in init_conds:
                lines.append(ic)
            if rec_rules:
                # Infer the array name from the LHS of the first rule: `arr[n] = …`
                m = _re.match(r"(\w+)\s*[\[,]", rec_rules[0])
                arr_name = m.group(1) if m else None
                if arr_name:
                    lines.append(f"for n in range(1, len({arr_name})):")
                    for rule in rec_rules:
                        lines.append(f"    {rule}")
                else:
                    lines.append("# WARNING: recurrence — could not infer loop bound; adapt manually")
                    for rule in rec_rules:
                        lines.append(f"# {rule}")
        else:
            # --- Regular equation cell ---
            is_func_def = _has_top_level_def(preprocessed)
            if is_func_def and lines and lines[-1] != "":
                lines.append("")
            lines.append(preprocessed)
            # Constraints and conditions as comments.
            for s in sub_cells:
                if s.sub_type() in ("constraint", "condition"):
                    sub_src = s.source().strip()
                    if sub_src:
                        lines.append(f"# ({s.sub_type()}): {sub_src}")
            if is_func_def:
                lines.append("")

        # Collect magic output variable names for the trailing note.
        try:
            stores = get_store_names(preprocessed)
            for name in stores:
                if name in MAGIC_NAMES:
                    magic_sinks.append(name)
        except Exception:
            pass

    # Flush any trailing non-evaluable cells (no evaluable cell follows them).
    for non_eval_cell in trailing:
        _emit_non_eval(non_eval_cell, lines)

    # Trailing note about renderer-local variables.
    if magic_sinks:
        unique_sinks = sorted(set(magic_sinks))
        lines += [
            "",
            "# ---- Pringle renderer-local variables ----",
            "# The following names are assigned above but only auto-render inside Pringle.",
            "# Outside Pringle they are plain numpy arrays; no rendering occurs.",
        ]
        for name in unique_sinks:
            lines.append(f"# {name}")

    Path(path).write_text("\n".join(lines) + "\n")
