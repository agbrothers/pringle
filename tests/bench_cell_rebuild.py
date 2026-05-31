"""
tests/bench_cell_rebuild.py

Headless benchmark for the expression-panel _rebuild_namespace path using
the bench-panel-rebuild.yml session (a generic potential-field + gradient-descent
config that isolates PERF-016).

This is a different performance context from bench_slider_animation.py:
  - Slider animation: measures the incremental downstream-only re-eval path
  - Cell rebuild:    measures the FULL re-evaluation of ALL cells, which fires
                     on every add_cell / remove_cell / drag / move / undo call

PERF-016 regression targets:
  traj       — data-mode recurrence: T Python eval() steps × k particles × grad_E
  traj_3d    — data-mode: calls E on T×k = 40,000 query points

Before PERF-016 fix:  ~1-2 s per add/remove/edit cell event
After PERF-016 fix:   ~50 ms (traj and traj_3d skipped when upstream unchanged)

Usage:
    python tests/bench_cell_rebuild.py
    python tests/bench_cell_rebuild.py --n 128 --frames 5
    python tests/bench_cell_rebuild.py --n 128 --frames 5 --mem
    python -m cProfile -s cumulative tests/bench_cell_rebuild.py | head -80
    kernprof -l -v tests/bench_cell_rebuild.py

See design-docs/20-profiling-sop.md for interpretation guidance.
"""

from __future__ import annotations

import argparse
import gc
import statistics
import time
import tracemalloc

import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _timeit(fn, n: int, warmup: int = 2) -> list[float]:
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    return times


def _stats(times: list[float]) -> tuple[float, float]:
    if not times:
        return 0.0, 0.0
    return statistics.mean(times), sorted(times)[int(len(times) * 0.95)]


def _fmt_row(label: str, times: list[float]) -> str:
    if not times:
        return f"  {label:<44} │  {'n/a':>8}  │  {'n/a':>7}"
    mean, p95 = _stats(times)
    return f"  {label:<44} │  {mean:>8.2f}  │  {p95:>7.2f}"


# ---------------------------------------------------------------------------
# Cell definitions matching bench-panel-rebuild.yml (topological order)
#
# Slider values
SLIDERS = {
    "k":  400.0,   # number of source / particle points
    "T":  100.0,   # gradient-descent steps
    "β":  4.0,     # potential bandwidth
    "lr": 0.05,    # gradient step size
}

# (name, source, rng_seed, recurrence_rule, initial_conditions)
# Cells in topological (dependency-first) order
CELLS = [
    # ── POTENTIAL FIELD ──────────────────────────────────────────────────────
    # sources: k random 2D source points in [-4,4]^2
    ("sources",   "sources = random.random((k, 2)) * 8 - 4",                0, None, None),
    # D: pairwise negative-squared distances via matmul — no (K,D,N) intermediate
    ("D",         "D(M, v) = -(sum(M**2, axis=1)[:,None] + sum(v**2, axis=0)[None,:] - 2*(M@v))",
                  0, None, None),
    ("β_inv",     "β_inv = 1/β",                                             0, None, None),
    ("E",         "E(v) = -β_inv * logsumexp(β * D(sources, v), axis=0)",   0, None, None),
    ("grid_pts",  "grid_pts = array([x, y]).reshape(2, -1)",                 0, None, None),
    ("grid_shape","grid_shape = x.shape",                                    0, None, None),
    # z: energy surface — moderately expensive (E on 16,384 grid points)
    ("z",         "z = E(grid_pts).reshape(*grid_shape)",                   0, None, None),
    # sources_3d: source points lifted onto the energy surface
    ("sources_3d","sources_3d = concatenate((sources, E(sources.T)[:,None]), axis=1)",
                  0, None, None),
    # ── TRAJECTORIES (PERF-016 regression targets) ────────────────────────────
    # W: softmax attention weights — avoids the (K,D,N) intermediate
    ("W",         "W(M, v) = exp(β * D(M, v) - logsumexp(β * D(M, v), axis=0))",
                  0, None, None),
    # grad_E: gradient of E w.r.t. v; returns (2, N) — uses BLAS matmul only
    ("grad_E",    "grad_E(M, v) = 2 * (v - M.T @ W(M, v))",                0, None, None),
    # traj: data-mode recurrence, T steps × k particles → (T, k, 2) scatter_batch_2d
    ("traj",      "traj = zeros((T, k, 2))",
                  7,
                  "traj[n] = traj[n-1] - lr * grad_E(sources, traj[n-1].T).T",
                  ["traj[0] = random.random((k, 2)) * 10 - 5"]),
    # traj_3d: data-mode, calls E on T*k points → (k, T, 3) scatter_batch
    ("traj_3d",   "traj_3d = concatenate((\n    traj,\n    E(traj.reshape(-1, 2).T).reshape(T, k, 1) + 0.03,\n) , axis=-1).transpose(1, 0, 2)",
                  0, None, None),
]
# ---------------------------------------------------------------------------


