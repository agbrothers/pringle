# Pringle — Closed Performance Issues

Performance issues that have been resolved are moved here from [18-performance-backlog.md](18-performance-backlog.md).

Each entry records the original description, the fix applied, and the measured improvement (if available from the regression benchmark in `tests/bench_slider_animation.py`).

See [20-profiling-sop.md](20-profiling-sop.md) for the profiling standard operating procedure.

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
