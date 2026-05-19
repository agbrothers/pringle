"""
tests/bench_slider_animation.py

Headless benchmark for the β-slider animation pipeline from memory.yml.

Measures wall-clock time for each CPU layer of the per-frame update
independently — no Qt or display required.  Simulates the downstream
evaluation chain that fires every 16 ms when the β slider animates:

  DAG/AST overhead → cell evaluation → geometry (index gen + normals + clipping)

Performance target: ≥ 30 fps at n=128  →  ≤ 33 ms total per frame.

Usage:
    python tests/bench_slider_animation.py
    python tests/bench_slider_animation.py --n 128 --frames 100
    python tests/bench_slider_animation.py --n 128 --frames 100 --mem
    python -m cProfile -s cumulative tests/bench_slider_animation.py | head -60
    kernprof -l -v tests/bench_slider_animation.py   # requires line_profiler

See design-docs/20-profiling-sop.md for interpretation guidance.
"""

from __future__ import annotations

import argparse
import gc
import statistics
import time
import tracemalloc
from typing import Callable

import numpy as np


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def _timeit(fn: Callable, n: int, warmup: int = 5) -> list[float]:
    """Run fn() n+warmup times; return the n timed durations in ms."""
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    return times


def _stats(times: list[float]) -> tuple[float, float, float]:
    """Return (mean, p95, stdev) in ms."""
    return (
        statistics.mean(times),
        sorted(times)[int(len(times) * 0.95)],
        statistics.stdev(times) if len(times) > 1 else 0.0,
    )


# ---------------------------------------------------------------------------
# Section 1 — AST pipeline overhead
#
# Measures the repeated AST work done for each cell on each slider tick:
#   preprocess → get_free_names → get_store_names → check_ast
# These four operations run once per downstream cell per frame.
# ---------------------------------------------------------------------------

def bench_ast_pipeline(n_frames: int) -> dict[str, list[float]]:
    """
    Time each AST operation on the downstream cells from the β chain.

    Returns a dict mapping operation name to per-frame total time across
    all cells (i.e., what the app pays per tick, not per cell).
    """
    from pringle.preprocess import preprocess
    from pringle.safety import check_ast, get_free_names, get_store_names

    # Sources of cells downstream of β in memory.yml
    downstream_sources = [
        "β_inv = 1/β",
        "E(v) = -β_inv * Q( sum( [F ( β*(  S(m[:, None], v)  ) ) for m in M], axis=0))",
        "E_batch(v) = -β_inv * Q( sum( F( β*(  InvDistSqBatch(M, v)  ) ), axis=0))",
        "z = E_batch(grid).reshape(*shape)",
        "M_z = E_batch(M.T)",
        "M_e = concatenate((M, M_z[:,None]), axis=1)",
    ]
    # Preprocess sources once — this is done once per cell per tick in the app too
    preprocessed = [preprocess(s)[0] for s in downstream_sources]

    results: dict[str, list[float]] = {
        "preprocess": [],
        "get_free_names": [],
        "get_store_names": [],
        "check_ast": [],
        "total_ast": [],
    }

    def _one_frame_preprocess():
        for s in downstream_sources:
            preprocess(s)

    def _one_frame_free_names():
        for p in preprocessed:
            get_free_names(p)

    def _one_frame_store_names():
        for p in preprocessed:
            get_store_names(p)

    def _one_frame_check_ast():
        for p in preprocessed:
            check_ast(p)

    def _one_frame_total():
        for s in downstream_sources:
            p, _ = preprocess(s)
            get_free_names(p)
            get_store_names(p)
            check_ast(p)

    results["preprocess"]     = _timeit(_one_frame_preprocess,  n_frames)
    results["get_free_names"] = _timeit(_one_frame_free_names,  n_frames)
    results["get_store_names"]= _timeit(_one_frame_store_names, n_frames)
    results["check_ast"]      = _timeit(_one_frame_check_ast,   n_frames)
    results["total_ast"]      = _timeit(_one_frame_total,       n_frames)
    return results


