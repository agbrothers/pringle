# Pringle — Profiling Standard Operating Procedure

This document defines the repeatable process for profiling the Pringle application, interpreting results, and filing actionable issues. It covers Python CPU profiling, memory profiling, and Qt/GPU considerations.

**Performance target:** ≥ 30 fps at n=128 (≤ 33 ms total per animation frame).

See `gh issue list --label performance` for open issues.  
See `gh issue list --label performance --state closed` for resolved issues.

---

## 1. Overview of the Profiling Stack

Pringle is a hybrid application: Python CPU computation → Qt signals/slots → wgpu GPU rendering. Each layer requires a different tool. A complete profiling session touches all three.

```
Slider tick (16 ms)
  └─ _on_slider_value_changed           ← Python CPU: DAG + eval
       └─ run_cell × N cells            ← Python CPU: AST + exec + numpy
            └─ make_surface_mesh        ← Python CPU: index gen + normals + clipping
                 └─ gfx.Geometry/Mesh   ← Python CPU: pygfx object creation
                      └─ request_draw   ← GPU: wgpu buffer upload + render pass
```

**Key insight:** Fix the Python CPU layers first. GPU render time is rarely the bottleneck for Pringle-scale geometry at n=128. Profile in order: CPU → memory → GPU.

---

## 2. Tooling Reference

### 2.1 CPU Profiling

| Tool | When to use | Install |
|------|-------------|---------|
| **`py-spy`** | First look; attaches to live process, zero code changes, produces flame graphs | `pip install py-spy` |
| **`cProfile` + `pstats`** | Call-count + cumulative time for any script | stdlib |
| **`snakeviz`** | Interactive browser-based viewer for `.prof` files from cProfile | `pip install snakeviz` |
| **`line_profiler`** | Line-by-line timing of a specific function; requires `@profile` decorator | `pip install line_profiler` |
| **`scalene`** | Combined CPU + memory + GPU time; distinguishes numpy from pure-Python | `pip install scalene` |

### 2.2 Memory Profiling

| Tool | When to use | Install |
|------|-------------|---------|
| **`tracemalloc`** | Find allocation sites during a benchmark run | stdlib |
| **`memory_profiler`** | Line-level memory delta (RSS) via `@profile` decorator | `pip install memory-profiler` |
| **`pympler`** | Object-size auditing; useful for finding live object accumulation | `pip install pympler` |

### 2.3 Qt / Frame Timing

Pringle exposes `CellListWidget.last_eval_ms` for equation evaluation time. Extending this to a `last_render_ms` and `last_frame_ms` on `PringleWindow` provides a simple frame-time breakdown without external tools. Useful for quick regression checks in the live app.

### 2.4 GPU Profiling

