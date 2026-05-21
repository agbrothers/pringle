# Pringle — Bug Backlog

Bugs are logged here as they are identified. Each entry includes a description, reproduction steps, root cause analysis, and suggested fixes where known.

See [15-feature-backlog.md](15-feature-backlog.md) for the feature backlog.  
See [16-closed-bugs.md](16-closed-bugs.md) for resolved bugs.

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
**Severity:** CRITICAL — `_clip_mesh_to_mask` is the single largest frame-time bottleneck (170 ms at n=128, 516% of the 33 ms budget) AND produces no visible quality improvement over NaN masking; absorbs PERF-004

**Description:**  
The triangle-clipping patch (`_clip_mesh_to_mask` in `renderer.py`) is not producing visibly smoother edges at the current grid resolution. The staircase pattern remains prominent. At the same time, the function is extremely expensive: it loops over every triangle in Python, making it the dominant bottleneck in the entire rendering pipeline.

The function has two independent defects that must both be fixed:

1. **Quality defect (root cause of jagged edges):** Boundary vertices are placed at the edge midpoint `(A + B) * 0.5` rather than at the true constraint zero-crossing. The midpoint lies on the grid edge but not on the constraint boundary, so the clipped mesh boundary does not follow the constraint curve. The improvement is negligible because the inserted vertex is in the wrong place.

2. **Performance defect (root cause of 170 ms cost):** The function iterates every triangle — all ~32,258 of them at n=128 — in a Python `for tri in indices` loop with per-triangle dict lookups and list appends. The vast majority of triangles are entirely inside or entirely outside the constraint and require no clipping. Only the perimeter triangles (O(n), not O(n²)) actually straddle the boundary.

**Reproduction:**  
Add a constrained surface, e.g. `z = x**2 - y**2` with constraint `x**2 + y**2 < 1`. Rotate to view the boundary edge. Enable profiling or run `python tests/bench_slider_animation.py --n 128` to see the 170 ms cost.

**Measured performance impact (2026-05-19, n=128):**

| Metric | Value |
|--------|-------|
| Mean frame time for `_clip_mesh_to_mask` | **170.2 ms** |
| % of 33 ms frame budget | **516%** |
| Effective frame rate with this bottleneck present | ~4 fps |
| Expected frame rate after fix (estimated) | ~45 fps |

**Root cause — midpoint interpolation:**  
`_bv()` computes the boundary vertex as `(positions[a] + positions[b]) * 0.5`. This midpoint is halfway along the grid edge in 3D space, not at the point where the constraint function crosses zero. For a constraint like `x**2 + y**2 < 1`, the true boundary vertex should be at the point along the edge where `x**2 + y**2 = 1`. The midpoint misses this location by up to half a grid cell width, which is the same order as the staircase artifact being corrected.

**Required fix — implement both corrections together:**

**Step 1 — correct zero-crossing interpolation (quality fix):**  
Replace the midpoint with a linear interpolation along the signed distance to the constraint boundary. If vertex A has constraint value `f_A` and vertex B has `f_B` (signed: positive = inside, negative = outside), the crossing parameter is:

```python
t = f_A / (f_A - f_B)          # t ∈ (0, 1), crossing point fraction along A→B
crossing = A + t * (B - A)     # 3D position on constraint boundary
```

This requires `_clip_mesh_to_mask` to receive the constraint evaluation values (not just the boolean mask) so that `f_A` and `f_B` are available per vertex. The boolean `inside` mask can be derived from `f >= 0`; `f` itself is needed for interpolation.

**Step 2 — numpy vectorized fast-path (performance fix):**  
Classify triangles before entering any loop using boolean array indexing:

```python
inside_count = inside[indices].sum(axis=1)   # shape (T,), values 0–3
all_in  = inside_count == 3   # boolean mask, shape (T,)
all_out = inside_count == 0
boundary = ~all_in & ~all_out   # only ~O(n) triangles at perimeter

# Fast paths — no Python loop:
kept_indices = indices[all_in]   # all-inside triangles pass through unchanged

# Slow path — Python loop only over boundary triangles:
for tri in indices[boundary]:
    ...   # split using linear interpolation
```

At n=128, `boundary` triangles number roughly 4 × 128 = ~512 (perimeter), not 32,258. The Python loop cost drops from O(n²) to O(n).

**Step 3 — function signature change:**  
Change `_clip_mesh_to_mask(positions, indices, normals, inside: bool[])` to accept `f_values: float[]` (the raw constraint evaluation, pre-threshold). Derive `inside = f_values >= 0` inside the function. The call site in `make_surface_mesh` already has the raw z-values and constraint expression available.

**Possible stretch improvements (after the above fix):**
- Adaptive grid refinement near the boundary for even smoother edges.
- Fragment shader alpha fade on boundary triangles (anti-aliased edges without mesh changes).
