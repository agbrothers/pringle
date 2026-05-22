# Pringle — Performance Backlog

Performance issues are logged here as they are identified through static analysis, dynamic profiling, or user observation. Each entry includes a root cause analysis, estimated impact, and a suggested fix.

See [19-closed-performance.md](19-closed-performance.md) for resolved issues.  
See [20-profiling-sop.md](20-profiling-sop.md) for the profiling standard operating procedure.

**Performance target:** ≥ 30 fps at n=128 (≤ 33 ms total per animation frame).

---

## Measured Baseline (2026-05-19, n=128, 30 frames)

Run via `python tests/bench_slider_animation.py --n 128 --frames 30`.

| Component | Mean ms | % of 33ms budget |
|-----------|---------|-----------------|
| `_clip_mesh_to_mask` (→ BUG-001) | **170.2** | **516%** |
| `_grid_indices` (PERF-003) | **54.7** | **166%** |
| Cell evaluation chain (PERF-001, PERF-006) | **17.0** | **52%** |
| ↳ z_surface computation alone | 10.9 | 33% |
| `_grid_normals` | 2.6 | 8% |
| AST pipeline / 6 downstream cells (PERF-006) | 2.7 | 8% |
| `build_equation_namespace()` (PERF-005) | 0.02 | ~0% |
| **Estimated total frame** | **253** | **767%** |

**Effective frame rate at baseline: ~4 fps at n=128.**

---

## Intermediate Benchmark — After BUG-001 + PERF-003 (2026-05-20, n=128, 30 frames)

After BUG-001 partial fix and PERF-003 vectorization. Geometry functions timed directly via inline benchmark (bench script API mismatch after FEAT-038 refactor).

| Component | Mean ms | % of 33ms budget | vs baseline |
|-----------|---------|-----------------|-------------|
| `_clip_mesh_to_mask` (partial fix, PERF-010 pending) | **26.7** | **81%** | 6.4× faster |
| `_grid_gradients + _grid_normals` (FEAT-038) | 0.31 | 1% | — |
| `_grid_indices` (PERF-003, closed) | 0.19 | 1% | 295× faster |
| Cell evaluation chain (PERF-001, PERF-006) | **17.0** | **52%** | unchanged |
| **Estimated total frame** | **44** | **134%** | **5.7× faster** |

**~23 fps — below target.**

---

## Current Benchmark — After PERF-002 (2026-05-21, n=128)

After PERF-002 fix (live GPU buffer update; index buffer never re-uploaded during animation).

**Scope caveat:** PERF-002's in-place path requires `not has_constraint`. Constrained surfaces (e.g. memory.yml's `z < 3`) always take the full rebuild path and see no improvement from this fix. The numbers below apply to unconstrained surfaces only.

| Component | Mean ms | % of 33ms budget | vs baseline |
|-----------|---------|-----------------|-------------|
| `_clip_mesh_to_mask` (PERF-011 closed) | **1.4** | **4%** | 89× faster |
| `_grid_gradients + _grid_normals` (FEAT-038) | 0.29 | 1% | — |
| `_grid_indices` (PERF-003, closed) | 0.15 | 0% | 365× faster |
| Cell evaluation chain (PERF-001, PERF-006) | **17.0** | **52%** | unchanged |
| Surface geometry — in-place CPU (PERF-002) | **0.36** | **1%** | **5.0× faster** |
| **Estimated total CPU frame (unconstrained)** | **~19.0** | **58%** | **13.3× faster** |

Dev-measured surface geometry: 0.22 ms (6.6×); independent benchmark: 0.36 ms (5.0×) — same direction, timing variance.

JIT warmup: ~2.1 s first call in a fresh process; ~323 ms when loading the compiled cache on subsequent starts. One-time cost per process after the cache is warm.

---

## Current Benchmark — After PERF-013 (independently verified 2026-05-22, n=128, 60 frames, GC disabled)

Run via `python tests/bench_slider_animation.py --n 128 --frames 60 --no-gc`.

**PERF-013 independently verified:** `execute_recurrence` measured at **3.49 ms** (developer projected ~3.3 ms — within timing variance, confirmed). Two previously unmeasured components are now tracked: `build_dag` (PERF-001, called every tick) and `make_scatter_mesh` for scatter output cells (path output).

**Animation frame budget (β-slider, constrained surface, full accounting):**

