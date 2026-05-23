# Pringle — Closed Bugs

Bugs that have been resolved. Entries are preserved here for historical reference.

See [14-bug-backlog.md](14-bug-backlog.md) for open bugs.

---

### BUG-044 — Constant values outside default slider range do not morph to slider
**Status:** Closed (fixed 2026-05-23)

**Root cause:** `is_slider_cell` in `preprocess.py` checked `isinstance(node.value, ast.Constant)`, but negative literals like `a = -3` are parsed as `UnaryOp(USub, Constant(3))` — not a `Constant` — so the check returned `False` and the morph was silently skipped. (`a = 15` worked because positive literals parse directly as `Constant(15)`; range expansion for out-of-range positives was already handled in the `SliderWidget` constructor.)

**Fix:** In `is_slider_cell`, unwrap a leading `UnaryOp(USub, ...)` before the `Constant` check and negate the value. The `SliderWidget` constructor's existing range expansion (`value * 2` if out of bounds) handles the range correctly once the value reaches it.

**Tests:** `tests/test_bug044.py` — `TestIsSliderCellNegative` (5 cases) and `TestSliderMorphOutOfRange` (4 cases).

---

### BUG-043 — Slider morph fires eagerly on every keystroke instead of on Enter/focus loss
**Status:** Closed (fixed 2026-05-23)

**Root cause:** `_on_cell_changed` called `_maybe_morph_to_slider` on every `content_changed` event (every keystroke), so typing `a = 5` immediately snapped the cell to a `SliderWidget` mid-edit.

**Fix:** Added `commit_requested = pyqtSignal(str)` to `CellWidget`, wired to `_text_edit.focus_lost` (already emitted from `CellTextEdit.focusOutEvent`). In `CellListWidget.add_cell`, connected `cell.commit_requested` → `_maybe_morph_to_slider`. Removed `_maybe_morph_to_slider` from `_on_cell_changed` — namespace rebuild (`_rebuild_namespace`) still fires on every keystroke for live evaluation; only the morph is deferred.

**Tests:** `tests/test_bug043.py` — `test_typing_scalar_does_not_morph_mid_edit`, `test_focus_out_morphs_to_slider`, `test_clear_before_commit_prevents_morph`.

---

### BUG-039 (crosshair) — Zooming disconnects camera from crosshair after WASD panning
**Status:** Closed (fixed 2026-05-23)

**Root cause:** `_pan_target` in `renderer.py` called `self._controller.target = new_target` (which internally calls `camera.look_at(new_target)`) before updating `self._camera.local.position`. Because `look_at` reads the camera's current world position at call time, it computed the look direction from the OLD camera position toward the new (shifted) target — introducing a small tilt per step. After many WASD frames the tilt accumulated into a visible misalignment: the camera no longer pointed exactly at the orbit target, so the crosshair (at the target in world space) projected slightly off screen-center. The effect was most noticeable after zooming (zoom moves the camera without correcting orientation).

**Fix:** In `renderer.py:_pan_target`, moved `self._camera.local.position = cam_pos + delta` to execute BEFORE `self._controller.target = new_target`. With the camera already at its new position, `look_at` computes the correct direction (`new_target − new_cam_pos = old_target − old_cam_pos`, unchanged), preventing any per-step drift.

**Tests:** `tests/test_bug039.py` — `test_pan_target_no_drift` (fixed impl: <0.001° after 120 steps), `test_pan_target_buggy_drifts` (old impl: >0.1° confirms regression coverage).

---

### BUG-039 — Typing in comment cells triggers a full namespace rebuild on every keystroke
**Status:** Closed (fixed 2026-05-22)

**Fix (Option A):** In `CellListWidget.add_comment_cell` and `_maybe_morph_to_comment`, changed `comment.content_changed.connect(self._on_cell_changed)` to `comment.content_changed.connect(self._on_comment_changed)`. Added `_on_comment_changed` as a no-op — comment edits don't affect the namespace or any render output. Equation cell edits are unaffected.

**Tests:** `tests/test_phase4_5.py::TestCommentCellNoRebuild` — `test_comment_edit_does_not_rebuild`, `test_morphed_comment_does_not_rebuild`, `test_equation_cell_still_rebuilds`.

---

