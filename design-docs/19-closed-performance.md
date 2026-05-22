# Pringle — Closed Performance Issues

Performance issues that have been resolved are moved here from [18-performance-backlog.md](18-performance-backlog.md).

Each entry records the original description, the fix applied, and the measured improvement (if available from the regression benchmark in `tests/bench_slider_animation.py`).

See [20-profiling-sop.md](20-profiling-sop.md) for the profiling standard operating procedure.

---

### PERF-002 — Full GPU geometry recreated on every surface update
**Status:** Closed (fixed 2026-05-21)  
**Priority:** CRITICAL  
**Measured cost before:** ~1.44 ms CPU geometry rebuild + ~387 KB index buffer re-uploaded to GPU every animation frame

**Root cause:** `make_surface_mesh` constructed brand-new `gfx.Geometry` and `gfx.Mesh` objects on every call. `add_object` removed the old scene object and added the new one, triggering a full GPU buffer upload (~771 KB: positions + indices + normals). During slider animation, only z-values change — the index buffer and x/y positions are constant across all frames.

**Fix:** Added `_surface_geo`, `_surface_mesh`, and `_surface_sig` caches to `PringleRenderer`. On the first frame per cell (or after any topology change), the full rebuild runs and the geometry is cached. On subsequent animation frames where no constraint is active and the grid shape + colormap mode are unchanged:
- `geo.positions.data[:, 2] = z.ravel()` + `update_full()` — uploads only positions buffer
- `geo.normals.data[:] = _grid_normals(...)` + `update_full()` — uploads only normals buffer
- `geo.colors.data[:]` updated only when a colormap is active
- Index buffer (387 KB) is **never re-uploaded** after the first frame

Topology signature `(rows, cols, has_colormap)` guards the cache — any change triggers a full rebuild. Constraint-active frames always rebuild (topology may change). Cache is cleared in `remove_object`.

**Measured outcome (2026-05-21, headless CPU benchmark):**

| Metric | Before | After | Speedup |
|--------|--------|-------|---------|
| CPU geometry update | 1.44 ms | **0.22 ms** | **6.6×** |
| GPU index upload | ~387 KB/frame | **0 KB** (skipped) | — |
| Estimated GPU render callback | ~9.3 ms | **~4–5 ms** (est.) | **~2×** |

GPU savings are additive to CPU savings and not directly measurable without a real render loop + wgpu timestamp queries.

---

### PERF-011 — Python boundary loop in `_clip_mesh_to_mask` (Numba JIT)
**Status:** Closed (fixed 2026-05-20)  
**Priority:** HIGH  
**Measured cost before:** 12.5 ms at n=128 (38% of frame budget)

**Root cause:** After PERF-010, the remaining cost in `_clip_mesh_to_mask` was the Python `for tri in boundary_tris` loop (~522 triangles at n=128). Each iteration called `_bv` with `np.linalg.norm` on a length-3 array — numpy function-call overhead at this granularity cost ~24 µs/triangle in Python.

**Fix:** Ported the boundary loop to `_clip_boundary_njit` — a standalone `@numba.njit(cache=True)` function. Key decisions:
- Edge cache uses `numba.typed.Dict(int64 → int32)` with packed `(lo << 32) | hi` keys (avoids `UniTuple` typing issues across numba versions)
- Replaced `np.linalg.norm` with inline `math.sqrt(nx*nx + ny*ny + nz*nz)` — one FPU instruction
- Output arrays pre-allocated at `2 * len(boundary_tris)` (maximum possible); sliced to actual count after return
- Python fallback path preserved for environments without numba
- `numba>=0.59` added to `pyproject.toml` dependencies

**Measured outcome (2026-05-20, n=128, 30 calls steady-state):**

| Metric | Before | After | Speedup |
|--------|--------|-------|---------|
| `_clip_mesh_to_mask` | 12.5 ms | **1.4 ms** | **8.8×** |
| Estimated CPU frame total | 30.0 ms | **~18.9 ms** | — |
| Effective CPU fps | ~33 fps | **~36 fps** | — |

**JIT warmup:** ~2.1 s first call in a fresh process (full LLVM compile); ~323 ms on subsequent starts (loads precompiled cache from `__pycache__`). One-time cost per process when a constrained surface is first rendered.

---

### PERF-010 — O(n²) vertex list/array roundtrip in `_clip_mesh_to_mask`
**Status:** Closed (fixed 2026-05-20)  
**Priority:** CRITICAL  
**Measured impact:** ~13 ms of the 26.7 ms post-BUG-001 `_clip_mesh_to_mask` cost at n=128

**Root cause:** After BUG-001's vectorized fast path, `new_pos = list(positions)` still converted all 16,384 vertex rows to a Python list unconditionally every frame. `np.array(new_pos)` then rebuilt the array row-by-row. Only ~512 new boundary vertices were ever appended, but the full 16K conversion paid the cost regardless.

**Fix:** Removed `list(positions)` / `list(normals)` entirely. New boundary vertices accumulate in small `new_verts_pos` / `new_verts_nor` Python lists (only the ~512 new ones). Final arrays built with `np.concatenate([positions, np.array(new_verts_pos)])` — original array is a zero-copy slice, `np.array()` call is now O(n) for boundary vertices only. When no boundary vertices are added, the original arrays are returned directly with no allocation.

**Measured outcome (2026-05-20, n=128, 30 frames):**

| Metric | Estimated | Actual |
|--------|-----------|--------|
| `_clip_mesh_to_mask` after fix | 3–5 ms | **12.5 ms** |
| Total estimated frame | ~20 ms | **30.0 ms** |
| Effective fps | ~50 fps | **~33 fps** |