| Component | Mean ms | P95 ms | % of 33ms budget | Notes |
|-----------|---------|--------|-----------------|-------|
| `build_dag + downstream_of` (PERF-001) | **2.18** | 2.68 | 7% | Called every tick; was missing from prior estimates |
| Cell evaluation chain (β downstream) | **5.68** | 7.37 | 17% | |
| ↳ `z_surface` computation | 3.36 | 5.05 | 10% | |
| `make_surface_mesh` (full, includes clip) | **4.91** | 6.17 | 15% | |
| ↳ `_clip_mesh_to_mask` (Numba, PERF-011 closed) | 1.70 | 2.09 | 5% | |
| ↳ `_grid_gradients + _grid_normals` | 0.59 | 1.00 | 2% | |
| ↳ `_grid_indices` | 0.16 | 0.27 | 0% | |
| AST pipeline (6 downstream cells, PERF-006) | 1.11 | 1.58 | 3% | |
| `execute_recurrence` (200 steps, PERF-013 closed) | **3.49** | 4.11 | 11% | **Verified** (was ~14 ms) |
| `make_scatter_mesh` (200-pt path output, PERF-014) | **0.73** | 1.18 | 2% | Was missing from prior estimates |
| **Estimated total CPU frame** | **~17.0** | ~18.9 | **52%** | |

**Result: PASS at 52% of 33 ms budget (surface update fps).** With GPU (~9–10 ms) estimated wall-clock is **~26 ms → ~38 fps**.

**Why camera still feels laggy despite PERF-013:**  
The PASS metric measures surface update fps, not camera responsiveness. The main thread is blocked for ~17 ms per animation tick. Since the animation timer fires every 16 ms, camera orbit/zoom mouse events are queued during those 17 ms blocking windows and processed in the sub-millisecond gaps between ticks. Average camera event latency ≈ 8–9 ms; worst-case ≈ 17 ms. This is above the ~5 ms threshold for "smooth" feel. PERF-013 helped surface fps (prior total ~28 ms → 17 ms) but the camera lag is structural: **eval runs synchronously in the Qt main thread**. The fix is threading (PERF-015 proposed) or a pause-on-interact interaction pattern.

**Breakdown before vs after PERF-013 (full accounting):**

| State | Total CPU blocking | Surface fps | Camera feel |
|-------|--------------------|-------------|-------------|
| Before PERF-013 | ~28 ms | ~36 fps | Laggy (28 ms block) |
| After PERF-013 | ~17 ms | ~59 fps | Still laggy (~17 ms block) |
| After PERF-001 (projected) | ~14.8 ms | ~67 fps | Marginal improvement |
| With eval threading (PERF-015) | ~0 ms block | ~60 fps | Smooth |

**Recurrence per-step breakdown (measured at individual component level, pre-PERF-013):**

| Per-step overhead | Mean µs | × 200 steps | Notes |
|-------------------|---------|------------|-------|
| `eval(string)` — compile + bytecode + numpy | 56.9 | **11.4 ms** | String recompiled on every eval call |
| `np.any(~np.isfinite(result[n]))` per-step | 3.7 | **0.73 ms** | Boolean alloc + reduction per step |
| `np.errstate(...)` context manager | 1.7 | **0.34 ms** | Enter + exit per step |
| Namespace dict copy `{**ns, ...}` (100 keys) | 0.6 | **0.12 ms** | Full ns copy each step |
| **Total** | **62.9** | **~12.6 ms** | (+overhead = ~14 ms measured) |

Compile-once speedup: `eval(code_object)` = 16.3 µs vs `eval(string)` = 56.9 µs → **3.5× on eval alone**.
Post-loop NaN check: `np.all(np.isfinite(result[1:]))` = 4.2 µs (once) vs 3.7 µs × 200 = 732 µs → **174× on NaN checks**.

---

## GPU Frame Timer Measurements (n=128)

**Method:** Qt frame-timer wrapper (`PRINGLE_FRAME_TIMING=1`). Times the `_pr.render()` callback wall-clock. Enabled via env var; zero overhead when unset. Cell evaluation runs in the Qt event loop *outside* this callback, so the two costs are additive.

### Pre-PERF-011 (2026-05-20) — memory.yml, constrained surface

| Phase | Cost | Notes |
|-------|------|-------|
| GPU render callback (steady state, p95) | **~9 ms** | Upload 771 KB mesh + Metal render commands |
| CPU cell evaluation (headless benchmark) | **~30 ms** | Outside render callback |
| **Total wall-clock frame** | **~39 ms → ~25 fps** | |
| First-frame spike | ~984 ms | Metal pipeline compile + initial buffer alloc |