GPU render time can be measured via wgpu timestamp queries (`GPUQuerySet`), but this is rarely the primary bottleneck for Pringle at n=128. Tools:
- **macOS:** Instruments → Metal System Trace
- **Cross-platform:** RenderDoc (supported by wgpu's Vulkan backend on Linux/Windows)

---

## 3. The Profiling Phases

### Phase 0 — Baseline capture

**Goal:** Establish a reproducible baseline before any optimization work.

**Steps:**

1. Run the headless benchmark and record its output:
   ```bash
   cd /path/to/pringle
   python tests/bench_slider_animation.py --n 128 --frames 100 | tee baseline_n128.txt
   ```

2. Generate a flame graph of the live app with py-spy (requires a display):
   ```bash
   # In one terminal: launch the app with memory.yml
   python -m pringle examples/memory.yml &
   APP_PID=$!

   # In another: record for 30 seconds while the β slider animates
   py-spy record --pid $APP_PID --output baseline_flame.svg --duration 30
   kill $APP_PID
   ```
   Open `baseline_flame.svg` in a browser. The widest frames at the top of the flame graph are the biggest time consumers.

3. Commit baseline numbers to `design-docs/` or a `benchmarks/` directory so future work has a reference point.

---

### Phase 1 — Isolate the hot path with cProfile

**Goal:** Get a ranked call-count + cumulative-time profile with no code changes to production code.

**Steps:**

1. Run the headless benchmark under cProfile:
   ```bash
   python -m cProfile -s cumulative tests/bench_slider_animation.py --n 128 --frames 60 \
     > cprofile_out.txt 2>&1
   head -60 cprofile_out.txt
   ```

2. For an interactive view:
   ```bash
   python -m cProfile -o bench.prof tests/bench_slider_animation.py --n 128 --frames 60
   python -m snakeviz bench.prof
   ```

3. Key columns to examine in the `pstats` output:
   - **`tottime`:** Time spent in the function itself (excluding callees). Highest `tottime` = the actual bottleneck.
   - **`cumtime`:** Total time including all callees. Useful for identifying expensive call chains.
   - **`ncalls`:** Call count. A function called 10,000× with small `tottime` is a different problem from one called once with large `tottime`.

4. Functions to watch (known hot from static analysis):
   - `ast.parse` — expected to appear high; measures PERF-006 impact
   - `_grid_indices` — expected high `tottime`; measures PERF-003 impact
   - `_clip_mesh_to_mask` — expected high `tottime`; measures PERF-004 impact
   - `build_equation_namespace` — expected multiple calls; measures PERF-005 impact
   - `build_dag` — expected on every tick; measures PERF-001 impact

---

### Phase 2 — Line-level profiling of confirmed hot functions

**Goal:** Get per-line timing for the specific functions identified in Phase 1.

**Steps:**

1. Install line_profiler:
   ```bash
   pip install line_profiler
   ```

2. Add `@profile` decorators to the target functions. Do NOT commit these decorators — they are for local profiling only. Typical targets:
   - `pringle/renderer.py`: `_grid_indices`, `_clip_mesh_to_mask`, `make_surface_mesh`
   - `pringle/evaluator.py`: `run_cell`
   - `pringle/cell_list.py`: `_on_slider_value_changed`, `_rebuild_namespace`
   - `pringle/dag.py`: `build_dag`, `cell_defines`, `cell_uses`

3. Run:
   ```bash
   kernprof -l -v tests/bench_slider_animation.py --n 128 --frames 30
   ```

4. Examine the `% Time` column. Lines above 10% are worth optimizing.

---

### Phase 3 — Memory allocation audit

**Goal:** Identify per-frame allocations that create GC pressure.

**Steps:**

1. Run the benchmark with `tracemalloc` enabled (the `--mem` flag in `bench_slider_animation.py`):
   ```bash
   python tests/bench_slider_animation.py --n 128 --frames 100 --mem
   ```
   This prints the top allocation sites after the benchmark run.

2. Watch for:
   - **Large allocations per frame:** numpy arrays ≥ 100 KB created on every tick suggest missing buffer reuse (PERF-002).
   - **pygfx object accumulation:** If `gfx.Geometry` / `gfx.Mesh` counts grow unboundedly across frames, old objects are not being garbage-collected before new ones are added.
   - **Python `list` growth in `_clip_mesh_to_mask`:** `new_pos`, `new_nor`, and `new_idx` are rebuilt via `.append()` every frame (PERF-004).

3. For detailed object counts:
   ```python
   from pympler import muppy, summary
   # snapshot before and after N frames, diff the summaries
   ```

---

### Phase 4 — Regression benchmark

**Goal:** Ensure that optimizations actually improve performance and do not regress other metrics.

**Steps:**

1. Before implementing a fix, record the baseline:
   ```bash
   python tests/bench_slider_animation.py --n 128 --frames 100 > before.txt
   ```

2. Implement the fix.

3. Record the post-fix numbers:
   ```bash
   python tests/bench_slider_animation.py --n 128 --frames 100 > after.txt
   diff before.txt after.txt
   ```

4. For a complete regression suite, test at multiple resolutions:
   ```bash
   for n in 64 128 256; do
     python tests/bench_slider_animation.py --n $n --frames 60
   done
   ```

5. The benchmark script prints a **pass/fail** line against the 33 ms target. This is the definition of "done" for each performance issue.

---

### Phase 5 — GPU profiling (when CPU work is already optimized)

**Goal:** Profile the wgpu render pass if the 30fps target is still missed after CPU fixes.

**Steps (macOS):**

1. Launch Instruments → Metal System Trace while the app is running.
2. Look for:
   - **Buffer upload time:** Large uploads per frame indicate PERF-002 is not fully fixed.
   - **Vertex shader time:** Scales with vertex count (n²); should be negligible at n=128.
   - **Fragment shader time:** Scales with pixel coverage; could be an issue for large overlapping transparent surfaces.

**Alternative (all platforms):** Add wgpu timestamp queries to `PringleRenderer.render()` to measure GPU time from within the app. See the wgpu-py docs for `GPUQuerySet`.

---

### Phase 6 — Document and file issues

**Goal:** Ensure every finding is tracked and every improvement is credited.

**Steps:**

1. File new bottlenecks discovered during profiling as GitHub Issues: `gh issue create --label performance --title "..." --body "..."`.
2. When a fix is merged, close the issue with a commit link: `gh issue close <N> --comment "Fixed in ..."`. Post before/after benchmark numbers from Phase 4 as a comment or edit the issue body.
3. Update the baseline numbers in `baseline_n128.txt` after each major fix.

---

## 4. Interpreting Benchmark Output

`bench_slider_animation.py` reports per-section timing in this format:

```
═══════════════════════════════════════════════════════
 Pringle Slider Animation Benchmark  (n=128, frames=100)
═══════════════════════════════════════════════════════

 Section                    │  Mean ms │  P95 ms │ % budget
 ───────────────────────────┼──────────┼─────────┼────────
 AST pipeline (per-cell)    │    0.42  │   0.61  │   2.5%
 Cell evaluation chain      │    8.31  │   9.14  │  25.2%
 Geometry: _grid_indices    │    7.83  │   8.20  │  23.7%
 Geometry: _grid_normals    │    1.12  │   1.31  │   3.4%
 Geometry: _clip_mesh       │   12.44  │  13.80  │  37.7%
 Geometry: make_surface     │   23.90  │  25.12  │  72.4%  ← includes above
 ───────────────────────────┼──────────┼─────────┼────────
 Estimated total frame      │   32.21  │  34.26  │  97.6%
 Target (33 ms / 30 fps)    │   33.00  │         │

 Result: PASS ✓  (mean within budget)
```

**Key columns:**
- **Mean ms:** Arithmetic mean across all benchmark frames. Use this for comparisons.
- **P95 ms:** 95th-percentile latency. If P95 >> mean, there is a sporadic stall (GC pause, OS scheduling).
- **% budget:** Mean as a percentage of the 33 ms frame budget. Sum of sub-sections can exceed 100% because some sections overlap (e.g., `make_surface` includes `_clip_mesh`).

---

## 5. Common Pitfalls

**Profiling in debug mode:** Python debug builds and un-optimized numpy builds can skew results by 2–5×. Always profile with the same Python/numpy as production.

**Thermal throttling:** On macOS laptops, sustained load causes CPU throttling. Warm up with `--frames 20` before the actual timed run, or use `--warmup N` explicitly.

**Qt event loop timing:** `cProfile` and `line_profiler` measure wall time including Qt event loop overhead when run through the live app. The headless benchmark eliminates this noise by calling evaluation functions directly.

**GC interference:** Python's cyclic garbage collector can fire during a benchmark frame, spiking P95. If P95 is >> 2× mean, run with `gc.disable()` to confirm whether GC is the cause, then re-enable it and investigate what is creating cyclic references.

**wgpu lazy uploads:** `gfx.Geometry` does not upload to GPU until the first render call that uses it. Per-frame GPU upload time will not appear in `make_surface_mesh` timing — it appears in the `render()` call. Use Phase 5 tools to measure this separately.