def _build_shared(grid) -> dict:
    """Build shared namespace with sliders + grid vars."""
    from pringle.namespace import build_equation_namespace
    from pringle.grid import grid_vars

    ns = build_equation_namespace()
    for name, val in SLIDERS.items():
        ns[name] = int(val) if val == int(val) else val
    ns.update(grid_vars(grid))
    return ns


# ---------------------------------------------------------------------------
# Section 1 — Per-cell timing: run_cell for each evaluable cell
# ---------------------------------------------------------------------------

def bench_per_cell(grid, n_frames: int) -> dict[str, list[float]]:
    """
    Time run_cell() + execute_recurrence() for each cell in bench-panel-rebuild.
    Returns per-cell timing and the total full-rebuild cost.
    """
    from pringle.evaluator import run_cell
    from pringle.recurrence import parse_recurrence, execute_recurrence
    from pringle.namespace import build_equation_namespace

    results: dict[str, list[float]] = {}
    total_times: list[float] = []

    def _one_rebuild():
        ns = _build_shared(grid)
        t_total = 0.0
        cell_times = {}
        for cell_name, src, rng_seed, rec_rule, init_exprs in CELLS:
            ns["random"] = np.random.RandomState(rng_seed)
            t0 = time.perf_counter()
            result = run_cell(src, ns, grid)
            if rec_rule and not result.error:
                is_valid, arr_name, _ = parse_recurrence(rec_rule)
                if is_valid and arr_name in result.exports:
                    arr = result.exports[arr_name]
                    if isinstance(arr, np.ndarray):
                        rec_ns = {**build_equation_namespace(), **ns, **result.exports}
                        arr, _ = execute_recurrence(arr_name, arr, init_exprs or [], rec_rule, rec_ns)
                        result.exports[arr_name] = arr
            elapsed = (time.perf_counter() - t0) * 1000.0
            ns.update(result.exports)
            cell_times[cell_name] = elapsed
            t_total += elapsed
        return cell_times, t_total

    for _ in range(2):  # warmup
        _one_rebuild()

    for _ in range(n_frames):
        cell_times, t_total = _one_rebuild()
        for name, t in cell_times.items():
            results.setdefault(name, []).append(t)
        total_times.append(t_total)

    results["_TOTAL_REBUILD"] = total_times
    return results


# ---------------------------------------------------------------------------
# Section 2 — Recurrence isolation
# ---------------------------------------------------------------------------

def bench_recurrence_cells(grid, n_frames: int) -> dict[str, list[float]]:
    """
    Isolate execute_recurrence() cost for the traj cell.
    Pre-builds the namespace so only the recurrence loop is timed.
    """
    from pringle.evaluator import run_cell
    from pringle.recurrence import parse_recurrence, execute_recurrence
    from pringle.namespace import build_equation_namespace

    ns = _build_shared(grid)
    seed_cells = [
        ("sources",  "sources = random.random((k, 2)) * 8 - 4", 0),
        ("D",        "D(M, v) = -(sum(M**2, axis=1)[:,None] + sum(v**2, axis=0)[None,:] - 2*(M@v))", 0),
        ("β_inv",    "β_inv = 1/β", 0),
        ("E",        "E(v) = -β_inv * logsumexp(β * D(sources, v), axis=0)", 0),
        ("W",        "W(M, v) = exp(β * D(M, v) - logsumexp(β * D(M, v), axis=0))", 0),
        ("grad_E",   "grad_E(M, v) = 2 * (v - M.T @ W(M, v))", 0),
    ]
    for cname, src, seed in seed_cells:
        ns["random"] = np.random.RandomState(seed)
        r = run_cell(src, ns, grid)
        ns.update(r.exports)

    base_rec_ns = {**build_equation_namespace(), **ns}
    k_val = int(SLIDERS["k"])
    T_val = int(SLIDERS["T"])

    traj_arr = np.zeros((T_val, k_val, 2))
    traj_rule = "traj[n] = traj[n-1] - lr * grad_E(sources, traj[n-1].T).T"
    traj_init = ["traj[0] = random.random((k, 2)) * 10 - 5"]

    results: dict[str, list[float]] = {}
    results["traj_recurrence"] = _timeit(
        lambda: execute_recurrence("traj", traj_arr.copy(), traj_init, traj_rule, base_rec_ns),
        n_frames,
    )
    return results


# ---------------------------------------------------------------------------
# Section 3 — Surface E(grid) isolation
# ---------------------------------------------------------------------------