# ---------------------------------------------------------------------------
# Section 2 — Cell evaluation chain
#
# Measures run_cell() for each cell downstream of β in memory.yml.
# This is the actual numpy computation (E_batch on the full grid).
# ---------------------------------------------------------------------------

def bench_cell_eval(grid, n_frames: int) -> dict[str, list[float]]:
    """
    Time run_cell for each downstream cell in the β-slider chain.

    The shared namespace is pre-seeded with all independent cells so that
    only the β-dependent computation is measured.
    """
    from pringle.evaluator import run_cell
    from pringle.namespace import build_equation_namespace

    # Build a shared namespace with independent cells already evaluated
    base_ns = build_equation_namespace()
    base_ns.update({
        "β": 0.4,
        "M": np.random.default_rng(42).random((10, 2), dtype=float) * 6 - 3,
    })

    # Evaluate independent cells once to populate the namespace
    independent_sources = [
        "F(v) = exp(v)",
        "Q(v) = log(v)",
        "InvDistSq(m, v) = -sum((m-v)**2, axis=0)",
        "InvDistSqBatch(m, v) = -sum((m[..., None]-v[None, ...])**2, axis=1)",
        "grid = array([x, y]).reshape(2, -1)",
        "shape = x.shape",
    ]
    shared_ns = dict(base_ns)
    for src in independent_sources:
        result = run_cell(src, shared_ns, grid)
        shared_ns.update(result.exports)

    # Downstream chain — evaluated in order each frame
    downstream = [
        ("β_inv",    "β_inv = 1/β"),
        ("E",        "E(v) = -β_inv * Q( sum( [F ( β*(  S(m[:, None], v)  ) ) for m in M], axis=0))"),
        ("E_batch",  "E_batch(v) = -β_inv * Q( sum( F( β*(  InvDistSqBatch(M, v)  ) ), axis=0))"),
        ("z_surface","z = E_batch(grid).reshape(*shape)"),
        ("M_z",      "M_z = E_batch(M.T)"),
        ("M_e",      "M_e = concatenate((M, M_z[:,None]), axis=1)"),
    ]

    results: dict[str, list[float]] = {}
    chain_times: list[float] = []

    beta_values = np.linspace(0.05, 0.95, n_frames)

    for _ in range(5):  # warmup
        for name, src in downstream:
            run_cell(src, dict(shared_ns), grid)

    for frame_idx in range(n_frames):
        beta = float(beta_values[frame_idx % len(beta_values)])
        frame_ns = dict(shared_ns)
        frame_ns["β"] = beta
        frame_ns["β_inv"] = 1.0 / beta
        t_frame = 0.0
        for name, src in downstream:
            t0 = time.perf_counter()
            result = run_cell(src, frame_ns, grid)
            elapsed = (time.perf_counter() - t0) * 1000.0
            frame_ns.update(result.exports)
            results.setdefault(name, []).append(elapsed)
            t_frame += elapsed
        chain_times.append(t_frame)

    results["chain_total"] = chain_times
    return results


# ---------------------------------------------------------------------------
# Section 3 — Geometry CPU layer
#
# Measures the pure-Python and numpy geometry construction functions.
# These are called inside make_surface_mesh on every frame update.
# ---------------------------------------------------------------------------

