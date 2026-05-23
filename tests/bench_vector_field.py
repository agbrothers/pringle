"""
tests/bench_vector_field.py

Headless benchmark for the vector-field-animation.yml config.

Measures the per-frame cost when the T slider animates:
  anim = frames[T]  → (N, 6) array index (near-free)
  make_arrow_mesh(anim, ...)  → InstancedMesh construction (primary bottleneck)

Also profiles a vectorized batch matrix construction as a proof-of-concept
to establish the maximum achievable speedup for PERF-017.

Performance target: ≤ 33 ms total per animation frame (30 fps).

Usage:
    python tests/bench_vector_field.py
    python tests/bench_vector_field.py --n-arrows 4096 --frames 60
    python tests/bench_vector_field.py --n-arrows 4096 --frames 60 --mem
    python -m cProfile -s cumulative tests/bench_vector_field.py | head -60
"""

from __future__ import annotations

import argparse
import gc
import statistics
import time
import tracemalloc

import numpy as np


# ---------------------------------------------------------------------------
# Timing helpers (same as bench_slider_animation.py)
# ---------------------------------------------------------------------------

def _timeit(fn, n: int, warmup: int = 5) -> list[float]:
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    return times


def _stats(times: list[float]) -> tuple[float, float, float]:
    return (
        statistics.mean(times),
        sorted(times)[int(len(times) * 0.95)],
        statistics.stdev(times) if len(times) > 1 else 0.0,
    )


# ---------------------------------------------------------------------------
# Vectorized batch matrix construction (proof-of-concept for PERF-017)
#
# Replaces the O(N) Python loop in make_arrow_mesh with a single numpy
# operation over the full (N, 3) tail/head arrays.
#
# Rodrigues rotation formula applied in batch:
#   d = head - tail              (N, 3)
#   L = ||d||                    (N,)
#   d_hat = d / L               (N, 3)
#   axis = cross(z, d_hat)      (N, 3)  where z = [0, 0, 1]
#   s = ||axis||                 (N,)
#   c = d_hat[:, 2]             (N,)   = dot(z, d_hat)
#   K = skew(axis_n)            (N, 3, 3)
#   R = I + s*K + (1-c)*K@K    (N, 3, 3)
# ---------------------------------------------------------------------------

def _arrow_matrices_batch(
    tails: np.ndarray,   # (N, 3)
    heads: np.ndarray,   # (N, 3)
    size: float = 0.1,
) -> np.ndarray:
    """Return (N, 4, 4) float32 instance transform matrices — fully vectorized."""
    N = len(tails)
    d = heads - tails                                             # (N, 3)
    L = np.linalg.norm(d, axis=1)                               # (N,)
    valid = L > 1e-10
    L_safe = np.where(valid, L, 1.0)
    d_hat = d / L_safe[:, None]                                  # (N, 3)

    # cross(z=[0,0,1], d_hat) = [d_hat[:,1]*1 - d_hat[:,2]*0,  ← component 0
    #                             d_hat[:,2]*0 - d_hat[:,0]*1,  ← component 1
    #                             d_hat[:,0]*0 - d_hat[:,1]*0]  ← component 2
    # = [-d_hat[:,1]... wait:
    # z x d = |i  j  k |
    #         |0  0  1 |
    #         |dx dy dz|
    # = i*(0*dz - 1*dy) - j*(0*dz - 1*dx) + k*(0*dy - 0*dx)
    # = (-dy, dx, 0)
    axis = np.stack([-d_hat[:, 1], d_hat[:, 0], np.zeros(N)], axis=1)  # (N, 3)

    s = np.linalg.norm(axis, axis=1)                             # (N,) sin(angle)
    c = d_hat[:, 2]                                              # (N,) cos(angle) = dot(z, d_hat)
    s_safe = np.where(s > 1e-8, s, 1.0)
    axis_n = axis / s_safe[:, None]                              # (N, 3) normalized

    # Skew-symmetric K per arrow: K[i] = [[0, -az, ay], [az, 0, -ax], [-ay, ax, 0]]
    ax, ay, az = axis_n[:, 0], axis_n[:, 1], axis_n[:, 2]
    zero = np.zeros(N)
    K = np.stack([
        np.stack([ zero, -az,   ay], axis=1),
        np.stack([ az,   zero, -ax], axis=1),
        np.stack([-ay,   ax,   zero], axis=1),
    ], axis=1)                                                   # (N, 3, 3)

    # Rodrigues: R = I + sin(θ)*K + (1-cos(θ))*K²
    I3 = np.eye(3, dtype=np.float64)[None]                      # (1, 3, 3)
    KK = K @ K                                                   # (N, 3, 3)
    R = I3 + s[:, None, None] * K + (1 - c)[:, None, None] * KK  # (N, 3, 3)

    # Handle parallel (s≈0) and anti-parallel (c≈-1) cases
    parallel = s < 1e-8
    antipar = parallel & (c < 0)
    R[parallel & ~antipar] = np.eye(3)
    flip = np.eye(3); flip[1, 1] = -1.0; flip[2, 2] = -1.0
    R[antipar] = flip

    # Assemble 4×4 matrices
    Ms = np.zeros((N, 4, 4), dtype=np.float32)
    Ms[:, :3, 0] = (R[:, :, 0] * size).astype(np.float32)       # X: radial
    Ms[:, :3, 1] = (R[:, :, 1] * size).astype(np.float32)       # Y: radial
    Ms[:, :3, 2] = (R[:, :, 2] * L_safe[:, None]).astype(np.float32)  # Z: scaled by length
    Ms[:, :3, 3] = tails.astype(np.float32)                     # translation
    Ms[:, 3, 3] = 1.0

    # Zero out invalid (degenerate) arrows
    Ms[~valid] = 0.0
    return Ms