def bench_surface_E(grid, n_frames: int) -> dict[str, list[float]]:
    """Isolate the cost of z = E(grid_pts) — logsumexp energy surface."""
    from pringle.evaluator import run_cell

    ns = _build_shared(grid)
    for cname, src, seed in [
        ("sources",  "sources = random.random((k, 2)) * 8 - 4", 0),
        ("D",        "D(M, v) = -(sum(M**2, axis=1)[:,None] + sum(v**2, axis=0)[None,:] - 2*(M@v))", 0),
        ("β_inv",    "β_inv = 1/β", 0),
        ("E",        "E(v) = -β_inv * logsumexp(β * D(sources, v), axis=0)", 0),
        ("grid_pts", "grid_pts = array([x, y]).reshape(2, -1)", 0),
        ("grid_shape","grid_shape = x.shape", 0),
    ]:
        ns["random"] = np.random.RandomState(seed)
        r = run_cell(src, ns, grid)
        ns.update(r.exports)

    results: dict[str, list[float]] = {}
    results["z_E_grid"] = _timeit(
        lambda: run_cell("z = E(grid_pts).reshape(*grid_shape)", dict(ns), grid),
        n_frames,
    )

    # Raw numpy: isolate just the energy computation
    k_val = int(SLIDERS["k"])
    sources_arr = np.random.RandomState(0).random((k_val, 2)) * 8 - 4
    β = SLIDERS["β"]
    β_inv = 1.0 / β
    g = ns["grid_pts"]
    from scipy.special import logsumexp as _lse
    def _raw_E():
        D = -(np.sum(sources_arr**2, axis=1)[:,None]
              + np.sum(g**2, axis=0)[None,:]
              - 2 * (sources_arr @ g))
        return -β_inv * _lse(β * D, axis=0)

    results["E_grid_raw_numpy"] = _timeit(_raw_E, n_frames)
    return results


# ---------------------------------------------------------------------------
# Section 4 — DAG rebuild overhead
# ---------------------------------------------------------------------------

def bench_dag_rebuild(n_frames: int) -> dict[str, list[float]]:
    """
    Time build_dag + topo_order + undefined_names for the bench-panel-rebuild
    cell set. These run on every _rebuild_namespace() call.
    """
    from pringle.dag import build_dag, topo_order, undefined_names

    class _MockCell:
        def __init__(self, cid, src):
            self.cell_id = cid
            self._src = src
            self._sub_cells = []
        def source(self):
            return self._src

    all_cells = []
    for i, (name, val) in enumerate(SLIDERS.items()):
        all_cells.append(_MockCell(f"slider_{i}", f"{name} = {val}"))
    for i, (cell_name, src, *_) in enumerate(CELLS):
        all_cells.append(_MockCell(f"eq_{i}", src))

    results: dict[str, list[float]] = {}
    results["build_dag"] = _timeit(lambda: build_dag(all_cells), n_frames)
    results["topo_order"] = _timeit(
        lambda: topo_order(build_dag(all_cells), all_cells), n_frames
    )
    results["undefined_names"] = _timeit(
        lambda: undefined_names(all_cells), n_frames
    )
    results["full_dag_pass"] = _timeit(
        lambda: (build_dag(all_cells),
                 topo_order(build_dag(all_cells), all_cells),
                 undefined_names(all_cells)),
        n_frames,
    )
    return results


# ---------------------------------------------------------------------------
# Memory audit
# ---------------------------------------------------------------------------