### BUG-013 — Camera locks and crosshair drifts when panning and rotating simultaneously
**Status:** Closed (fixed 2026-05-22)

**Fix:** Replaced `gfx.OrbitController.register_events()` with a custom `_IncrementalOrbitHandler` in `renderer.py`. The stock event system snapshots the camera state at drag-start and recomputes the full camera position from that snapshot on every `pointer_move`, immediately discarding any WASD delta. The new handler calls `controller.rotate()` / `.pan()` / `.zoom()` with the incremental pixel delta since the *previous* event, so the controller always reads the live camera state. WASD and mouse orbit now run simultaneously without conflict. See `renderer.py:_IncrementalOrbitHandler` and `test_phase10.py::TestSimultaneousPanOrbit`.

---

### BUG-036 — `_EvalWorker` C++ object deleted before eval thread stops on close
**Status:** Closed (fixed 2026-05-22)

**Fix:** Added `CellListWidget.shutdown()` that calls `_eval_thread.quit()` + `wait(3000)`. `PringleWindow.closeEvent` now calls `self._cell_list.shutdown()` as the first action before `processEvents()` and `super().closeEvent()`. The racy `self.destroyed` lambda (which fired after Qt had already started destroying widgets) was removed. See [cell_list.py](../pringle/cell_list.py) and [app.py](../pringle/app.py).

---

### BUG-033 — Sub-cells in data mode trigger full rebuild on every keystroke
**Status:** Closed (fixed 2026-05-22)

**Fix:** Two changes in `cell_widget.py`: (1) `add_sub_cell` now checks `self._data_mode` and connects `sub.content_changed` to `_mark_data_stale` instead of `_on_text_changed` when in data mode. (2) `set_data_mode` now swaps the signal connection for all already-attached sub-cells alongside the existing `_text_edit` swap. Four regression tests added in `test_phase8.py::TestSubCellDataModeSignals`.

---

### BUG-034 — `_eval_cell` blocked by `QMessageBox` during passive mode transition
**Status:** Closed (fixed 2026-05-22)

**Fix:** Added `force: bool = False` parameter to `set_data_mode` (cell_widget.py). When `force=False` (the default, used by `_eval_cell`), incompatible sub-cells are silently removed with no dialog. The confirmation dialog is only shown when `force=True`, reserved for explicit future user-initiated calls. Added four regression tests in `test_phase8.py::TestSetDataMode`.

---

### BUG-032 — `test_phase10` tests use stale 4-arg `_on_bounds_changed` signature
**Status:** Closed (fixed 2026-05-22)

**Fix:** Updated the 5 failing tests to call `_on_bounds_changed` with 6 args (`x_min, x_max, y_min, y_max, z_min, z_max`) and unpack the `bounds_changed` signal as a 6-tuple. Fixed the stale docstring in `view_settings.py` line 6 to match the 6-arg `pyqtSignal`.

---

### BUG-035 — `ConstraintSubCell` renamed to `SubCell`; `hasattr` guards removed from `_eval_cell`
**Status:** Closed (fixed 2026-05-22)

**Fix:** Renamed `ConstraintSubCell` → `SubCell` across `cell_widget.py` and `tests/test_phase8.py`. Removed the six `hasattr` guards in `_eval_cell` (`cell_list.py`) and replaced with direct method calls, reflecting that `_eval_cell` only ever receives `CellWidget` instances.

---

### BUG-031 — RNG seeding breaks CellWidget data-mode → run button
**Status:** Closed (fixed 2026-05-22)

**Root cause:** `_on_run_requested` called `_rebuild_namespace()`, which restored `cell._rng_state` for every equation cell including the target — making `→` a no-op for random cells.

**Fix:** In `_on_run_requested`, clear `self._cells[idx]._rng_state = None` on the target cell before calling `_rebuild_namespace()`. That cell then captures a fresh MT position (new draws); all other cells retain their pinned state.

---

### BUG-030 — `DataCellWidget` zombie class and stale architecture docs
**Status:** Closed (fixed 2026-05-22)

**Root cause:** The equation cell / data cell merge happened at the UI level (no `+ Data cell` button; `CellWidget` gained `data_mode`) but the old code paths were never removed. `DataCellWidget`, `data_panel.py`, `add_data_cell`, `_run_data_cell`, `_data_cell_ns`, and `_on_data_cell_*` remained as dead code reachable only via loading old YAML files with `type: data`.