# ---------------------------------------------------------------------------
# Section 1 — _arrow_matrix single-call cost
#
# Each call works on tiny (3,) arrays; Python overhead dominates.
# This establishes the per-arrow baseline to extrapolate the loop cost.
# ---------------------------------------------------------------------------

def bench_arrow_matrix_single(n_frames: int) -> dict[str, list[float]]:
    """Time a single _arrow_matrix call (one arrow)."""
    from pringle.renderer import _arrow_matrix

    rng = np.random.default_rng(0)
    tail = rng.uniform(-5, 5, size=3).astype(np.float32)
    head = rng.uniform(-5, 5, size=3).astype(np.float32)

    return {"_arrow_matrix_1x": _timeit(lambda: _arrow_matrix(tail, head, size=0.1), n_frames)}


# ---------------------------------------------------------------------------
# Section 2 — make_arrow_mesh full pipeline timing
#
# The main suspect: builds an InstancedMesh from (N, 6) arrows.
# Broken into:
#   a) Loop-only cost (just the matrix construction, no pygfx object)
#   b) Full make_arrow_mesh (includes gfx.InstancedMesh creation)
# ---------------------------------------------------------------------------

def bench_make_arrow_mesh(n_arrows: int, n_frames: int) -> dict[str, list[float]]:
    """Time make_arrow_mesh and sub-components for N arrows."""
    from pringle.renderer import _arrow_matrix, make_arrow_mesh

    rng = np.random.default_rng(1)
    arrows = rng.uniform(-5, 5, size=(n_arrows, 6)).astype(np.float32)
    tails = arrows[:, :3]
    heads = arrows[:, 3:]

    # Sub-section a: Python loop + _arrow_matrix only (no pygfx Geometry/Mesh)
    import pygfx as gfx
    from pringle.renderer import _ARROW_GEO, _build_unit_arrow_geometry
    _geo = _build_unit_arrow_geometry()
    mat_obj = gfx.MeshPhongMaterial(color=(0.9, 0.6, 0.1, 1.0))

    def _loop_only():
        mesh = gfx.InstancedMesh(_geo, mat_obj, n_arrows)
        for i, (t, h) in enumerate(zip(tails, heads)):
            M = _arrow_matrix(t, h, size=0.1)
            if M is not None:
                mesh.set_matrix_at(i, M)

    def _full_make():
        make_arrow_mesh(arrows, color=(0.9, 0.6, 0.1, 1.0), opacity=1.0, size=0.1)

    results: dict[str, list[float]] = {}
    results["make_arrow_loop_only"]     = _timeit(_loop_only, n_frames)
    results["make_arrow_mesh_full"]     = _timeit(_full_make, n_frames)
    return results


