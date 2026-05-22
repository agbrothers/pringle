# Animation and Time Variation

## Desmos's Approach

Desmos approximates time-varying behavior through **parameter animation**: any named parameter (slider) can be set to loop over a range at a fixed rate. There is no explicit "time" concept — `t` is just a slider that happens to increment automatically. This is flexible (you control the rate and range) but indirect.

Pringle can make time a first-class concept while preserving the same slider-driven flexibility.

## Core Model

Every expression can reference a set of **named parameters** in addition to spatial coordinates:

- `x`, `y`, `z`, `u`, `v` — spatial coordinates (reserved)
- `t` — time (reserved; auto-increments when animation is running)
- `a`, `b`, `n`, `k`, ... — user-defined sliders

Each parameter has:
- A current value
- A range `[min, max]`
- An optional animation mode: **loop**, **bounce**, **once**, or **static**
- A rate (units per second, or steps per second for discrete parameters)

## Animation Loop

```
_anim_timer tick (16 ms interval, SliderWidget)
    ↓
_anim_tick → value_changed signal → _on_slider_value_changed (main thread, ~0 ms)
    ↓
_dispatch_pending_eval (main thread):
    • Look up cached DAG (key comparison only — PERF-001)
    • Compute downstream_of(dag, slider_cell)
    • Skip invisible cells with no visible dependents (PERF-016)
    • Snapshot all cell state into _CellSpec dataclasses
    • Emit eval_requested signal (returns immediately)
    ↓
_EvalWorker.run_eval (background QThread — PERF-015):
    • For each spec in topological order:
        run_cell → surface/scatter data
        execute_recurrence if applicable (compile-once — PERF-013)
    • Emit results_ready signal
    ↓
_on_eval_results (main thread, queued connection):
    • Apply diagnostics and render callbacks
    • Drop stale results via generation counter
    ↓
PringleRenderer.render (GPU, driven by separate 16ms timer)
```

The main thread is free to handle camera events between `_dispatch_pending_eval` (which returns in microseconds) and `_on_eval_results`. Camera orbit, zoom, and WASD pan are processed continuously at 60 fps regardless of eval duration. If the worker is still busy when the next tick fires, the latest `(name, value)` is coalesced into `_pending_eval` and dispatched when the worker becomes free — animation frames are never queued.

**DAG caching (PERF-001):** `CellListWidget._get_dag()` caches the `nx.DiGraph` keyed on `{cell_id: source()}` for all evaluable cells. On a cache hit (unchanged sources — the entire animation duration), only a dict key comparison runs. Rebuild triggers only when a cell source changes.

**Invisible cell skipping (PERF-016):** After computing descendants, backward-reachability from visible output cells prunes the eval list. Invisible cells whose exports nothing visible depends on are skipped entirely. Invisible ancestors of visible cells remain in the eval set.

## Performance Model for Re-evaluation

| Approach | Cost at n=128 | Status |
|---|---|---|
| **CPU numpy eval + off-thread dispatch** | ~13 ms CPU (background); 0 ms main-thread block | **Current v1** |
| **GLSL/WGSL uniform** (t encoded in shader) | ~0.1ms | v2 — expression compiled to GPU shader |
| **GPU compute shader** (full grid eval on GPU) | ~1–2ms | v2 — deferred to FEAT-037 |

**Measured v1 budget at n=128 (memory.yml, constrained surface with recurrence path):**

| Component | Mean ms | % of 33 ms |
|---|---|---|
| DAG cache hit (PERF-001) | <0.01 | 0% |
| Cell evaluation chain | 5.35 | 16% |
| `make_surface_mesh` (constrained) | 4.07 | 12% |
| `execute_recurrence` (200 steps) | 3.35 | 10% |
| `make_scatter_mesh` (path output) | 0.75 | 2% |
| **Total CPU (background thread)** | **~13.2** | **40%** |
| GPU render callback (estimated) | ~9–10 | 30% |
| **Wall-clock frame** | **~22 ms → ~45 fps** | |

## Grid Resolution vs. Frame Rate Tradeoff

| Grid size | Vertices | CPU eval time (approx) | Notes |
|---|---|---|---|
| 64 × 64 | ~4K | < 2ms | Coarse; fine for fast prototyping |
| 128 × 128 | ~16K | ~13ms | Good default; 40% of budget |
| 256 × 256 | ~65K | ~50–80ms | High quality; exceeds 33ms budget; needs GPU eval for smooth animation |
| 512 × 512 | ~260K | ~200–400ms | Needs GPU eval |

A **multi-resolution strategy** (coarse while animating, fine when paused) is straightforward to implement and deferred to v2.

## Parametric Surfaces with Time

A time-varying parametric surface `(x,y,z) = f(u, v, t)` requires re-evaluating three functions per grid point per frame. At 128×128 this is ~16K evaluations of three numpy expressions — comfortably real-time on CPU.

```python
# Example: rotating parametric torus
# x = (R + r*cos(v)) * cos(u + t)
# y = (R + r*cos(v)) * sin(u + t)
# z = r * sin(v)
```

The user would enter three expressions (for x, y, z) referencing `u`, `v`, and any sliders including `t`.

## Slider UI

Each parameter entry in the expression panel should render as:

```
[ a ]  ──●───────────  [-2.0 ............. 5.0]   ▷ loop
```

Controls:
- Drag the handle to set value manually
- Click the range endpoints to edit bounds
- Click the play button to start animation
- Cycle through: loop / bounce / once / static

## Relationship to Expression Dependency Graph

The animation system only re-evaluates cells that **transitively depend on** the animated slider, determined by the cached DAG. A static surface `z = sin(x) * cos(y)` is never in the downstream set and is never evaluated during slider animation. Invisible cells that have no visible dependents are also skipped (PERF-016).

## Stretch Goals

- **ODE integration**: define a vector field `(dx/dt, dy/dt, dz/dt) = f(x,y,z,t)` and integrate trajectories using `scipy.integrate.solve_ivp`, rendering streamlines or particle paths
- **Frame recording**: export animation to GIF or MP4 using `imageio` or `ffmpeg`
- **Synchronized parameters**: multiple sliders can share a single animation clock (e.g., `a = sin(t)`, `b = cos(t)`)
