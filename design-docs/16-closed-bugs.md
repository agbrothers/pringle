# Pringle — Closed Bugs

Bugs that have been resolved. Entries are preserved here for historical reference.

See [14-bug-backlog.md](14-bug-backlog.md) for open bugs.

---

### BUG-001 — Constraint edge clipping jagged + 170 ms bottleneck
**Status:** Closed (fixed 2026-05-20)  
**Severity:** Critical (both quality and performance)

**Root cause:** Two independent defects: (1) boundary vertices placed at the edge midpoint rather than the true constraint zero-crossing — the inserted vertex was in the wrong place so the clipped boundary did not follow the constraint curve; (2) every triangle (~32,258 at n=128) was iterated in a Python `for` loop even though only the O(n) perimeter triangles straddle the boundary.

**Fix:**
- `evaluator.py` — added `_eval_signed_constraint` helper: for simple comparison expressions (`<`, `<=`, `>`, `>=`) uses AST parsing to evaluate the signed constraint value as a float (positive = inside). `apply_constraints` now returns a third value `constraint_values` (float32, positive = inside) when `return_mask=True`. `CellResult` gains `constraint_values` field.
- `renderer.py:_clip_mesh_to_mask` — signature changed from `inside: bool[]` to `f_values: float[]`; `inside` derived as `f_values >= 0`. Vectorized fast path: `inside_count = inside[indices].sum(axis=1)` → all-inside triangles (`inside_count == 3`) concatenated directly via numpy, all-outside discarded; Python loop restricted to `boundary` triangles only (`~512` at n=128 vs ~32,258 before). `_bv` uses `t = f_A / (f_A - f_B)` for zero-crossing interpolation (NaN/degenerate fallback to midpoint).
- `make_surface_mesh` — added `constraint_values` param; prefers it over `constraint_mask` for the clip call.
- `app.py` — passes `result.constraint_values` to `make_surface_mesh`.

**Measured impact (2026-05-20, n=128, 30 frames):**

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| `_clip_mesh_to_mask` | 170.2 ms | **26.7 ms** | 6.4× faster |
| `_grid_indices` (PERF-003 ref) | 54.7 ms | 0.19 ms | 295× faster |
| Estimated total frame | 253 ms | **44 ms** | 5.7× faster |
| Effective fps | ~4 fps | **~23 fps** | — |

**Quality fix confirmed:** boundary now follows the constraint curve exactly. Visual improvement is significant.

**Remaining performance issue in `_clip_mesh_to_mask`:** Expected "<1 ms" not achieved. Actual 26.7 ms is dominated by a remaining O(n²) cost on lines 99–100 and 153–154: `new_pos = list(positions)` and `new_nor = list(normals)` convert the full 16,384-vertex arrays to Python lists (measured at ~13 ms alone), and `np.array(new_pos)` converts them back. This conversion occurs unconditionally even though only ~512 boundary vertices are added. See **PERF-010** in `18-performance-backlog.md` for the fix.

**Status:** Quality fix complete; performance fix incomplete. Frame rate at ~23 fps vs 30 fps target.

---

### BUG-020 — Hard crash when a callable is assigned to a magic variable (`z`, `xyz`, etc.)
**Status:** Closed (fixed 2026-05-20)  
**Severity:** Critical

**Root cause:** `_detect_magic` returned `("surface", val)` unconditionally when `"z"` was in `user_stores`, without checking that `val` is numeric. A callable (ufunc, lambda, function) was passed as `data` into `np.asarray(data, dtype=np.float32)`, which raised `TypeError` — uncaught, aborting the process.

**Fix:**
- `_detect_magic` (`evaluator.py`) — callable guard on the `z` and `xyz` branches: if the value is callable and not an ndarray, return `(None, None)` so the func-auto-render path handles it normally.
- `run_cell` (`evaluator.py`) — `try/except (TypeError, ValueError)` around all four `np.asarray(data, ...)` normalization calls (surface, curve, scatter, parametric); type failures produce a cell error message instead of an exception.
- `_eval_cell` (`cell_list.py`) — already wrapped by the BUG-009 fix; any remaining unanticipated evaluator exception becomes a cell error rather than a crash.

---

### BUG-009 — Hard crash (`Abort trap: 6`) when data cell produces NaN or Inf
**Status:** Closed (fixed 2026-05-20)  
**Severity:** Critical

**Root cause:** Three-layer failure: (1) forward Euler integration diverges to float64 infinity; (2) `arr.astype(np.float32)` silently converts those to `inf`/`NaN` with only a RuntimeWarning; (3) `_fmt_scalar` called `int(f)` on a NaN float — `f == int(f)` raises `ValueError` before the return expression fires. The exception propagated uncaught through the entire call stack and aborted the process.