# ---------------------------------------------------------------------------
# Section 3 — Vectorized batch matrix construction (proof-of-concept)
#
# Computes all N arrow transform matrices in a single numpy operation.
# Establishes the potential speedup for PERF-017.
# ---------------------------------------------------------------------------

def bench_vectorized_matrices(n_arrows: int, n_frames: int) -> dict[str, list[float]]:
    """Compare vectorized batch vs. Python loop for N×(4×4) matrix construction."""
    from pringle.renderer import _arrow_matrix

    rng = np.random.default_rng(2)
    arrows = rng.uniform(-5, 5, size=(n_arrows, 6)).astype(np.float32)
    tails = arrows[:, :3]
    heads = arrows[:, 3:]

    def _python_loop():
        result = np.zeros((n_arrows, 4, 4), dtype=np.float32)
        for i, (t, h) in enumerate(zip(tails, heads)):
            M = _arrow_matrix(t, h, size=0.1)
            if M is not None:
                result[i] = M
        return result

    def _batch():
        return _arrow_matrices_batch(tails, heads, size=0.1)

    results: dict[str, list[float]] = {}
    results["matrix_loop_N_arrows"]    = _timeit(_python_loop, n_frames)
    results["matrix_batch_vectorized"] = _timeit(_batch, n_frames)
    return results


# ---------------------------------------------------------------------------
# Section 4 — In-place instance buffer update (proof-of-concept)
#
# After computing matrices via batch, writes them to the existing
# InstancedMesh.instance_buffer directly — avoids rebuilding the pygfx
# object entirely. Analogous to PERF-002 for surfaces.
# ---------------------------------------------------------------------------

def bench_inplace_update(n_arrows: int, n_frames: int) -> dict[str, list[float]]:
    """Compare full make_arrow_mesh rebuild vs. in-place instance buffer update."""
    from pringle.renderer import make_arrow_mesh, _build_unit_arrow_geometry
    import pygfx as gfx

    rng = np.random.default_rng(3)

    def _new_arrows():
        return rng.uniform(-5, 5, size=(n_arrows, 6)).astype(np.float32)

    # Pre-build the mesh once
    arrows0 = _new_arrows()
    mesh = make_arrow_mesh(arrows0, color=(0.9, 0.6, 0.1, 1.0), opacity=1.0, size=0.1)
    ib = mesh.instance_buffer  # Buffer with structured dtype: ('matrix', float32, (4,4)), ...

    def _full_rebuild():
        a = _new_arrows()
        make_arrow_mesh(a, color=(0.9, 0.6, 0.1, 1.0), opacity=1.0, size=0.1)

    def _inplace_update():
        a = _new_arrows()
        Ms = _arrow_matrices_batch(a[:, :3], a[:, 3:], size=0.1)
        ib.data["matrix"][:] = Ms.transpose(0, 2, 1)  # pygfx stores column-major
        ib.update_full()

    results: dict[str, list[float]] = {}
    results["full_rebuild_make_arrow"]  = _timeit(_full_rebuild, n_frames)
    results["inplace_buffer_update"]    = _timeit(_inplace_update, n_frames)
    return results


# ---------------------------------------------------------------------------
# Section 5 — Cell evaluation chain when T animates
#
# anim = frames[T] is a numpy array index — should be near-free.
# Confirms that the evaluation layer is NOT the bottleneck for T animation.
# ---------------------------------------------------------------------------

