# Pringle — Bug Backlog

Bugs are logged here as they are identified. Each entry includes a description, reproduction steps, root cause analysis, and suggested fixes where known.

See [15-feature-backlog.md](15-feature-backlog.md) for the feature backlog.

---

## Open

### BUG-009 — Hard crash (`Abort trap: 6`) when data cell produces NaN or Inf
**Status:** Open  
**Logged:** 2026-05-16  
**Severity:** Critical — process terminates, all unsaved work lost

**Description:**  
When a recursive data cell produces NaN or Inf values (e.g. because a numerical integration diverges at a large time step), the app crashes hard with `Abort trap: 6`. The crash originates in `_fmt_scalar` in `evaluator.py`, which calls `int()` on a NaN float — an operation Python does not allow. The unhandled `ValueError` propagates all the way through the call stack and aborts the process.

**Reproduction:**  
1. Load `sessions/rossler.yml`.
2. Change `dt` from `0.01` to `0.1` (via the slider spinbox or source edit).
3. Press ▷ on the `path = np.zeros((k+1, 3))` data cell.
4. App crashes immediately.

**Full error trace:**
```
/Users/greysonbrothers/code/pringle/pringle/cell_list.py:345: RuntimeWarning: overflow encountered in cast
  result.data = arr.astype(np.float32)
Traceback (most recent call last):
  File ".../cell_list.py", line 357, in _run_data_cell
    self._rebuild_namespace()
  File ".../cell_list.py", line 467, in _rebuild_namespace
    result = self._eval_cell(cell, shared)
  File ".../cell_list.py", line 493, in _eval_cell
    result = run_cell(...)
  File ".../evaluator.py", line 424, in run_cell
    preview = _make_preview(local_ns.get(name))
  File ".../evaluator.py", line 129, in _make_preview
    parts = [_fmt_scalar(x) for x in val]
  File ".../evaluator.py", line 117, in _fmt_scalar
    return str(int(f)) if f == int(f) and abs(f) < 1e15 else f"{f:g}"
ValueError: cannot convert float NaN to integer
Abort trap: 6
```

**Root cause — layered failure with three contributing factors:**

1. **Numerical divergence** (`recurrence.py` / `execute_recurrence`): The Rössler attractor's forward Euler scheme is only stable for `dt ≲ 0.05` with the session's parameters (`a = 0.1, b = 0.1, c = 14`). At `dt = 0.1` with `k = 5000` steps, the integration diverges and the `path` array fills with float64 values that grow without bound.

2. **float32 overflow** (`cell_list.py:345`): After `execute_recurrence` returns, `arr.astype(np.float32)` silently clamps out-of-range float64 values to `inf` (numpy emits a `RuntimeWarning` but execution continues). The resulting `path` array exported to `_data_cell_ns` and `_shared_ns` contains `inf` and, after subsequent arithmetic (e.g. `anim = path[time]` slicing an `inf` row), `NaN`.

3. **`_fmt_scalar` crashes on non-finite floats** (`evaluator.py:117`): The preview system calls `_fmt_scalar` for each element of 1D arrays. The guard `f == int(f)` is evaluated before `int(f)` is called in the return expression — but Python short-circuits `if` conditions left-to-right, and `float('nan') == int(float('nan'))` itself raises `ValueError: cannot convert float NaN to integer`. The exception is caught nowhere in the stack, propagating through `_make_preview → run_cell → _eval_cell → _rebuild_namespace → _run_data_cell` until the process aborts.

**Possible fixes:**

- **Immediate / minimal fix** (`evaluator.py:117`): Guard `_fmt_scalar` against non-finite values before any integer conversion:
  ```python
  def _fmt_scalar(x) -> str:
      f = float(x)
      if not math.isfinite(f):
          return str(f)          # yields "nan", "inf", "-inf"
      return str(int(f)) if f == int(f) and abs(f) < 1e15 else f"{f:g}"
  ```
  Import `math` at the top of `evaluator.py`. This is a one-line fix that prevents the crash and renders non-finite values legibly in the preview.

- **Defense in depth** (`evaluator.py` — `_make_preview` or the preview block in `run_cell`): Wrap the entire preview-generation block in `try/except Exception` so any unexpected formatting error degrades to `None` (no preview shown) rather than propagating. The preview is cosmetic — it should never crash the app.

- **Surface overflow as a cell warning** (`cell_list.py:~345`): Detect the numpy overflow before it silently corrupts downstream state. Use `np.errstate` or `warnings.catch_warnings` around the `astype(np.float32)` call; if overflow is detected, set the cell status to a warning ("Overflow: values exceed float32 range — integration may have diverged") and optionally skip the `_rebuild_namespace` call. This gives the user actionable feedback.