def bench_geometry_cpu(grid, n_frames: int) -> dict[str, list[float]]:
    """
    Time the CPU geometry construction functions independently.

    _grid_indices: builds triangle index buffer (pure Python loops — PERF-003)
    _grid_normals: computes per-vertex normals (numpy)
    _clip_mesh_to_mask: constraint triangle clipping (pure Python — PERF-004)
    """
    from pringle.renderer import _grid_indices, _grid_normals, _clip_mesh_to_mask

    rows, cols = grid.x.shape
    # Build a representative z surface and constraint mask
    z_surface = np.sin(grid.x) * np.cos(grid.y)
    inside_mask = (z_surface < 0.5).ravel()

    # Pre-build geometry needed as input to _clip_mesh_to_mask
    positions = np.stack([grid.x.ravel(), grid.y.ravel(), z_surface.ravel()], axis=1).astype(np.float32)
    indices   = _grid_indices(rows, cols)
    normals   = _grid_normals(grid.x, grid.y, z_surface)

    results: dict[str, list[float]] = {}
    results["_grid_indices"]     = _timeit(lambda: _grid_indices(rows, cols), n_frames)
    results["_grid_normals"]     = _timeit(lambda: _grid_normals(grid.x, grid.y, z_surface), n_frames)
    results["_clip_mesh_to_mask"]= _timeit(
        lambda: _clip_mesh_to_mask(positions, indices, normals, inside_mask), n_frames
    )

    # Combined cost: what make_surface_mesh pays before pygfx object creation
    def _full_cpu():
        idx = _grid_indices(rows, cols)
        nor = _grid_normals(grid.x, grid.y, z_surface)
        _clip_mesh_to_mask(positions, idx, nor, inside_mask)

    results["cpu_total"] = _timeit(_full_cpu, n_frames)
    return results


# ---------------------------------------------------------------------------
# Section 4 — Full make_surface_mesh
#
# Measures the complete make_surface_mesh call including pygfx object
# construction (but NOT GPU upload, which happens on the first render).
# ---------------------------------------------------------------------------

def bench_make_surface_mesh(grid, n_frames: int) -> dict[str, list[float]]:
    """
    Time the full make_surface_mesh pipeline.

    Includes all CPU geometry work from Section 3 plus gfx.Geometry /
    gfx.Mesh object construction.  GPU upload is NOT measured here — it
    happens lazily on the first render call.
    """
    from pringle.renderer import make_surface_mesh

    z_surface = np.sin(grid.x) * np.cos(grid.y)
    inside_mask = (z_surface < 0.5)
    z_raw = z_surface.copy()
    z_masked = np.where(inside_mask, z_surface, np.nan)

    def _make():
        make_surface_mesh(
            grid.x, grid.y, z_masked,
            color=(0.85, 0.55, 0.05, 1.0),
            constraint_mask=inside_mask,
            z_raw=z_raw,
            colormap="inferno",
        )

    try:
        times = _timeit(_make, n_frames)
    except Exception as exc:
        print(f"  [!] make_surface_mesh benchmark skipped: {exc}")
        times = []

    return {"make_surface_mesh": times}


# ---------------------------------------------------------------------------
# Section 5 — Namespace construction overhead
#
# Measures build_equation_namespace() which is called 2× per run_cell (PERF-005).
# ---------------------------------------------------------------------------

def bench_namespace(n_frames: int) -> dict[str, list[float]]:
    """Time build_equation_namespace() — called twice per run_cell (PERF-005)."""
    from pringle.namespace import build_equation_namespace

    single = _timeit(build_equation_namespace, n_frames)
    double = _timeit(lambda: (build_equation_namespace(), build_equation_namespace()), n_frames)
    return {
        "build_namespace_1x": single,
        "build_namespace_2x": double,
    }


# ---------------------------------------------------------------------------
# Memory snapshot helper
# ---------------------------------------------------------------------------