def bench_t_eval_chain(n_arrows: int, n_frames: int) -> dict[str, list[float]]:
    """
    Simulate the evaluation chain for anim = frames[T] and the
    downstream make_arrow_mesh call — isolates the two costs.
    """
    from pringle.evaluator import run_cell
    from pringle.namespace import build_equation_namespace
    from pringle.grid import GridConfig, make_grid
    from pringle.renderer import make_arrow_mesh

    # Simulate the frames array as built in vector-field-animation.yml
    n_grid = 64
    k = 10
    grid_cfg = GridConfig(x_min=-5, x_max=5, y_min=-5, y_max=5,
                          z_min=-5, z_max=5, n=n_grid)
    grid = make_grid(grid_cfg)
    nn = n_grid * n_grid  # 4096

    rng = np.random.default_rng(4)
    # Shape: (k-1, nn, 6) — pre-built frames tensor
    frames = rng.uniform(-5, 5, size=(k - 1, nn, 6)).astype(np.float32)

    T_values = list(range(k - 1))  # 0..8

    # a) Cost of numpy index anim = frames[T]
    def _eval_anim():
        T = T_values[_eval_anim._frame % (k - 1)]
        _eval_anim._frame += 1
        return frames[T]
    _eval_anim._frame = 0

    # b) Cost of make_arrow_mesh called with the resulting (nn, 6) slice
    def _eval_plus_mesh():
        T = T_values[_eval_plus_mesh._frame % (k - 1)]
        _eval_plus_mesh._frame += 1
        anim = frames[T]
        make_arrow_mesh(anim, color=(0.9, 0.6, 0.1, 1.0), opacity=1.0, size=0.03)
    _eval_plus_mesh._frame = 0

    results: dict[str, list[float]] = {}
    results["anim_index_only"]        = _timeit(_eval_anim, n_frames)
    results["anim_index_plus_mesh"]   = _timeit(_eval_plus_mesh, n_frames)
    return results


# ---------------------------------------------------------------------------
# Section 6 — Memory allocation audit
# ---------------------------------------------------------------------------