### Post-PERF-011 (2026-05-20) — memory.yml, constrained surface

| Phase | Cost | Notes |
|-------|------|-------|
| GPU render callback (steady state, p95) | **~9.3 ms** | Unchanged — GPU work not affected by CPU fix |
| CPU cell evaluation (headless benchmark) | **~19 ms** | clip: 12.5 ms → 1.6 ms |
| **Total wall-clock frame** | **~28 ms → ~36 fps** | |
| First-frame spike | ~1,055 ms | +~350 ms Numba JIT on top of Metal compile |
| Subsequent starts (cached JIT) | ~984 ms | Numba loads from `__pycache__`; Metal still compiles |

### Post-PERF-002 (2026-05-21) — unconstrained surface, forced re-eval at 60 fps

| Phase | Cost | Notes |
|-------|------|-------|
| GPU render callback (steady state, p95) | **5.0 ms** | Skips 387 KB index upload; uploads z + normals only (~384 KB) |
| CPU cell evaluation (headless benchmark) | **~19 ms** | geometry in-place: 1.8 ms → 0.36 ms |
| **Total wall-clock frame** | **~24 ms → ~42 fps** | |
| First-frame spike | ~1,033 ms | Same as post-PERF-011 |

**Constrained surfaces (memory.yml): no GPU change.** Full rebuild path still uploads 771 KB/frame; GPU callback remains ~9.3 ms; wall-clock ~28 ms → ~36 fps.

**Key findings:**
- PERF-002 reduces GPU callback from ~9 ms to ~5 ms for unconstrained surfaces (4 ms saving, matches estimate)
- Constrained surfaces must use full rebuild — PERF-002 has no effect on them
- PERF-001 (DAG cache, ~3–5 ms CPU saving) is the largest remaining bottleneck for both surface types
- To reach ~50 fps on unconstrained surfaces: PERF-001 → estimated ~20 ms → ~50 fps
- To reach ~50 fps on constrained surfaces: needs PERF-001 + constrained in-place path (new work)

### Post-PERF-013 (2026-05-22) — memory.yml with gradient-path recurrence cell, full accounting

Full-stack accounting after PERF-013 verification. Prior estimates omitted `build_dag` (2.18 ms) and `make_scatter_mesh` for the path output (0.73 ms).

| Phase | Cost | Notes |
|-------|------|-------|
| `build_dag + downstream_of` (PERF-001) | **~2.2 ms** | Unconditional every tick; newly measured |
| Cell eval chain (β downstream) | **~5.7 ms** | |
| `make_surface_mesh` (constrained) | **~4.9 ms** | Full rebuild, no in-place path for constrained |
| `execute_recurrence` (200 steps) | **~3.5 ms** | After PERF-013; was ~14 ms |
| `make_scatter_mesh` (path output) | **~0.7 ms** | Newly measured; recreated every frame |
| **Total CPU blocking per tick** | **~17.0 ms** | |
| GPU render callback (estimated) | **~9–10 ms** | Same constrained surface |
| **Estimated wall-clock frame** | **~26 ms → ~38 fps** | Camera lag persists (see current benchmark note) |

---

## Priority Legend

| Priority | Description |
|----------|-------------|
| CRITICAL | Blocks 30fps target on its own; must fix before any other optimization |
| HIGH | Significant contribution to frame budget; fix in first optimization pass |
| MEDIUM | Measurable but not dominant; address in second pass |
| LOW | Minor; fix opportunistically or when touching the relevant code |

---

