# Pringle — Bug Backlog

Bugs are logged here as they are identified. Each entry includes a description, reproduction steps, root cause analysis, and suggested fixes where known.

See [15-feature-backlog.md](15-feature-backlog.md) for the feature backlog.  
See [16-closed-bugs.md](16-closed-bugs.md) for resolved bugs.

---

### BUG-019 — Loading a second session merges its scene with the first session's objects
**Status:** Open  
**Logged:** 2026-05-18  
**Severity:** High — scene content from a prior session persists and contaminates every subsequent load

**Description:**  
When two session files are opened back to back without restarting the app, the second session's plot appears merged with the first. Surfaces, scatter points, or curves from the first session remain visible alongside the content of the second. There is no visible contamination when only one session is loaded from a cold start.

**Reproduction:**  
1. Launch the app (or start from a clean state).  
2. Open `sessions/sinusoid.yml`. Plots render correctly.  
3. Open `sessions/hello.yml`. The sinusoidal surface from the first session remains visible alongside hello.yml's content.

**Root cause — orphaned renderer objects caused by cell ID reassignment after the initial namespace rebuild:**

`restore_cell_list` (`session.py:184`) follows this sequence for each saved cell:

```
cell = cell_list.add_cell(source=source, style=style)   # (1) cell created with a new temp UUID
if cell_id:
    cell.cell_id = cell_id                              # (2) ID reassigned to the saved ID
for sub_data in data.get("sub_cells", []):              # (3) sub-cells added later
    sub = cell.add_sub_cell(...)
    sub._edit.setText(...)
```

Inside `add_cell` (step 1), when a non-empty `source` is provided, `cell.set_source(source)` is called and then `self._rebuild_namespace()` is called unconditionally (line 258–259 of `cell_list.py`). At this point the cell still has its **temp UUID**. `_rebuild_namespace` evaluates the cell and calls `vp.add_object(TEMP_UUID, mesh)`, storing the rendered mesh in the renderer's `_objects` dict under the temp UUID.

Immediately after `add_cell` returns, `cell.cell_id` is overwritten with the **saved ID** (step 2). Any later event that triggers `_rebuild_namespace` (e.g. a sub-cell `setText` firing `content_changed`, or a subsequent `add_cell` for another cell) re-evaluates this cell under the saved ID and calls `vp.add_object(SAVED_ID, mesh)`.

Now two renderer entries exist for the same cell:
- `TEMP_UUID → mesh` — **orphaned**: no cell in `_cells` has this ID
- `SAVED_ID → mesh` — active

The orphaned entry can never be removed. `remove_cell` and `remove_object` both operate on `SAVED_ID`; `TEMP_UUID` is unknown to them.

When the second session is loaded, `restore_cell_list` removes the first session's cells by saved ID — orphaned temp UUID objects remain in the renderer's `_objects` dict and the pygfx scene. The second session's objects are then added on top, producing the merged visual.

This is not visible on first load because the orphaned duplicate objects sit at exactly the same position as the active ones (same source, same grid) and are indistinguishable.

**Fix:**

Suppress `_rebuild_namespace` during bulk cell restoration using a flag (mirroring the existing `_skip_folder_inference` pattern). After all cells have been added and IDs have been assigned, do a single rebuild:

```python
# session.py — restore_cell_list, before Pass 1 loop:
cell_list._skip_rebuild = True

# ...add all cells, reassign IDs...

# after Pass 2:
cell_list._skip_rebuild = False
cell_list._rebuild_namespace()
```

```python
# cell_list.py — add_cell (lines 243–244 and 258–259), guard the rebuild:
if source:
    if not getattr(self, '_skip_rebuild', False):
        self._rebuild_namespace()
```

This eliminates intermediate rebuilds under temp UUIDs entirely. Every cell is fully constructed with its final saved ID before any rebuild occurs, so no orphaned objects are produced.

**Alternative (targeted) fix:** Pass `cell_id` as a parameter to `add_cell` so the cell's ID can be set before `set_source` and `_rebuild_namespace` are called. This avoids adding a new flag but requires changing `add_cell`'s signature and all call sites.

---


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

### BUG-015 — Visibility toggle triggers full namespace rebuild, causing random cells to re-sample
**Status:** Open  
**Logged:** 2026-05-18  
**Related:** Shares root cause with BUG-006 (see [16-closed-bugs.md](16-closed-bugs.md))

**Description:**  
Toggling the eye icon on any equation cell causes every other equation cell to re-evaluate, including cells that call random functions. Any cell producing a random scatter, random surface, or any other stochastic output visibly re-samples — its geometry changes — even though the user only changed visibility on an unrelated cell.

**Reproduction:**  
1. Add an equation cell: `p = random.randn(200, 3)` (auto-renders as scatter).  
2. Add any other equation cell, e.g. `z = sin(x)`.  
3. Toggle the eye icon on `z = sin(x)`.  
4. The scatter plot for `p` re-renders with a new random sample.

**Root cause:**  
`CellWidget._on_visibility_toggled` (`cell_widget.py:565–570`) updates `_visible`, then emits `content_changed`:

```python
def _on_visibility_toggled(self, checked: bool):
    self._visible = checked
    ...
    self.content_changed.emit(self.cell_id)   # ← triggers full rebuild
```

`content_changed` is connected to `CellListWidget._on_cell_changed` (`cell_list.py:559`), which calls `_rebuild_namespace()`. `_rebuild_namespace` re-evaluates every equation cell in topological order (`cell_list.py:481`). Cells containing random calls (e.g. `random.randn(...)`) produce a new sample on every evaluation, so they re-render with different geometry.

A visibility toggle requires no re-evaluation whatsoever. The existing result for the toggled cell is already cached — showing or hiding it is purely a renderer-side operation (send or withhold the cached result). Every other cell's result should be completely unaffected.

This is the same misrouting as BUG-006: both are caused by visibility toggle incorrectly flowing through `content_changed` → `_on_cell_changed` → `_rebuild_namespace` rather than through a dedicated visibility-only path.

**Fix:**  
`CellWidget` should emit a dedicated `visibility_toggled` signal (as `DataCellWidget` already does) instead of reusing `content_changed`. `CellListWidget` handles it by re-applying only the toggled cell's cached result — no rebuild:

```python
# cell_widget.py — add signal
visibility_toggled = pyqtSignal(str, bool)   # cell_id, is_visible

def _on_visibility_toggled(self, checked: bool):
    self._visible = checked
    ...
    self.visibility_toggled.emit(self.cell_id, checked)  # NOT content_changed
```

```python
# cell_list.py — connect and handle (mirrors _on_data_cell_visibility_toggled)
cell.visibility_toggled.connect(self._on_equation_cell_visibility_toggled)

def _on_equation_cell_visibility_toggled(self, cell_id: str, is_visible: bool) -> None:
    idx = self._index_of(cell_id)
    if idx < 0:
        return
    cell = self._cells[idx]
    last = getattr(cell, "_last_result", None)
    if is_visible and last is not None:
        self._on_cell_result(cell_id, last, cell.style)
    else:
        self._on_cell_result(cell_id, CellResult(), cell.style)
```

This requires equation cells to cache their last result in `_last_result` (as `DataCellWidget` already does) so it can be re-applied without re-evaluation.

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