**Fix — three complementary layers:**
- `evaluator.py:_fmt_scalar` — `math.isfinite(f)` guard before any integer conversion; returns `"nan"`, `"inf"`, or `"-inf"` for non-finite values. Added `import math`.
- `evaluator.py:run_cell` — wrapped the value-preview loop in `try/except Exception` so any formatting error degrades to no preview rather than propagating.
- `cell_list.py:_eval_cell` — wrapped the `run_cell()` call in `try/except Exception`; any unanticipated evaluator exception becomes a cell error instead of a process crash.
- `cell_list.py:_run_data_cell` — `warnings.catch_warnings(record=True)` around `arr.astype(np.float32)`; surfaces a "Overflow: values exceed float32 range" status warning if numpy emits a RuntimeWarning.

---

### BUG-015 — Visibility toggle and style changes trigger full namespace rebuild, causing random cells to re-sample
**Status:** Closed (fixed 2026-05-18)

**Root cause:** `CellWidget._on_visibility_toggled` and `_on_style_changed` both emitted `content_changed` → `_on_cell_changed` → `_rebuild_namespace`, re-evaluating every equation cell. Cells with stochastic expressions (e.g. `random.randn(...)`) produced a new sample on every toggle or color/opacity/size change. Also affected: folder eye toggle called `_rebuild_namespace()` to update equation cell members.

**Fix:** Added `visibility_toggled(str, bool)` and `style_updated(str)` signals to `CellWidget`. Both handlers now emit their dedicated signals instead of `content_changed`. `_rebuild_namespace` caches `cell._last_result` on every equation cell evaluation (mirroring `DataCellWidget`). New handlers `_on_equation_cell_visibility_toggled` and `_on_equation_cell_style_updated` in `CellListWidget` re-apply the cached result directly — no rebuild. `_on_folder_visibility_changed` likewise re-applies cached results for all member cells instead of calling `_rebuild_namespace`.

---

### BUG-019 — Loading a second session merges its scene with the first session's objects
**Status:** Closed (fixed 2026-05-18)  
**Severity:** High

**Root cause:** `add_cell` called `_rebuild_namespace()` immediately when given a non-empty `source`, before `restore_cell_list` could overwrite `cell.cell_id` with the saved ID. The rebuild registered the mesh under a temporary UUID. After `cell_id` was reassigned, the next rebuild registered a second copy under the saved ID. The temp-UUID copy was permanently orphaned — `remove_cell` only knows the saved ID — so it survived into subsequent session loads and merged with their scene.

**Fix:** Added `_skip_rebuild: bool = False` to `CellListWidget` (mirrors `_skip_folder_inference`). `restore_cell_list` sets it `True` before Pass 1, clears it after Pass 2, then calls `_rebuild_namespace()` once with all cells at their final saved IDs. No orphaned objects are produced.

---

### BUG-018 — Opacity setting has no visual effect on surfaces, lines, or scatter
**Status:** Closed (fixed 2026-05-18)  
**Severity:** Medium

**Root cause:** Two compounding failures: (1) `style.opacity` was stored in `CellStyle` but never forwarded to `make_surface_mesh`, `make_line_mesh`, or `make_scatter_mesh` — all three always constructed materials with `opacity=1.0`. (2) Even with opacity forwarded, pygfx's default `alpha_mode="auto"` leaves `depth_write=True`, so a transparent surface writes to the z-buffer and occludes geometry behind it entirely.

**Fix:** Added `opacity: float = 1.0` parameter to all three mesh builders (`renderer.py`). When `opacity < 1.0`, `mat.alpha_mode = "blend"` is set (disables depth write for correct layering). All seven call sites in `app.py:_on_cell_result` now pass `opacity=style.opacity`.

---

### BUG-017 — Multi-line comment cells load at single-line height; content requires scrolling
**Status:** Closed (fixed 2026-05-18)  
**Related:** FEAT-027

**Root cause:** `_CommentEdit._adjust_height()` ran in `__init__` before the widget had a real layout width, so word-wrap produced 1 line and `setFixedHeight` was called with a single-line height. The subsequent `resizeEvent` when the layout assigned the real width did not re-trigger height adjustment.

**Fix:** Override `resizeEvent` on `_CommentEdit` to call `_adjust_height()` on every resize, including the initial layout pass. Override `wheelEvent` to `event.ignore()` so scroll events fall through to the outer panel instead of scrolling inside the cell.

---

### BUG-016 — Scene geometry occluded by circular near-clip artifact when zooming in
**Status:** Closed (fixed 2026-05-18)  
**Severity:** Medium — reproducible with any scene when the camera gets within ~1 world unit of geometry