### PERF-001 — DAG rebuilt from scratch on every animation tick
**Status:** Open  
**Priority:** CRITICAL  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Files:** [dag.py:85-106](../pringle/dag.py#L85), [cell_list.py:808-831](../pringle/cell_list.py#L808)

**Description:**  
Every 16 ms slider animation tick triggers `_on_slider_value_changed`, which calls `build_dag(evaluable)` unconditionally before evaluating downstream cells. `build_dag` calls `cell_defines()` and `cell_uses()` for every evaluable cell in the session. Each of those calls `_preprocess_src()` (a regex match) and then `get_store_names()` or `get_free_names()` (a full `ast.parse()` round-trip). With memory.yml's ~20 evaluable cells this produces roughly **40 AST parses per frame** just to reconstruct a dependency graph that has not changed.

The DAG only changes when a cell's source text changes (`content_changed` signal). Between edits — including the entire duration of slider animation — the graph is identical on every tick.

**Estimated cost:** ~40 × `ast.parse()` + regex per frame; likely 2–5 ms per tick at n=128.

**Fix:**  
Cache the `nx.DiGraph` and the `downstream_of` result keyed on `{cell_id: source_text}` for the evaluable cells. Invalidate the cache in `_on_cell_changed` (the only signal that changes cell sources). On a slider tick, skip `build_dag` entirely and use the cached descendants list.

```python
# In CellListWidget.__init__:
self._dag_cache: nx.DiGraph | None = None
self._dag_source_key: dict[str, str] = {}  # cell_id → source at last build

def _get_dag(self, evaluable: list) -> nx.DiGraph:
    key = {c.cell_id: c.source() for c in evaluable}
    if key != self._dag_source_key or self._dag_cache is None:
        self._dag_cache = build_dag(evaluable)
        self._dag_source_key = key
    return self._dag_cache
```

---

### PERF-005 — `build_equation_namespace()` called twice per `run_cell` invocation
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Measured impact:** 0.02 ms per call at n=128 — effectively free; deprioritized relative to backlog  
**Files:** [evaluator.py:346](../pringle/evaluator.py#L346), [evaluator.py:365](../pringle/evaluator.py#L365)

**Description:**  
`run_cell` calls `build_equation_namespace()` at line 346 to build the execution namespace, and then calls it again at line 365 alongside `grid_vars(grid)` just to compute `base_keys` — the set of names that should not be exported from the cell's output. This second call constructs a fresh 100+-key dict and discards it immediately.

```python
# line 346 — used for execution:
local_ns = build_equation_namespace()

# line 365 — used only for key set, dict immediately discarded:
base_keys = set(build_equation_namespace().keys()) | set(grid_vars(grid).keys())
```

**Estimated cost:** 2 dict constructions per cell per frame; minor individually but the memory.yml β chain evaluates ~6 downstream cells per tick → 12 wasted namespace constructions per frame.

**Fix:** Precompute `_BASE_KEYS` as a module-level frozenset. Both `build_equation_namespace().keys()` and `grid_vars(make_grid()).keys()` are static; they do not depend on runtime state:

```python
# evaluator.py module level:
_BASE_KEYS: frozenset[str] = frozenset(build_equation_namespace()) | frozenset(grid_vars(make_grid()))

# run_cell: replace line 365 with:
for k, v in local_ns.items():
    if k.startswith("__") or k in _BASE_KEYS or k in MAGIC_NAMES:
        continue
    result.exports[k] = v
```

---

### PERF-006 — AST parsed 3× per `run_cell` invocation
**Status:** Open  
**Priority:** MEDIUM  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Files:** [evaluator.py:333-339](../pringle/evaluator.py#L333), [safety.py:52-60](../pringle/safety.py#L52), [safety.py:63-81](../pringle/safety.py#L63), [safety.py:84-140](../pringle/safety.py#L84)

**Description:**  
For each equation cell evaluation, `run_cell` triggers three separate `ast.parse()` calls on the same preprocessed source string:

1. `get_free_names(preprocessed)` — parses to find Load references  
2. `get_store_names(preprocessed)` — parses again to find Store targets  
3. `check_ast(preprocessed)` — parses a third time for the security walk

Each parse is independent; the AST object is not shared between them. Additionally, the DAG functions (`cell_defines`, `cell_uses` in `dag.py`) parse the same source a fourth and fifth time per rebuild tick.

**Estimated cost:** At ~50 µs per `ast.parse` call on typical expression lengths, 3 parses per cell × 6 downstream cells = 18 parse calls per frame ≈ ~0.9 ms. Larger cells and larger sessions will scale this higher.

**Fix:** Parse once in `run_cell` and pass the `ast.Module` object to all consumers. Requires adding an `ast_tree` parameter to `get_free_names`, `get_store_names`, and `check_ast`:

```python
# evaluator.py
tree = ast.parse(preprocessed, mode="exec")
result.free_names = get_free_names(preprocessed, tree=tree)
user_stores = get_store_names(preprocessed, tree=tree)
if not is_data_cell:
    check_ast(preprocessed, tree=tree)
```

---

### PERF-007 — Shadow geometry created unconditionally even when shadows are disabled
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Files:** [renderer.py:592-603](../pringle/renderer.py#L592)

**Description:**  
`add_object` always calls `_make_shadow_object(obj)` and, if successful, adds the shadow to the scene. This copies position arrays and creates `gfx.Geometry`/`gfx.Mesh` scene objects even when `self._shadow_visible` is `False` (the default). The shadows are then immediately hidden via `.visible = False`, but the allocation and scene-graph overhead still occurs every frame.

**Fix:** Guard the shadow creation with `if self._shadow_visible`:

```python
def add_object(self, cell_id: str, obj: gfx.WorldObject) -> bool:
    is_new = cell_id not in self._objects
    self.remove_object(cell_id)
    self._objects[cell_id] = obj
    self._scene.add(obj)
    if self._shadow_visible:                    # ← add this guard
        shadow = self._make_shadow_object(obj)
        if shadow is not None:
            shadow.visible = True
            self._scene.add(shadow)
            self._shadow_objects[cell_id] = shadow
    return is_new
```

---

### PERF-008 — Viewport issues unconditional `request_draw()` at 60 fps regardless of scene state
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Files:** [app.py:68-71](../pringle/app.py#L68)

**Description:**  
`PringleViewport._tick()` calls `self.request_draw()` unconditionally every 16 ms — even when no slider is animating, no cell has changed, and the camera has not moved. This causes the wgpu renderer to re-render an identical scene at 60 fps, consuming GPU time and power for no visual benefit.

**Fix:** Introduce a `_scene_dirty` flag on `PringleRenderer`. Set it in `add_object`, `remove_object`, `set_visible`, `_rebuild_overlay`, and during active camera orbit/pan. Clear it after each `render()` call. In `_tick`, only call `request_draw()` if the scene is dirty or held keys are active.

---

### PERF-009 — `_always_defined()` in `dag.py` rebuilds the equation namespace on first call
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Files:** [dag.py:26-35](../pringle/dag.py#L26)

**Description:**  
`_always_defined()` lazily builds and caches its result from `build_equation_namespace()` on first call — this is fine. However, if the module is freshly imported (new process), the first DAG build pays a construction cost. Additionally, the result is a module-level `global` mutated in-place, which can cause subtle bugs in multi-threaded futures.

**Fix:** Replace with a module-level constant computed at import time:

```python
from pringle.namespace import build_equation_namespace
from pringle.preprocess import SPATIAL_NAMES

_ALWAYS_DEFINED: frozenset[str] = (
    frozenset(build_equation_namespace())
    | SPATIAL_NAMES
    | {"t", "True", "False", "None"}
)
```

---


### PERF-012 — Numba JIT for recurrence-relation cell evaluation
**Status:** Open  
**Priority:** LOW — not currently applicable; logged for future architecture consideration  
**Logged:** 2026-05-20  
**Discovered via:** GPU library evaluation (FEAT-037)

**Description:**  
Cells that define sequential recurrence relations (`arr[n] = f(arr[n-1])`) cannot be vectorized with numpy and cannot use JAX/PyTorch (immutable array semantics). Currently they must be written as Python `for` loops, which is ~100× slower than C for numerical kernels of this shape.

Numba `@njit` is the correct solution for this pattern: it compiles mutable-array sequential loops to native code, runs them in place without copies, and requires no API changes to the array interface. The blocker is that Pringle cells are evaluated via `exec()` on a user-supplied string — dynamic code that cannot be JIT-compiled.

**Possible approaches:**
- **Specialized recurrence cell type:** A dedicated cell variant (e.g. `[recurrence]`) that accepts a restricted grammar (`x[i] = f(x, i)`) and compiles it to a Numba kernel at definition time. The compiled kernel is cached and called on every animation tick. This is a significant feature addition but would make iterative numerical methods (ODE solvers, time-series, cellular automata) run at near-C speed.
- **Numba-aware helper functions in the namespace:** Add a `@numba.njit`-compiled `cumulate(fn, x0, n)` or similar utility to `build_equation_namespace()`. Users write the body as a lambda; Numba JITs it on first call. Simpler than a new cell type but limited to fixed-structure recurrences.

**Why it matters:** Recurrence relations are a natural Pringle use case (Fibonacci, Lorenz attractor, Mandelbrot iteration count, forward Euler ODE). Without Numba, large N makes these prohibitively slow. With it, they become competitive with MATLAB/Julia.

---

### PERF-014 — `make_scatter_mesh` recreated from scratch every frame for recurrence output cells
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-22  
**Discovered via:** Independent profiling (benchmark section 8)  
**Files:** [app.py:617-629](../pringle/app.py#L617), [renderer.py](../pringle/renderer.py)

**Description:**  
After each `execute_recurrence` call in `_on_slider_value_changed`, `_on_cell_result` calls `make_scatter_mesh` (or `make_line_mesh`) to rebuild the full pygfx geometry object for the scatter/line output — allocating new `gfx.Geometry` and `gfx.Mesh` objects on every animation tick. For a 200-point path this costs ~0.73 ms per frame.

The surface cells already have an in-place update path (`update_surface` / PERF-002). Scatter/line cells currently always go through `add_object`, which discards and recreates the geometry.

**Measured cost:** 0.73 ms per frame for a 200-pt scatter; 0.77 ms for line. At 17 ms total blocking time per tick, this is 4–5% of the frame.

**Fix:** Add an `update_scatter` / `update_line` path in `PringleRenderer` analogous to `update_surface`: update the position buffer in-place if the point count hasn't changed; only rebuild the geometry object on count change. Gate in `app.py`'s `_on_cell_result` similar to `update_surface`.

---

### PERF-015 — Cell evaluation blocks Qt main thread; camera orbit laggy during animation
**Status:** Open  
**Priority:** HIGH  
**Logged:** 2026-05-22  
**Discovered via:** Independent profiling + user observation  
**Files:** [cell_list.py:720-765](../pringle/cell_list.py#L720), [slider_widget.py:317-331](../pringle/slider_widget.py#L317)

**Description:**  
The slider animation timer (`_anim_timer`, 16 ms interval) fires `_anim_tick` → `value_changed` → `_on_slider_value_changed`. The entire cell evaluation chain (~17 ms: DAG rebuild 2.2 ms + eval chain 5.7 ms + surface mesh 4.9 ms + recurrence 3.5 ms + scatter mesh 0.7 ms) runs synchronously in the Qt main thread.

Because evaluation takes ~17 ms and the timer interval is 16 ms, the main thread is blocked for essentially 100% of the animation cycle. Camera orbit/zoom mouse events queue up in the Qt event loop during evaluation and can only be processed in the ~0 ms windows between ticks. This manifests as "framey/laggy" camera rotation even when the surface update fps is acceptable.

**This is the root cause of the camera lag.** PERF-013 improved surface fps (28 ms → 17 ms per tick) but did not cross the ~5–8 ms threshold needed for smooth camera feel because the blocking period is still longer than the timer interval.

**Measured impact:** Average camera event latency ~8–9 ms; worst-case ~17 ms. Smooth threshold is ~5 ms.

**Fix options (in order of complexity):**

1. **Pause animation on mouse press (pragmatic, low effort):** Detect `mousePressEvent` / `mouseReleaseEvent` on `PringleViewport`. While mouse button is held, stop `_anim_timer`. Resume on release. Trades animation continuity during orbit for smooth camera — acceptable for interactive use. ~20 lines of code.

2. **Throttle animation to leave headroom (simple, imperfect):** Change `_ANIM_INTERVAL_MS` from 16 ms to e.g. 33 ms (30 fps animation). Between ticks, the event loop processes mouse events. Halves animation smoothness but nearly eliminates camera lag.

3. **Off-thread evaluation (correct, complex):** Move `_on_slider_value_changed` evaluation to a `QThread`. The eval thread posts results back to the main thread via a queued signal. Main thread handles camera events continuously at 60 fps. Requires thread-safety audit for namespace dict access and pygfx object creation (which may need to stay on the main thread).

---

### PERF-016 — Invisible output cells evaluated unconditionally during animation
**Status:** Open  
**Priority:** MEDIUM  
**Logged:** 2026-05-22  
**Discovered via:** User observation + code review  
**Files:** [cell_list.py:754-763](../pringle/cell_list.py#L754)

**Description:**  
`_on_slider_value_changed` calls `_eval_cell` for every cell in `descendants`, regardless of visibility. Invisible cells that don't export anything used by a visible cell are pure dead weight — their computation runs but their result is immediately discarded via `_on_cell_result(cell_id, CellResult(), style)` (no mesh created, no namespace value consumed downstream).

In memory.yml, toggling off `path_xy` does NOT skip `execute_recurrence` — it still runs 200 eval steps at ~3.5 ms per tick. Mesh creation is already skipped (the renderer already guards this correctly), but the numpy computation is not.

**Measured savings:** Up to 3.5 ms per tick when `path_xy` is invisible (the recurrence cell). More generally: any invisible output cell whose exports are unused saves its full `run_cell` cost.

**Fix:** After computing `descendants`, determine which cells are "needed" by performing backward reachability from visible output cells through the already-computed DAG. Skip `_eval_cell` (but not the slider value update) for cells outside the required set:

```python
# Visible output cells: need their computation + all their ancestors
visible_ids = {
    c.cell_id for c in descendants
    if not isinstance(c, SliderWidget) and self._is_render_visible(c)
}
required_ids = set(visible_ids)
for vid in visible_ids:
    required_ids.update(nx.ancestors(dag, vid))

for cell in descendants:
    if isinstance(cell, SliderWidget):
        shared[cell.name] = _ns_value(cell.value)
        continue
    if cell.cell_id not in required_ids:
        continue  # invisible and no visible cell depends on its exports
    result = self._eval_cell(cell, shared)
    shared.update(result.exports)
    self._on_cell_result(cell.cell_id, result, cell.style)
```

**Correctness:** Skipping a cell means its exports are absent from `self._shared_ns`. When the cell is made visible again, `_on_equation_cell_visibility_toggled` triggers a re-evaluation, repopulating the namespace.  
**Note:** Works best combined with PERF-001 (DAG cache) since the DAG is already being computed; adding `nx.ancestors` per visible cell is O(V+E) on the subgraph.

---

## YAML Equation Optimization Issues

These issues are specific to how expressions are written in session files and represent tips that can be documented in a user-facing guide.

---

### PERF-Y01 — `shape = array([x, y]).shape[1:]` allocates a full temporary array to read a shape
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis of memory.yml  
**Session file:** examples/memory.yml

**Description:**  
The UTILS/shape cell constructs a full `(2, 128, 128)` array (≈ 786 KB at n=128) merely to call `.shape[1:]`. Since `x` is already a `(n, n)` array, the shape is simply `x.shape`.

**Current expression:**
```python
shape = array([x, y]).shape[1:]
```

**Optimized expression:**
```python
shape = x.shape
```

This avoids a 786 KB allocation on every evaluation of this cell.

---

### PERF-Y02 — `E` function uses a Python list comprehension that inhibits vectorization
**Status:** Open  
**Priority:** MEDIUM  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis of memory.yml  
**Session file:** examples/memory.yml

**Description:**  
The ENERGY/E cell is defined as:
```python
E(v) = -β_inv * Q( sum( [F ( β*( S(m[:, None], v) ) ) for m in M], axis=0))
```

The `[... for m in M]` list comprehension iterates over the rows of `M` one at a time in Python, creating `k` intermediate arrays (one per memory point) before passing a Python list to `sum`. For k=10 memory points this is 10 separate numpy calls and Python iterations.

`E_batch` — the visible surface cell — already uses the fully batched `InvDistSqBatch` and is the correct implementation. However, `E` is still visible in the session and could mislead users who copy it.

**Note:** `E` is set to `visible: false` in memory.yml, so it does not currently affect rendering performance. This is a documentation issue — the non-batch version should be clearly marked as the naive/reference implementation.

**Optimized pattern:** Always prefer batch operations over Python loops over array rows. See [21-equation-tips.md](21-equation-tips.md) (forthcoming) for the full vectorization guide.

---

### PERF-Y03 — `logsumexp` could replace `log(sum(exp(...)))` for numerical stability and speed
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis of memory.yml  
**Session file:** examples/memory.yml

**Description:**  
`E_batch(v) = -β_inv * Q( sum( F( β * InvDistSqBatch(M, v) ), axis=0))` expands to:

```
-(1/β) * log( sum( exp( β * (-||m - v||²) ), axis=0 ) )
```

This is exactly the log-sum-exp pattern. `scipy.special.logsumexp` computes this in a numerically stable way (avoiding overflow for large β) and is typically faster than the explicit `log(sum(exp(...)))` chain because it can use the max-shift trick internally.

**Optimized expression:**
```python
E_batch(v) = β_inv * logsumexp(-β * InvDistSqBatch(M, v), axis=0)
```

Note the sign flip: `InvDistSqBatch` returns negative squared distances, so the signs work out.

`logsumexp` is now available in the equation namespace (`namespace.py`). The optimization can be applied directly in `examples/memory.yml`.