**30 fps target met.** Estimated 3–5 ms was not achieved; actual 12.5 ms reflects the Python loop cost over ~522 boundary triangles, which was not eliminated by PERF-010. Each `_bv` call performs per-vertex numpy operations (`np.linalg.norm` on a length-3 array) and Python attribute lookups — at ~24 µs/triangle for 522 triangles, this accounts for the remaining ~12 ms. Further reduction requires either Numba `@njit` on the boundary loop body or a fully vectorized boundary triangle split (complex, variable output count). Neither is needed to meet the current 30 fps bar.

---

### PERF-004 / BUG-001 — Python loop in constraint mesh clipping + midpoint interpolation
**Status:** Closed (fixed 2026-05-20)  
**Priority:** CRITICAL  
**Measured impact:** 170.2 ms at n=128 before fix (516% of frame budget)

**Root cause:** `_clip_mesh_to_mask` iterated every triangle in a Python `for` loop, and placed boundary vertices at edge midpoints rather than true zero-crossings.

**Fix:** Vectorized fast path (numpy boolean indexing) handles all-inside and all-outside triangles in bulk — only O(n) boundary triangles go through the Python loop. Signed constraint values (`f_values`: float, positive = inside) computed via AST evaluation of the constraint expression, enabling `t = f_A / (f_A - f_B)` zero-crossing interpolation in `_bv`. See BUG-001 in [16-closed-bugs.md](16-closed-bugs.md) for full details.

---

### PERF-016 — Invisible output cells evaluated unconditionally during animation
**Status:** Closed (fixed 2026-05-22)
**Priority:** MEDIUM
**Measured savings:** Up to 3.5 ms per tick when a recurrence output cell is invisible (skips `execute_recurrence` entirely)

**Root cause:** `_on_slider_value_changed` called `_eval_cell` for every cell in `descendants`, regardless of visibility. Invisible cells whose exports nothing visible depends on were pure dead weight — the numpy computation ran but the result was immediately discarded via `_on_cell_result(cell_id, CellResult(), style)`.

**Fix:** After computing `descendants`, backward-reachability from visible output cells through the DAG produces `required_ids`. Only cells in `required_ids` call `_eval_cell`; invisible cells with no visible dependents are skipped entirely. Invisible cells that ARE ancestors of a visible cell remain in `required_ids` and are still evaluated. See [cell_list.py:754-780](../pringle/cell_list.py#L754).

**Correctness invariant:** Skipped cells retain their previous export values in `_shared_ns` (copied at the start of each tick). When a cell is made visible again, `_on_equation_cell_visibility_toggled` re-evaluates it, refreshing the namespace. Tests in `test_phase6.py::TestCellListSlider` cover both the skip case and the ancestor-still-evaluated case.

---

### PERF-013 — `execute_recurrence` re-compiles RHS string and checks NaN on every step
**Status:** Closed (fixed 2026-05-22)
**Priority:** HIGH
**Measured cost before:** ~14 ms per animation tick for a 200-step recurrence cell (42% of 33 ms frame budget)

**Root cause:** Three per-step overheads compounded over the full recurrence loop:
- `eval(string)` re-invoked `compile()` on every iteration: 56.9 µs/step × 200 = **11.4 ms**
- `np.errstate(...)` context manager entered/exited every step: 1.7 µs × 200 = **0.34 ms**
- `{**namespace, array_name: result, "n": n}` copied the 100-key namespace dict every step: 0.6 µs × 200 = **0.12 ms**
- `np.any(~np.isfinite(result[n]))` ran a boolean reduction every step: 3.7 µs × 200 = **0.73 ms**

**Fix:** Three changes in `execute_recurrence` ([recurrence.py:70-82](../pringle/recurrence.py#L70)):
1. `compile(rhs, "<recurrence>", "eval")` once before the loop; pass the code object to `eval` instead of the string
2. Shared globals dict `{**namespace, "__builtins__": {}, array_name: result}` — only `{"n": n}` passed as locals per step (single-key dict); `result` is mutated in-place so `glob[array_name]` is always current with no sync
3. `np.errstate` moved outside the loop; `np.all(np.isfinite(result[1:]))` called once post-loop instead of per step

**Measured outcome (projected from per-step profiling, 200-step cell):**

| Metric | Before | After | Speedup |
|--------|--------|-------|---------|
| Per-step eval | 56.9 µs | ~16.3 µs | **3.5×** |
| Per-step NaN check | 3.7 µs | ~0 µs (post-loop) | — |
| Total recurrence (200 steps) | ~14 ms | ~3.3 ms | **~4.2×** |
| Estimated CPU frame (with recurrence) | ~24 ms | ~13.3 ms | — |
| Estimated wall-clock fps | ~30 fps | ~45 fps | — |

---

### PERF-003 — Python nested-loop triangle index generation
**Status:** Closed (fixed 2026-05-19)  
**Priority:** CRITICAL  
**Measured impact:** 54.7 ms at n=128 before fix (166% of frame budget)

**Root cause:** `_grid_indices(rows, cols)` used a nested Python `for r / for c` loop with `.append()` to build triangle indices — ~65,000 Python iterations at n=128.

**Fix:** Replaced with fully vectorized numpy broadcasting in `renderer.py`:
```python
r = np.arange(rows - 1, dtype=np.int32)[:, None]
c = np.arange(cols - 1, dtype=np.int32)[None, :]
i = (r * cols + c).ravel()
t1 = np.column_stack([i,     i + 1,        i + cols])
t2 = np.column_stack([i + 1, i + cols + 1, i + cols])
return np.vstack([t1, t2])
```
Zero Python loops; runs in microseconds. Output is identical (same triangle winding order).