def _run_tracemalloc(grid, n_frames: int) -> None:
    from pringle.evaluator import run_cell
    from pringle.recurrence import parse_recurrence, execute_recurrence
    from pringle.namespace import build_equation_namespace

    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()

    for _ in range(n_frames):
        ns = _build_shared(grid)
        for cell_name, src, rng_seed, rec_rule, init_exprs in CELLS:
            ns["random"] = np.random.RandomState(rng_seed)
            result = run_cell(src, ns, grid)
            if rec_rule and not result.error:
                is_valid, arr_name, _ = parse_recurrence(rec_rule)
                if is_valid and arr_name in result.exports:
                    arr = result.exports[arr_name]
                    if isinstance(arr, np.ndarray):
                        rec_ns = {**build_equation_namespace(), **ns, **result.exports}
                        arr, _ = execute_recurrence(arr_name, arr, init_exprs or [], rec_rule, rec_ns)
                        result.exports[arr_name] = arr
            ns.update(result.exports)

    snap_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    print("\n── Memory allocation top-20 sites (delta across rebuild frames) ──")
    stats = snap_after.compare_to(snap_before, "lineno")
    for stat in stats[:20]:
        print(f"  {stat}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _print_report(n: int, frames: int,
                  per_cell: dict, rec: dict, surf: dict, dag: dict) -> None:
    print()
    print("═" * 72)
    print(f"  Pringle Cell-Rebuild Benchmark  (n={n}, frames={frames})")
    print(f"  Session: bench-panel-rebuild.yml  ({len(CELLS)} eq cells + {len(SLIDERS)} sliders)")
    print("═" * 72)
    print(f"  {'Section':<44} │  {'Mean ms':>8}  │  {'P95 ms':>7}")
    print("  " + "─" * 44 + "─┼─" + "─" * 10 + "─┼─" + "─" * 9)

    print()
    print("  [Full _rebuild_namespace equivalent]")
    print(_fmt_row("  TOTAL REBUILD (all cells, all recurrence)", per_cell.get("_TOTAL_REBUILD", [])))

    print()
    print("  [Per-cell breakdown — top contributors]")
    skip = {"_TOTAL_REBUILD"}
    cell_rows = [(name, times) for name, times in per_cell.items()
                 if name not in skip and times]
    cell_rows.sort(key=lambda x: _stats(x[1])[0], reverse=True)
    for name, times in cell_rows[:12]:
        print(_fmt_row(f"    run_cell({name})", times))

    print()
    print("  [Recurrence isolation — execute_recurrence only]")
    for key, times in rec.items():
        print(_fmt_row(f"  {key}", times))

    print()
    print("  [Surface E(grid) isolation]")
    for key, times in surf.items():
        print(_fmt_row(f"  {key}", times))

    print()
    print("  [DAG rebuild overhead (fires on every _rebuild_namespace)]")
    for key, times in dag.items():
        print(_fmt_row(f"  {key}", times))

    print()
    total_mean, total_p95 = _stats(per_cell.get("_TOTAL_REBUILD", []))
    dag_mean, _ = _stats(dag.get("full_dag_pass", []))

    print("  ── Estimated add/remove cell spike ──")
    print(f"    _rebuild_namespace:  {total_mean:>8.1f} ms  (full re-eval, before PERF-016 fix)")
    print(f"    DAG pass overhead:   {dag_mean:>8.1f} ms  (build_dag + topo + undef)")
    traj_mean, _ = _stats(per_cell.get("traj", []))
    traj3d_mean, _ = _stats(per_cell.get("traj_3d", []))
    z_mean, _ = _stats(per_cell.get("z", []))
    other = total_mean - traj_mean - traj3d_mean - z_mean
    print(f"")
    print(f"    Breakdown:")
    print(f"      traj (recurrence):  {traj_mean:>8.1f} ms")
    print(f"      traj_3d (E@40k):    {traj3d_mean:>8.1f} ms")
    print(f"      z = E(grid):        {z_mean:>8.1f} ms")
    print(f"      all other cells:    {other:>8.1f} ms")
    print(f"")
    skippable = traj_mean + traj3d_mean
    after_fix = total_mean - skippable
    print(f"    After PERF-016 fix (skip traj + traj_3d when upstream unchanged):")
    print(f"      Expected rebuild:   {after_fix:>8.1f} ms  ({total_mean/max(after_fix,0.1):.0f}x speedup)")
    print()
    print("═" * 72)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cell-rebuild benchmark for bench-panel-rebuild.yml (PERF-016)"
    )
    parser.add_argument("--n",      type=int, default=128,
                        help="Grid resolution (default 128)")
    parser.add_argument("--frames", type=int, default=5,
                        help="Timed frames (default 5; each is an ~1-2s rebuild)")
    parser.add_argument("--mem",    action="store_true",
                        help="Run tracemalloc memory audit")
    parser.add_argument("--no-gc",  action="store_true",
                        help="Disable GC during timing")
    args = parser.parse_args()

    from pringle.grid import GridConfig, make_grid
    grid = make_grid(GridConfig(
        x_min=-5, x_max=5, y_min=-5, y_max=5,
        z_min=-1.5, z_max=0.5, n=args.n,
    ))

    if args.no_gc:
        gc.disable()
        print("[bench] GC disabled")

    print(f"[bench] n={args.n}  frames={args.frames}")
    print(f"[bench] grid shape: {grid.x.shape}  ({grid.x.size:,} vertices)")
    print(f"[bench] cells: {len(CELLS)} equations + {len(SLIDERS)} sliders")
    print()

    print("[bench] 1/4: Per-cell timing (full rebuild) ...")
    per_cell = bench_per_cell(grid, args.frames)

    print("[bench] 2/4: Recurrence isolation ...")
    rec = bench_recurrence_cells(grid, args.frames)

    print("[bench] 3/4: Surface E(grid) isolation ...")
    surf = bench_surface_E(grid, args.frames)

    print("[bench] 4/4: DAG rebuild overhead ...")
    dag = bench_dag_rebuild(args.frames)

    if args.no_gc:
        gc.enable()

    _print_report(args.n, args.frames, per_cell, rec, surf, dag)

    if args.mem:
        print("[bench] Running memory audit ...")
        _run_tracemalloc(grid, min(args.frames, 3))


if __name__ == "__main__":
    main()
