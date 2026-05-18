# Pringle — Closed Bugs

Bugs that have been resolved. Entries are preserved here for historical reference.

See [14-bug-backlog.md](14-bug-backlog.md) for open bugs.

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