def _run_tracemalloc(n_arrows: int, n_frames: int) -> None:
    from pringle.renderer import make_arrow_mesh
    import numpy as np

    rng = np.random.default_rng(5)
    arrows = rng.uniform(-5, 5, size=(n_arrows, 6)).astype(np.float32)

    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()

    for _ in range(n_frames):
        make_arrow_mesh(arrows, color=(0.9, 0.6, 0.1, 1.0), opacity=1.0, size=0.03)

    snap_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    print("\n── Memory allocation top-20 sites (delta across benchmark) ──")
    stats = snap_after.compare_to(snap_before, "lineno")
    for stat in stats[:20]:
        print(f"  {stat}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

_BUDGET_MS = 33.0


def _fmt_row(label: str, times: list[float], budget: float = _BUDGET_MS) -> str:
    if not times:
        return f"  {label:<44} │  {'n/a':>8}  │  {'n/a':>7}  │  {'n/a':>6}"
    mean, p95, _ = _stats(times)
    pct = mean / budget * 100
    return f"  {label:<44} │  {mean:>8.2f}  │  {p95:>7.2f}  │  {pct:>5.1f}%"


def _print_report(
    n_arrows: int,
    n_frames: int,
    s1: dict,
    s2: dict,
    s3: dict,
    s4: dict,
    s5: dict,
) -> None:
    print()
    print("═" * 74)
    print(f"  Pringle Vector Field Benchmark  (N={n_arrows} arrows, frames={n_frames})")
    print("═" * 74)
    print(f"  {'Section':<44} │  {'Mean ms':>8}  │  {'P95 ms':>7}  │  {'% budget':>8}")
    print("  " + "─" * 44 + "─┼─" + "─" * 10 + "─┼─" + "─" * 9 + "─┼─" + "─" * 9)

    print("  [1. Per-arrow _arrow_matrix cost (single call)]")
    for k, v in s1.items():
        print(_fmt_row(f"  {k}", v))
    single_mean = statistics.mean(s1.get("_arrow_matrix_1x", [0.0]))
    print(f"       → extrapolated Python loop for N={n_arrows}: ~{single_mean * n_arrows:.1f} ms")

    print()
    print("  [2. make_arrow_mesh full pipeline]")
    for k, v in s2.items():
        print(_fmt_row(f"  {k}", v))

    print()
    print("  [3. Vectorized matrix construction vs. Python loop]")
    loop_times = s3.get("matrix_loop_N_arrows", [])
    batch_times = s3.get("matrix_batch_vectorized", [])
    for k, v in s3.items():
        print(_fmt_row(f"  {k}", v))
    if loop_times and batch_times:
        speedup = statistics.mean(loop_times) / max(statistics.mean(batch_times), 1e-6)
        print(f"       → vectorization speedup: {speedup:.1f}×")

    print()
    print("  [4. In-place buffer update vs. full rebuild]")
    rebuild_times = s4.get("full_rebuild_make_arrow", [])
    inplace_times = s4.get("inplace_buffer_update", [])
    for k, v in s4.items():
        print(_fmt_row(f"  {k}", v))
    if rebuild_times and inplace_times:
        speedup = statistics.mean(rebuild_times) / max(statistics.mean(inplace_times), 1e-6)
        print(f"       → in-place speedup: {speedup:.1f}×")

    print()
    print("  [5. T-slider animation: eval vs. eval+mesh]")
    eval_only = s5.get("anim_index_only", [])
    eval_mesh = s5.get("anim_index_plus_mesh", [])
    for k, v in s5.items():
        print(_fmt_row(f"  {k}", v))
    if eval_only and eval_mesh:
        eval_mean = statistics.mean(eval_only)
        mesh_mean = statistics.mean(eval_mesh) - eval_mean
        print(f"       → eval cost: {eval_mean:.3f} ms, mesh cost: {mesh_mean:.1f} ms")

    print()
    print("  " + "─" * 44 + "─┼─" + "─" * 10 + "─┼─" + "─" * 9 + "─┼─" + "─" * 9)
    mesh_full = s5.get("anim_index_plus_mesh", [])
    if mesh_full:
        mean, p95, _ = _stats(mesh_full)
        over = max(mean - _BUDGET_MS, 0.0)
        status = "PASS ✓" if mean <= _BUDGET_MS else f"FAIL ✗  ({over:.0f} ms over budget)"
        print(_fmt_row("  TOTAL FRAME (eval + make_arrow_mesh)", mesh_full))
        print(f"  {'TARGET  (33 ms = 30 fps)':<44} │  {_BUDGET_MS:>8.1f}  │  {'':>7}  │")
        print()
        print(f"  Result: {status}")
    print("═" * 74)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Headless benchmark for vector-field-animation.yml"
    )
    parser.add_argument("--n-arrows", type=int, default=4096,
                        help="Number of arrows (default: 4096 = 64×64 grid)")
    parser.add_argument("--frames",   type=int, default=30,
                        help="Timed frames per section (default: 30)")
    parser.add_argument("--mem",      action="store_true",
                        help="Run tracemalloc memory audit after timing")
    parser.add_argument("--no-gc",    action="store_true",
                        help="Disable Python GC during timing")
    args = parser.parse_args()

    if args.no_gc:
        gc.disable()
        print("[bench] GC disabled for timing isolation")

    print(f"[bench] n_arrows={args.n_arrows}  frames={args.frames}")
    print()

    print("[bench] Section 1/5: _arrow_matrix single-call cost ...")
    s1 = bench_arrow_matrix_single(args.frames)

    print("[bench] Section 2/5: make_arrow_mesh full pipeline ...")
    s2 = bench_make_arrow_mesh(args.n_arrows, args.frames)

    print("[bench] Section 3/5: vectorized batch matrix construction ...")
    s3 = bench_vectorized_matrices(args.n_arrows, args.frames)

    print("[bench] Section 4/5: in-place instance buffer update ...")
    s4 = bench_inplace_update(args.n_arrows, args.frames)

    print("[bench] Section 5/5: T-slider eval chain ...")
    s5 = bench_t_eval_chain(args.n_arrows, args.frames)

    if args.no_gc:
        gc.enable()

    _print_report(args.n_arrows, args.frames, s1, s2, s3, s4, s5)

    if args.mem:
        print("[bench] Running memory audit ...")
        _run_tracemalloc(args.n_arrows, min(args.frames, 20))


if __name__ == "__main__":
    main()