def _run_with_tracemalloc(grid, n_frames: int) -> None:
    """
    Run the full evaluation + geometry pipeline with tracemalloc active
    and print the top allocation sites.
    """
    from pringle.evaluator import run_cell
    from pringle.namespace import build_equation_namespace
    from pringle.renderer import make_surface_mesh

    shared_ns = build_equation_namespace()
    shared_ns["β"] = 0.4
    shared_ns["M"] = np.random.default_rng(42).random((10, 2)) * 6 - 3

    independent = [
        "F(v) = exp(v)", "Q(v) = log(v)",
        "InvDistSqBatch(m, v) = -sum((m[..., None]-v[None, ...])**2, axis=1)",
        "grid = array([x, y]).reshape(2, -1)", "shape = x.shape",
    ]
    for src in independent:
        r = run_cell(src, shared_ns, grid)
        shared_ns.update(r.exports)

    downstream = [
        "β_inv = 1/β",
        "E_batch(v) = -β_inv * Q( sum( F( β*(  InvDistSqBatch(M, v)  ) ), axis=0))",
        "z = E_batch(grid).reshape(*shape)",
    ]

    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()

    for frame_idx in range(n_frames):
        beta = 0.1 + (frame_idx % 10) * 0.09
        ns = dict(shared_ns)
        ns["β"] = beta
        ns["β_inv"] = 1.0 / beta
        for src in downstream:
            r = run_cell(src, ns, grid)
            ns.update(r.exports)
        z_data = ns.get("z")
        if z_data is not None and isinstance(z_data, np.ndarray) and z_data.ndim == 2:
            z_masked = np.where(z_data < 3, z_data, np.nan)
            inside = (z_data < 3)
            try:
                make_surface_mesh(grid.x, grid.y, z_masked, constraint_mask=inside, z_raw=z_data)
            except Exception:
                pass

    snap_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    print("\n── Memory allocation top-20 sites (delta across benchmark) ──")
    stats = snap_after.compare_to(snap_before, "lineno")
    for stat in stats[:20]:
        print(f"  {stat}")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

_BUDGET_MS = 33.0  # 30 fps target


def _fmt_row(label: str, times: list[float], budget: float = _BUDGET_MS) -> str:
    if not times:
        return f"  {label:<36} │  {'n/a':>8}  │  {'n/a':>7}  │  {'n/a':>6}"
    mean, p95, _ = _stats(times)
    pct = mean / budget * 100
    return f"  {label:<36} │  {mean:>8.2f}  │  {p95:>7.2f}  │  {pct:>5.1f}%"


