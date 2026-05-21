# Pringle — Closed Performance Issues

Performance issues that have been resolved are moved here from [18-performance-backlog.md](18-performance-backlog.md).

Each entry records the original description, the fix applied, and the measured improvement (if available from the regression benchmark in `tests/bench_slider_animation.py`).

See [20-profiling-sop.md](20-profiling-sop.md) for the profiling standard operating procedure.

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