**Description:**  
Zooming in close to any rendered object causes a circular clipping boundary to appear — geometry inside the boundary vanishes as if blocked by a "spherical collider" centered at the camera. The boundary is the perspective near-clipping plane intersecting the scene; from the viewer's perspective it looks curved/circular due to perspective distortion.

**Reproduction:**  
1. Open `sessions/hello.yml`.  
2. Scroll-zoom into the surface until the camera is within ~1 unit of the geometry.  
3. A circular occlusion boundary appears and grows as you zoom further in.

**Root cause:**  
`gfx.PerspectiveCamera(50)` (no `depth_range` argument) uses pygfx's default `near ≈ 1.07`. Any geometry within 1.07 world units of the camera position is clipped. For a scene with objects in a ±5 unit cube, zooming in to inspect fine detail quickly brings the camera inside the 1.07-unit exclusion zone.

**Fix (`renderer.py:328`):** Pass explicit `depth_range` to the constructor:
```python
self._camera = gfx.PerspectiveCamera(50, depth_range=(0.01, 100_000))
```
`show_object` / `fit_camera` do not reset `depth_range`, so the value persists through camera resets. `near=0.01` allows the camera to approach within 1 cm of geometry before clipping, which is sufficient for all expected use cases.

---

### BUG-006 — Camera moves when toggling cell visibility
**Status:** Closed (fixed 2026-05-18)  
**Description:** Toggling a cell's eye icon off removed its object from `renderer._objects`; toggling back on re-added it with a new `cell_id → is_new=True` check, triggering `fit_camera()`. Fixed by adding `_seen_cell_ids: set[str]` to `PringleViewport`: `add_object` only calls `fit_camera()` on a cell's first-ever render. A `forget_cell(cell_id)` method (wired to `CellListWidget.remove_cell` via the new `on_cell_deleted` callback) removes ids when cells are truly deleted, so genuinely new cells still auto-fit.

---

### BUG-010 — Top view has inconsistent / erratic orbit behavior
**Status:** Closed (fixed 2026-05-18)  
**Description:** Camera at `(0, 0, 12)` placed the view direction exactly parallel to the orbit controller's up vector, causing a cross-product singularity (gimbal lock). Also, manually writing `cam.local.position` left the controller's internal spherical-coordinate cache stale. Fixed in `PringleViewport.set_camera_preset`: top preset shifted to `(0.001, 0, 12)` to avoid the singularity; `controller.target = (0, 0, 0)` added after every preset to re-sync the controller state.

---

### BUG-012 — Opacity and size style settings not persisted in session files
**Status:** Closed (fixed 2026-05-18)  
**Description:** `opacity`, `line_width`, and `point_size` were never written to the YAML style dict in `cell_to_dict`, so reloading a session silently reset them to defaults. Fixed by adding all three fields to the `cell_to_dict` style dict and reading them back in `restore_cell_list` with `get(..., default)` fallbacks for older files.

---

### BUG-011 — Data cells do not auto-run on session load
**Status:** Closed (fixed 2026-05-18)  
**Description:** Data cells were restored with source text but never executed, leaving the viewport empty until the user manually clicked ▷. Fixed in `app.py:_on_open` — after `restore_cell_list` returns, iterate over all `DataCellWidget` instances with non-empty source and call `_run_data_cell` on each.

---

### BUG-008 — False "Undefined" warnings for function-definition cells
**Status:** Closed (fixed 2026-05-16)  
**Description:** Cells calling functions defined with `f(x) = expr` syntax received spurious "Undefined: 'f'" warnings. `dag.py` called `get_store_names` on raw source, which fails to parse that syntax (not valid Python). The fix was to preprocess source through the lambda converter before any AST analysis in `cell_defines` and `cell_uses`.

---

### BUG-007 — Zero-size buffer crash in scatter/line when slider reaches zero
**Status:** Closed (fixed 2026-05-16)  
**Fix:** `make_scatter_mesh` and `make_line_mesh` now return an invisible 1-point placeholder when the input array is empty, matching the existing guard in `make_surface_mesh`.

---

### BUG-002 — Zero-size buffer crash in surface when slider reaches zero
**Status:** Closed (fixed 2026-05-15, commit `ff20120`)  
**Fix:** `make_surface_mesh` returns an invisible placeholder mesh when the clipped index array is empty.

---

### BUG-003 — `KeyboardEvent` has no `.get()` attribute
**Status:** Closed (fixed 2026-05-15, commit `41a40fe`)  
**Fix:** Keyboard handling moved to Qt level; wgpu `_on_key` handler removed entirely.