- **Longer-term**: Evaluate whether the float32 cast at `cell_list.py:345` is actually necessary for the render pipeline, or whether float64 arrays could be passed through to avoid lossy downcasting for large-valued simulations.

---

### BUG-014 — `RuntimeError: CallerHelper has been deleted` on app close
**Status:** Open  
**Logged:** 2026-05-18  
**Severity:** Low — app has already exited cleanly; error is printed to stderr only, no data loss

**Description:**  
Closing the application after a normal session (save → close) sometimes prints a `RuntimeError` traceback to stderr:

```
Exception ignored from cffi callback <function GPUBuffer.map_async.<locals>.buffer_map_callback ...>
...
RuntimeError: wrapped C/C++ object of type CallerHelper has been deleted
```

The error appears to be reproducible after toggling visibility controls (axes, crosshair) before closing, though the toggle operations themselves are likely incidental — any close after a rendered frame can trigger it (see root cause below).

**Full trace:**
```
Exception ignored from cffi callback GPUBuffer.map_async.<locals>.buffer_map_callback:
  wgpu/backends/wgpu_native/_api.py — buffer_map_callback
    promise._wgpu_set_input(status)
  wgpu/_async.py — _wgpu_set_input / _set_input / _set_pending_resolved
    self._call_soon_threadsafe(self._resolve_callback)
  rendercanvas/core/loop.py — call_soon_threadsafe
    self._rc_call_soon_threadsafe(wrapper)
  rendercanvas/qt.py — _rc_call_soon_threadsafe
    self._caller.call.emit(callback)
RuntimeError: wrapped C/C++ object of type CallerHelper has been deleted
```

**Root cause — shutdown ordering race between Qt object teardown and a pending GPU async callback:**

rendercanvas uses a small Qt helper object (`CallerHelper`, `rendercanvas/qt.py:192`) to safely marshal callbacks from the GPU driver thread back to the Qt main thread. It works by emitting a Qt signal: `self._caller.call.emit(callback)`.

The render pipeline initiates an async GPU buffer read (`map_async("READ_NOSYNC")`) every frame as part of texture presentation (`rendercanvas/contexts/wgpucontext.py:389`). This operation is asynchronous — the GPU driver calls back when it's done, from a background thread.