def _print_report(
    n: int,
    frames: int,
    ast_res: dict,
    eval_res: dict,
    geo_res: dict,
    mesh_res: dict,
    ns_res: dict,
) -> bool:
    """Print formatted benchmark report. Returns True if within budget."""
    budget = _BUDGET_MS
    print()
    print("═" * 66)
    print(f"  Pringle Slider Animation Benchmark  (n={n}, frames={frames})")
    print("═" * 66)
    print(f"  {'Section':<36} │  {'Mean ms':>8}  │  {'P95 ms':>7}  │  {'% budget':>8}")
    print("  " + "─" * 36 + "─┼─" + "─" * 10 + "─┼─" + "─" * 9 + "─┼─" + "─" * 9)

    print("  [AST pipeline — per tick across all downstream cells]")
    for key in ("total_ast", "preprocess", "get_free_names", "get_store_names", "check_ast"):
        label = f"  {key}" if key != "total_ast" else key
        print(_fmt_row(f"  ast/{label}", ast_res.get(key, [])))

    print()
    print("  [Cell evaluation chain — memory.yml β downstream]")
    for key in ("chain_total", "β_inv", "E", "E_batch", "z_surface", "M_z", "M_e"):
        label = f"  {key}" if key != "chain_total" else key
        print(_fmt_row(f"  eval/{label}", eval_res.get(key, [])))

    print()
    print("  [Geometry CPU — renderer hot functions]")
    for key in ("cpu_total", "_grid_indices", "_grid_normals", "_clip_mesh_to_mask"):
        label = f"  {key}" if key != "cpu_total" else key
        print(_fmt_row(f"  geo/{label}", geo_res.get(key, [])))

    print()
    print("  [Full make_surface_mesh (includes geo above)]")
    for key, times in mesh_res.items():
        print(_fmt_row(f"  mesh/{key}", times))

    print()
    print("  [Namespace construction overhead (PERF-005)]")
    for key, times in ns_res.items():
        print(_fmt_row(f"  ns/{key}", times))

    # Estimated total frame: eval chain + geo CPU (dominant bottlenecks)
    eval_chain = eval_res.get("chain_total", [])
    geo_cpu = geo_res.get("cpu_total", [])
    mesh_times = mesh_res.get("make_surface_mesh", [])
    if mesh_times:
        # make_surface_mesh includes geo_cpu, so use it as the geometry cost
        combined = [e + m for e, m in zip(eval_chain, mesh_times)] if eval_chain and mesh_times else []
    elif eval_chain and geo_cpu:
        combined = [e + g for e, g in zip(eval_chain, geo_cpu)]
    else:
        combined = eval_chain or geo_cpu

    print()
    print("  " + "─" * 36 + "─┼─" + "─" * 10 + "─┼─" + "─" * 9 + "─┼─" + "─" * 9)
    print(_fmt_row("  ESTIMATED TOTAL FRAME", combined))
    print(f"  {'TARGET  (33 ms = 30 fps)':<36} │  {budget:>8.1f}  │  {'':>7}  │")
    print()

    if combined:
        mean_total, p95_total, _ = _stats(combined)
        if mean_total <= budget:
            print(f"  Result: PASS ✓  (mean {mean_total:.1f} ms ≤ {budget:.0f} ms budget)")
            passed = True
        else:
            over = mean_total - budget
            print(f"  Result: FAIL ✗  (mean {mean_total:.1f} ms, {over:.1f} ms over budget)")
            passed = False
        if p95_total > budget:
            print(f"  Warning: P95 {p95_total:.1f} ms exceeds budget — frame drops will be visible")
    else:
        print("  Result: INCOMPLETE — not enough data to estimate total")
        passed = False

    print("═" * 66)
    print()
    return passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Headless benchmark for Pringle slider animation pipeline"
    )
    parser.add_argument("--n",      type=int, default=128, help="Grid resolution (default 128)")
    parser.add_argument("--frames", type=int, default=60,  help="Timed frames per section (default 60)")
    parser.add_argument("--warmup", type=int, default=5,   help="Warmup frames per section (default 5)")
    parser.add_argument("--mem",    action="store_true",   help="Run tracemalloc memory audit after timing")
    parser.add_argument("--no-gc",  action="store_true",   help="Disable Python GC during timing (isolates GC spikes)")
    args = parser.parse_args()

    from pringle.grid import GridConfig, make_grid
    grid = make_grid(GridConfig(
        x_min=-10, x_max=10, y_min=-10, y_max=10,
        z_min=-10, z_max=10, n=args.n,
    ))

    if args.no_gc:
        gc.disable()
        print(f"[bench] GC disabled for timing isolation")

    print(f"[bench] n={args.n}  frames={args.frames}  warmup={args.warmup}")
    print(f"[bench] grid shape: {grid.x.shape}  ({grid.x.size:,} vertices)")
    print()

    print("[bench] Section 1/5: AST pipeline overhead ...")
    ast_res = bench_ast_pipeline(args.frames)

    print("[bench] Section 2/5: Cell evaluation chain ...")
    eval_res = bench_cell_eval(grid, args.frames)

    print("[bench] Section 3/5: Geometry CPU functions ...")
    geo_res = bench_geometry_cpu(grid, args.frames)

    print("[bench] Section 4/5: Full make_surface_mesh ...")
    mesh_res = bench_make_surface_mesh(grid, args.frames)

    print("[bench] Section 5/5: Namespace construction ...")
    ns_res = bench_namespace(args.frames)

    if args.no_gc:
        gc.enable()

    _print_report(args.n, args.frames, ast_res, eval_res, geo_res, mesh_res, ns_res)

    if args.mem:
        print("[bench] Running memory audit ...")
        _run_with_tracemalloc(grid, min(args.frames, 50))


if __name__ == "__main__":
    main()