**Fix:**
- Migrated `examples/lorenz.yml` and `examples/rossler.yml`: `type: data` → `type: equation`, `np.zeros(...)` → `zeros(...)`
- Deleted `pringle/data_cell_widget.py` and `pringle/data_panel.py`
- Removed `add_data_cell`, `_run_data_cell`, `_data_cell_ns`, `_on_data_cell_visibility_toggled`, `_on_data_cell_render_mode_changed` from `cell_list.py`
- Removed `DataCellWidget` branch from `session.py:cell_to_dict`; `restore_cell_list` now routes old `type: data` YAML entries through `add_cell` (equation path) with `cell_type in ("equation", "data")` handling for sub-cells and RNG state
- Removed `DataCellWidget` auto-run loop from `app.py:_on_open`
- Updated `06-panel-architecture.md`, `07-cell-types-and-blocks.md`, `11-recurrence-relations.md`, `12-user-input-and-interaction.md`, and BUG-029 description in `14-bug-backlog.md`

---

### BUG-014 — `RuntimeError: CallerHelper has been deleted` on app close
**Status:** Closed (fixed 2026-05-21)  
**Severity:** Low — stderr noise only; app has already exited cleanly, no data loss

**Root cause:** Shutdown ordering race between Qt object teardown and a pending GPU async callback. rendercanvas's `CallerHelper` (`QObject`) is destroyed when Qt tears down `QObject`s after `aboutToQuit`. The render pipeline issues `map_async("READ_NOSYNC")` every frame; the wgpu-native background thread fires its callback after `CallerHelper` is already deleted, so Shiboken raises `RuntimeError`. The error is caught and printed as "Exception ignored" — the app is already gone.

**Fix:** Added `closeEvent` to `PringleWindow` (`app.py`):
```python
def closeEvent(self, event) -> None:
    QApplication.processEvents()
    super().closeEvent(event)
```
`processEvents()` drains queued `map_async` callbacks before Qt destroys `QObjects`, eliminating the race in the common case.

---

### BUG-026 — `error messaging the mach port for IMKCFRunLoopWakeUpReliable` printed on startup
**Status:** Closed (fixed 2026-05-21)  
**Severity:** Low — stderr noise only

**Root cause:** During session restore, each `add_cell`/`add_data_cell`/`add_comment_cell` call unconditionally called `cell.focus()`, giving a `QPlainTextEdit` keyboard focus before Qt's Cocoa event loop integration was fully established. The IMK framework attempted to ping the `CFRunLoop` for the newly focused widget and failed.

**Fix:** Gated all six `cell.focus()` call sites in `cell_list.py` on `not self._skip_rebuild`. Since `restore_cell_list` sets `_skip_rebuild = True` for its entire duration, no text widget receives focus during startup. Interactive `add_cell` calls (user-triggered) still focus the new cell normally.

---

### BUG-023 — Dragging a folder does not move its member cells
**Status:** Closed (fixed 2026-05-21)  
**Severity:** High

**Root cause:** `_move_cell` only popped and re-inserted the `FolderCellWidget` header. The layout rebuild then placed member cells at their previous positions in `_cells` order — unchanged — splitting the folder from its members.

**Fix:** `_move_cell` now branches on `isinstance(cell, FolderCellWidget)`. In the folder branch: collects `block = [folder] + members` (members in `_cells` visual order), pops all block indices in reverse, adjusts `to_idx` by the count of removed cells that preceded it, then inserts the whole block at `insert_at`. No-op detection checks whether `to_idx` falls inside the block's own span. Single-cell move logic is unchanged.

---

### BUG-025 — Drag drop indicator appears inside tall cells; misplaced near hidden cells
**Status:** Closed (fixed 2026-05-21)  
**Severity:** Low — cosmetic

**Root cause:** `_compute_drop_idx` used the cell midpoint (50%) as the snap threshold. For tall cells (200+ px), this placed the indicator deep inside the cell body. Hidden folder members still appeared in `_cells` with stale geometry, registering as valid insertion points at phantom positions.

