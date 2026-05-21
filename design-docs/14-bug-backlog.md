# Pringle — Bug Backlog

Bugs are logged here as they are identified. Each entry includes a description, reproduction steps, root cause analysis, and suggested fixes where known.

See [15-feature-backlog.md](15-feature-backlog.md) for the feature backlog.  
See [16-closed-bugs.md](16-closed-bugs.md) for resolved bugs.

---

### BUG-025 — Drag drop indicator appears inside tall data cells; misplaced near hidden cells
**Status:** Open  
**Logged:** 2026-05-20  
**Severity:** Low — cosmetic, but makes drag-and-drop confusing for multi-line cells

**Description:**  
When dragging a cell over a data cell that has expanded to multiple lines (e.g., one with recursion sub-cells), the blue drop indicator line appears in the middle of the data cell rather than at a cell boundary. Additionally, dragging near collapsed folder members (which are hidden) produces erratic indicator placement because hidden widgets report stale geometry values.

**Root cause:**  
`_compute_drop_idx` (`cell_list.py:909`) uses each cell's vertical midpoint as the boundary threshold:
```python
if local_y < geo.top() + geo.height() // 2:
    return i
```
For a standard equation cell (~40px tall), the midpoint at 20px is a reasonable boundary. For a tall data cell (e.g., 200px with three sub-cell rows), the midpoint is at 100px — so the user has to drag 100px into the visible cell before the indicator snaps to "below the previous cell." At any mouse position between the top and midpoint of the data cell, the indicator line appears visually in the middle of the data cell widget.

Hidden member cells of a collapsed folder have their `geometry()` return the position they occupied before being hidden (they are removed from the layout's visible flow but not resized to zero). This causes `_compute_drop_idx` to count hidden cells as real insertion points, placing the indicator at phantom positions and sometimes skipping slots or placing in wrong locations near collapsed folders.

**Fix — `_compute_drop_idx`:**  
Use a smaller threshold fraction (e.g., 25% from the top rather than 50%), and skip hidden cells entirely:
```python
def _compute_drop_idx(self, local_y: int) -> int:
    for i, cell in enumerate(self._cells):
        if not cell.isVisible():
            continue             # skip hidden members of collapsed folders
        geo = cell.geometry()
        if local_y < geo.top() + geo.height() // 4:   # 25% threshold
            return i
    return len(self._cells)
```
A 25% threshold means the indicator snaps to "before cell i" only when the mouse is in the top quarter of cell i — giving a much narrower hot zone and keeping the indicator near the actual cell boundary for tall cells.

**Fix — `_position_drop_indicator`:**  
Similarly, skip hidden cells when computing the indicator Y position so it always snaps to a visible gap between two visible cells.

---


### BUG-023 — Dragging a folder does not move its member cells
**Status:** Open  
**Logged:** 2026-05-20  
**Severity:** High — core folder drag behavior is broken; members scatter or land in wrong folder

**Description:**  
Dragging a folder header to a new position in the panel moves only the folder header widget. Member cells remain at their original positions, appearing as top-level cells or becoming members of whatever folder is now above them. When dragging a **closed** folder, hidden member cells have stale geometry values that cause `_compute_drop_idx` to compute incorrect insertion indices, frequently mixing member cells into adjacent folders.

**Expected behavior (per `01-desmos-3d-overview.md` — Folders section):**  
Dragging a folder moves the entire folder+members block as a unit. Members immediately follow the folder header at the new position, in their original relative order. This holds whether the folder is expanded or collapsed.

**Root cause — `_move_cell` only moves the folder header** (`cell_list.py:933–955`):  
```python
cell = self._cells.pop(from_idx)   # only pops the FolderCellWidget
insert_idx = (to_idx - 1) if to_idx > from_idx else to_idx
self._cells.insert(insert_idx, cell)
# Layout rebuild then places members at their old positions
```
The branch `if not isinstance(cell, FolderCellWidget)` explicitly skips folder cells for membership re-assignment, but there is no code that also moves the member cells. After the pop+insert, the layout rebuild re-inserts ALL cells in `_cells` order — with the folder header in the new position but the member cells unchanged, creating a visual split.

For closed folders, the second issue is that hidden cells still appear in `_cells` and `_compute_drop_idx` queries their `geometry()`. Hidden widgets return their last-known geometry (not zero), so they register as valid insertion targets at phantom positions.

**Fix — `_move_cell`:**  
When the cell being moved is a `FolderCellWidget`, collect its members and move them together:
```python
def _move_cell(self, from_idx: int, to_idx: int) -> None:
    from pringle.folder_cell_widget import FolderCellWidget
    cell = self._cells[from_idx]

    if isinstance(cell, FolderCellWidget):
        # Collect folder + members as a block
        folder_id = cell.cell_id
        members = [c for c in self._cells if self._cell_folder.get(c.cell_id) == folder_id]
        block = [cell] + members   # folder header first, then members in order
        # Remove block from _cells (pop in reverse to preserve indices)
        block_indices = sorted([self._index_of(b.cell_id) for b in block], reverse=True)
        for i in block_indices:
            self._cells.pop(i)
        # Adjust to_idx for the removed items
        removed_before = sum(1 for i in block_indices if i < to_idx)
        insert_at = max(0, to_idx - removed_before)
        for j, b in enumerate(block):
            self._cells.insert(insert_at + j, b)
    else:
        # Original single-cell move logic
        self._cells.pop(from_idx)
        insert_idx = (to_idx - 1) if to_idx > from_idx else to_idx
        self._cells.insert(insert_idx, cell)
        new_folder = self._infer_folder(self._index_of(cell.cell_id))
        if new_folder != self._cell_folder.get(cell.cell_id):
            self._assign_folder(cell, new_folder)

    # Rebuild layout order
    self._container.setUpdatesEnabled(False)
    for c in self._cells:
        self._layout.removeWidget(c)
    for i, c in enumerate(self._cells):
        self._layout.insertWidget(i + 1, c)
    self._container.setUpdatesEnabled(True)
    self._rebuild_namespace()
```

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

