"""
Dependency graph for the cell evaluation engine.

Nodes are cell_ids.  Edge (A → B) means "B depends on A" — i.e., B uses
a name that A defines.

Public API
----------
build_dag(cells)             → nx.DiGraph
topo_order(dag, cells)       → (ordered_cells, cyclic_cell_ids)
downstream_of(dag, id, cells)→ cells that transitively depend on cell_id
undefined_names(cells)       → {cell_id: [name, ...]} for truly missing names
"""

from __future__ import annotations

import networkx as nx

from pringle.safety import get_store_names, get_free_names
from pringle.preprocess import SPATIAL_NAMES


_ALWAYS_DEFINED: set[str] | None = None


def _always_defined() -> set[str]:
    """Names always in scope — equation namespace + spatial + Python literals."""
    global _ALWAYS_DEFINED
    if _ALWAYS_DEFINED is None:
        from pringle.namespace import build_equation_namespace
        _ALWAYS_DEFINED = (
            set(build_equation_namespace().keys())
            | SPATIAL_NAMES
            | {"t", "True", "False", "None"}
        )
    return _ALWAYS_DEFINED


# ---------------------------------------------------------------------------
# Per-cell define / use sets
# ---------------------------------------------------------------------------

def _preprocess_src(src: str) -> str:
    """Return preprocessed source, falling back to raw on error."""
    from pringle.preprocess import preprocess
    try:
        preprocessed, _ = preprocess(src)
        return preprocessed
    except Exception:
        return src


def cell_defines(cell) -> set[str]:
    """Names this cell stores into the shared namespace."""
    from pringle.slider_widget import SliderWidget
    if isinstance(cell, SliderWidget):
        return {cell.name}
    src = cell.source().strip()
    if not src:
        return set()
    try:
        return get_store_names(_preprocess_src(src))
    except Exception:
        return set()


def cell_uses(cell) -> set[str]:
    """Names this cell reads from the shared namespace (excluding always-defined)."""
    from pringle.slider_widget import SliderWidget
    if isinstance(cell, SliderWidget):
        return set()
    src = cell.source().strip()
    if not src:
        return set()
    try:
        uses = get_free_names(_preprocess_src(src)) - _always_defined()
        # Also collect external deps from recurrence/initial_condition sub-cells so
        # the DAG correctly orders upstream cells (e.g. dL, dt) before the path cell.
        for sub in getattr(cell, "_sub_cells", []):
            if not hasattr(sub, "sub_type"):
                continue
            if sub.sub_type() not in ("recursion", "initial_condition"):
                continue
            sub_src = sub.source().strip()
            if not sub_src:
                continue
            try:
                sub_uses = get_free_names(_preprocess_src(sub_src)) - _always_defined()
                sub_uses.discard("n")  # 'n' is the recurrence loop variable, not an external dep
                uses |= sub_uses
            except Exception:
                pass
        return uses
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_dag(cells: list) -> nx.DiGraph:
    """
    Build a DAG from cells.  Edge (A → B) means B depends on A.
    All cells are added as nodes even if they have no edges.
    """
    g = nx.DiGraph()
    for cell in cells:
        g.add_node(cell.cell_id)

    # name → list of cell_ids that define it
    name_to_definers: dict[str, list[str]] = {}
    for cell in cells:
        for name in cell_defines(cell):
            name_to_definers.setdefault(name, []).append(cell.cell_id)

    for cell in cells:
        for name in cell_uses(cell):
            for definer_id in name_to_definers.get(name, []):
                if definer_id != cell.cell_id:
                    g.add_edge(definer_id, cell.cell_id)

    return g


# ---------------------------------------------------------------------------
# Ordering and analysis
# ---------------------------------------------------------------------------

def topo_order(dag: nx.DiGraph, cells: list) -> tuple[list, set[str]]:
    """
    Return (cells_in_topological_order, cyclic_cell_ids).

    If no cycles: cells are in dependency-first order.
    If cycles exist: cells are returned in original visual order and the
    cyclic cell_ids are returned so callers can flag them.
    """
    try:
        sorted_ids = list(nx.topological_sort(dag))
        id_to_cell = {c.cell_id: c for c in cells}
        ordered = [id_to_cell[cid] for cid in sorted_ids if cid in id_to_cell]
        return ordered, set()
    except nx.NetworkXUnfeasible:
        cycles = list(nx.simple_cycles(dag))
        cyclic_ids: set[str] = {cid for cycle in cycles for cid in cycle}
        return list(cells), cyclic_ids


def downstream_of(dag: nx.DiGraph, cell_id: str, cells: list) -> list:
    """
    Return cells that transitively depend on cell_id, in topological order.
    The cell itself is not included in the result.
    """
    if cell_id not in dag:
        return []
    descendant_ids = nx.descendants(dag, cell_id)
    if not descendant_ids:
        return []
    id_to_cell = {c.cell_id: c for c in cells}
    sub = dag.subgraph(descendant_ids)
    try:
        ordered_ids = list(nx.topological_sort(sub))
    except nx.NetworkXUnfeasible:
        ordered_ids = list(descendant_ids)
    return [id_to_cell[cid] for cid in ordered_ids if cid in id_to_cell]


def undefined_names(cells: list) -> dict[str, list[str]]:
    """
    Return {cell_id: [name, ...]} for names used by a cell that are not
    defined by any cell or the built-in namespace.
    """
    all_defined = set(_always_defined())
    for cell in cells:
        all_defined.update(cell_defines(cell))

    result: dict[str, list[str]] = {}
    for cell in cells:
        from pringle.slider_widget import SliderWidget
        if isinstance(cell, SliderWidget):
            continue
        missing = sorted(n for n in cell_uses(cell) if n not in all_defined)
        if missing:
            result[cell.cell_id] = missing
    return result