When the app closes:
1. Qt's `aboutToQuit` fires → rendercanvas `QtLoop.stop(force=True)` is called, stopping the event loop.
2. Qt proceeds to destroy all `QObject`s, including `CallerHelper`.
3. The pending `map_async` GPU callback from the last rendered frame fires from the wgpu-native background thread.
4. The callback chain reaches `self._caller.call.emit(callback)` — but `_caller` (a `CallerHelper` `QObject`) has already been deleted by Qt.
5. Shiboken (PyQt6's C++ binding layer) raises `RuntimeError: wrapped C/C++ object of type CallerHelper has been deleted`.

The toggle operations before closing are **not the cause** — they just happen to be what the user did before closing. Any close sequence following a render will have this pending callback in flight.

**Why it's "Exception ignored":** The error originates in a cffi callback registered with the wgpu-native C library. Python can't propagate exceptions out of cffi callbacks, so it prints the traceback and continues — hence "Exception ignored." The app has already exited cleanly by this point.

**Possible fixes:**

- **Flush pending GPU work in `closeEvent`** (simplest workaround, `app.py`): Override `closeEvent` on `PringleWindow` to call `QApplication.processEvents()` before the default close, giving any queued callbacks a chance to fire while `CallerHelper` is still alive:
  ```python
  def closeEvent(self, event: QCloseEvent) -> None:
      QApplication.processEvents()   # drain pending GPU callbacks
      super().closeEvent(event)
  ```
  This is a best-effort workaround and may not be reliable under all timing conditions.

- **Upstream fix in rendercanvas**: The correct fix is for rendercanvas's `QtLoop` to either (a) cancel/discard the pending `map_async` awaitable when `stop(force=True)` is called, or (b) keep `CallerHelper` alive (via `QApplication.instance()` ownership) until all pending async callbacks have resolved. This warrants filing a bug report upstream against [rendercanvas](https://github.com/pygfx/rendercanvas).

- **Suppress the noise**: Wrap the cffi callback path with a `try/except RuntimeError` inside rendercanvas. Since the error is already "ignored," this would simply silence the stderr output. Again an upstream fix, not something we can do from application code.

---

### BUG-013 — Camera locks and crosshair drifts when panning and rotating simultaneously
**Status:** Open  
**Logged:** 2026-05-17

**Description:**  
Holding a WASD pan key while dragging the mouse to orbit causes two visible problems: (1) the camera view freezes in place — WASD movement appears to have no effect — and (2) the crosshair continues drifting across the scene independently of the camera. When the mouse button is released and a pan key is pressed again, the camera jumps to an unexpected position.

**Root cause:**  
Two update paths write `camera.local.position` without coordination:

- **WASD pan** (`_pan_target` in `renderer.py:305`): each `_tick` call reads `controller.target` and `camera.local.position`, adds a delta to both, and writes them back. This keeps the camera-to-target offset constant.

- **Mouse orbit** (`gfx.OrbitController`, registered via `register_events`): while a mouse button is held and the user drags, the controller receives mouse-move events and recomputes `camera.local.position` from its internally cached spherical coordinates (elevation, azimuth, distance from target) that were captured at drag start. Every mouse-move event overwrites `camera.local.position` with a value derived from that internal state.

When both are active simultaneously:
1. `_pan_target` shifts `controller.target` successfully (the controller does not cache the target internally during drag — it reads it fresh).
2. `_pan_target` also writes `camera.local.position`, but the next mouse-move event from the `OrbitController` immediately overwrites it using the stale spherical-coordinate cache. The camera appears frozen.
3. Because `controller.target` is being shifted by `_pan_target` each tick, the crosshair (drawn at `controller.target` every frame in `render()`) moves — but the camera does not follow, causing visual decoupling.
4. When the drag ends, the controller stops overwriting `camera.local.position`. The next keypress then applies movement relative to a `controller.target` that has already drifted by the accumulated WASD delta — producing a jump.

**Can rotate and pan simultaneously be achieved?**  
Not without modifying or replacing the `OrbitController`. Its spherical-coordinate cache is internal and inaccessible, so there is no way to inject a "shift the orbit origin mid-drag" operation without the controller immediately undoing it on the next mouse-move event. True simultaneous orbit+pan would require either subclassing `OrbitController` to expose its internal state or replacing it with a custom controller (larger refactor).

**Possible fixes, in order of complexity:**

- **Suppress WASD movement during mouse drag** (recommended short-term fix): Track mouse-button-held state by overriding `mousePressEvent` / `mouseReleaseEvent` on `PringleViewport` (the Qt canvas widget). In `_tick`, skip `_apply_movement` when a mouse button is held. This prevents both the camera lock (no conflicting writes) and the crosshair drift (target is not shifted during drag). WASD and orbit still work individually. The downside is no simultaneous pan+rotate, but the controls are at least predictable.

  ```python
  # PringleViewport
  def mousePressEvent(self, event):
      self._mouse_held = True
      super().mousePressEvent(event)

  def mouseReleaseEvent(self, event):
      self._mouse_held = False
      super().mouseReleaseEvent(event)

  def _tick(self):
      if self._held_keys and not self._mouse_held:
          self._apply_movement()
      self.request_draw()
  ```

- **Freeze crosshair only, don't fix drift** (cosmetic only): Skip the crosshair position update in `render()` when `_mouse_held` is True. The underlying target drift still occurs and the jump-on-release remains, but the visual decoupling is hidden. Not recommended on its own.

- **Full simultaneous pan+rotate** (larger refactor): Replace `gfx.OrbitController` with a custom controller that handles both mouse orbit and keyboard pan in a single unified update loop with no internal caching. This is the video-game-style approach and gives the best UX, but is a significant change to the navigation architecture.

---




### BUG-001 — Constraint edge clipping still jagged
**Status:** Open  
**Logged:** 2026-05-15

**Description:**  
The triangle-clipping patch (`_clip_mesh_to_mask` in `renderer.py`) is not producing visibly smoother edges at the current grid resolution. The staircase pattern remains prominent.

**Reproduction:**  
Add a constrained surface, e.g. `z = x**2 - y**2` with constraint `x**2 + y**2 < 1`. Rotate to view the boundary edge.

**Hypothesis / investigation needed:**  
- The clipping logic may be correct but the grid step size is too coarse for the improvement to be visible.
- Or: clipped boundary vertices are not being interpolated correctly along the true constraint boundary.
- Or: the midpoint interpolation in `_bv()` does not move the vertex to the actual constraint boundary.

**Possible approaches:**  
- Compute the exact zero-crossing position along each boundary edge rather than the midpoint (linear interpolation on the signed distance).
- Adaptive grid refinement near the boundary.
- Smoothing at the shader/material level (anti-aliased edges via alpha).

---

## Closed

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
