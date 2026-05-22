# Pringle — Bug Backlog

Bugs are logged here as they are identified. Each entry includes a description, reproduction steps, root cause analysis, and suggested fixes where known.

See [15-feature-backlog.md](15-feature-backlog.md) for the feature backlog.  
See [16-closed-bugs.md](16-closed-bugs.md) for resolved bugs.

---

### BUG-034 — `_eval_cell` can spawn a blocking `QMessageBox` dialog mid-rebuild

**Status:** Closed (fixed 2026-05-22)  
**Logged:** 2026-05-22  
**Severity:** High — modal dialog can appear during a passive rebuild triggered by a slider drag or upstream edit; blocks the Qt event loop from inside a debounce timeout

**Description:**  
`_eval_cell` (cell_list.py:600) calls `cell.set_data_mode(should_be_data)` when the inferred render type of a cell changes between `scatter` (data-array mode) and surface/other (equation mode). `set_data_mode` (cell_widget.py:504) contains a `QMessageBox.question()` call that fires if the cell has incompatible sub-cells — e.g., a constraint sub-cell on a cell that is switching to data mode.

The result is that a user who:
1. Adds a constraint sub-cell to a cell, then
2. Edits the expression so it now returns an `(N, 3)` array

…will see a blocking modal dialog during the next passive rebuild (triggered by a slider tick or another cell's edit). The dialog appears from inside a debounce `QTimer` callback — a context where UI dialogs are not expected and where the user has no obvious reason why the dialog appeared.

**Root cause:**  
The decision to switch data mode and its UI side effect (dialog, signal rewiring, sub-cell cleanup) are bundled inside a single method called from the evaluation path. Evaluation should be free of UI side effects beyond updating inline labels.

**Fix (two options):**

*Option A — Defer mode-switch via `QTimer.singleShot(0, ...)`.*  
In `_eval_cell`, replace the direct `cell.set_data_mode(should_be_data)` call with a deferred call. The dialog would still appear, but after the current rebuild completes and the event loop returns to an idle state.

```python
should_be_data = result.from_shape_inference and result.render_type in ("scatter", "scatter_2d")
if should_be_data != cell.is_data_mode():
    QTimer.singleShot(0, lambda c=cell, m=should_be_data: c.set_data_mode(m))
```

*Option B — Suppress dialog during passive mode transitions.*  
Add a `force: bool = False` parameter to `set_data_mode`. When `force=False` (called from `_eval_cell`), silently remove incompatible sub-cells without asking. Reserve the confirmation dialog for explicit user actions (e.g., adding a sub-cell that would be incompatible with the current mode).

Option B is the recommended fix — auto-switching data mode is always a passive inference from the return type, not a user-initiated action, so the dialog is always inappropriate in this path.

---

### BUG-033 — Sub-cells in data mode ignore the manual-re-run contract; every keystroke triggers a full rebuild

**Status:** Open  
**Logged:** 2026-05-22  
**Severity:** Medium — typing in a Lorenz recurrence rule triggers a full integration on every debounce tick (300 ms), making the UI sluggish while composing sub-cell expressions

**Description:**  
Data-mode `CellWidget` implements a manual-re-run contract for the main cell: `textChanged` is disconnected from the debounce path and replaced with `focus_lost → _emit_changed`. This means the main expression is only re-evaluated when the user leaves the text field, avoiding repeated expensive integrations while typing.

Sub-cells bypass this contract entirely. `add_sub_cell` always connects `sub.content_changed → self._on_text_changed`, which starts the 300 ms debounce timer and ultimately calls `_rebuild_namespace()` after each debounce tick — even when the parent cell is in data mode. For a Lorenz path with `k=2000`, this means 2000 integration steps fire every ~300 ms while the user types a character in the recursion rule.

**Root cause:**  
`add_sub_cell` (cell_widget.py:471) connects `content_changed` unconditionally regardless of `self._data_mode`. The data-mode signal-swap logic in `set_data_mode` only touches `self._text_edit`; sub-cells are added after mode-switching and always use the eager path.

**Reproduction:**  
1. Open `examples/lorenz.yml` (k=2000 steps)  
2. Click in the recursion rule sub-cell and type any character  
3. Observe ~300 ms stall 300 ms after each keypress (full Lorenz integration fires)

**Fix:**  
In `add_sub_cell`, check `self._data_mode` and connect to `_mark_data_stale` (not `_on_text_changed`) when in data mode, mirroring the main-cell signal swap. Also apply the same swap inside `set_data_mode` for any already-attached sub-cells.

```python
def add_sub_cell(self, sub_type: str = "constraint") -> SubCell:
    sub = SubCell(sub_type=sub_type, parent=self)
    if self._data_mode:
        sub.content_changed.connect(self._mark_data_stale)
    else:
        sub.content_changed.connect(self._on_text_changed)
    ...
```

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