**Fix:** Two changes to `cell_list.py`:
- `_compute_drop_idx`: skip `not cell.isVisible()` cells; changed threshold from `height // 2` to `height // 4` (25%) so the indicator snaps to a cell boundary after crossing only the top quarter.
- `_position_drop_indicator`: compute `y` using only visible cells — walks backward from `drop_idx` for `prev_bottom` and forward for `next_top`, skipping hidden cells.

---

### BUG-028 — CellTextEdit shows native OS frame border on all equation and data cells
**Status:** Closed (fixed 2026-05-21)  
**Severity:** Low — cosmetic

**Root cause:** `CellTextEdit` (`cell_widget.py`) had no stylesheet or frame override. Qt's default `QPlainTextEdit` draws a native frame (a 1px OS-drawn border) that `border: none` in a stylesheet alone does not remove — on macOS the frame is drawn by the platform style plugin and ignores CSS border declarations.

**Fix:** Added `self.setFrameShape(QFrame.Shape.NoFrame)` (removes the native Qt/OS-drawn frame) and `self.setStyleSheet("QPlainTextEdit { border: none; background: transparent; }")` (removes any painted Qt border) to `CellTextEdit.__init__`. Sub-cell `ConstraintSubCell` overrides this with its own dashed border stylesheet, which is intentional.

---

### BUG-027 — Equation and data cells clip multi-line content on session load
**Status:** Closed (fixed 2026-05-21)  
**Severity:** Medium — long expressions are unreadable after loading a saved session

**Root cause:** `CellTextEdit._adjust_height` connected to `document().contentsChanged`, which fires before Qt's layout engine has reflowed text to the widget's actual width. When cells are restored from a session file and text is set via `setPlainText`, the document size calculation runs at a pre-layout width (often a narrow default), so `setFixedHeight` is set for a single line even when the expression wraps to multiple lines at 480 px. The height was never corrected after the widget reached its final width.

**Fix:** Mirrored the approach used by `_CommentEdit` (which has always displayed correctly):
- Replaced `document().contentsChanged` → `document().documentLayout().documentSizeChanged` signal, which fires *after* text reflow at the actual widget width. Height is computed as `line_count × lineSpacing()` — accurate for wrapped content.
- Added `resizeEvent` override that calls `_adjust_height()` so cells re-expand correctly when the user drags the panel splitter.

---

### BUG-024 — New cell inserted above the active cell instead of below
**Status:** Closed (fixed 2026-05-20)  
**Severity:** Medium

**Root cause:** Off-by-one between `_cells` list index and layout index. The layout has a hidden placeholder at index 0, so `_cells[idx]` lives at layout index `idx + 1`. All four `add_*` methods used `insertWidget(idx + 1, cell)`, which placed the new cell at the focused cell's slot — inserting before it instead of after.

**Fix:** Changed `insertWidget(idx + 1, ...)` → `insertWidget(idx + 2, ...)` in `add_cell`, `add_data_cell`, `add_comment_cell`, and `add_folder` (`cell_list.py`).

---

### BUG-021 — Startup font warning: 174 ms alias scan for missing "Monospace" family
**Status:** Closed (fixed 2026-05-20)  
**Severity:** Low

**Root cause** (`comment_cell_widget.py`): Two stylesheet strings used `font-family: monospace`. Qt treats `monospace` as a literal font family name (not a CSS generic keyword) and scans all installed font families for a match or alias — taking ~174 ms on a large font catalog.

**Fix:** Replaced bare `monospace` with an explicit cross-platform stack: `font-family: 'Menlo', 'Consolas', 'Courier New';`. Qt picks the first available name without triggering an alias scan. `Menlo` is the default monospace font on macOS; `Consolas` on Windows.

---

### BUG-022 — Transparent surface shows triangle mesh artifact where it self-overlaps
**Status:** Closed (fixed 2026-05-20)  
**Severity:** Medium

**Root cause:** `alpha_mode="blend"` draws transparent fragments in mesh-index order. For a self-overlapping surface, back triangles could render after front ones, producing a visible triangle-grid artifact.

**Fix:** Changed `alpha_mode="blend"` → `alpha_mode="weighted_blend"` at all four opacity-guarded sites in `renderer.py` (surface, line, scatter/sphere, degenerate-placeholder paths). WBOIT accumulates weighted color contributions from all fragments at each pixel and normalizes at resolve time — no dependency on triangle draw order.

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
