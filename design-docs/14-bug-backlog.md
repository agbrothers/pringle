# Pringle — Bug Backlog

Bugs are logged here as they are identified. Each entry includes a description, reproduction steps, root cause analysis, and suggested fixes where known.

See [15-feature-backlog.md](15-feature-backlog.md) for the feature backlog.  
See [16-closed-bugs.md](16-closed-bugs.md) for resolved bugs.

---

### BUG-035 — `ConstraintSubCell` class handles 4 sub-types but is named for one; `hasattr` guards in `_eval_cell` are unreachable dead code

**Status:** Closed (fixed 2026-05-22)  
**Logged:** 2026-05-22  
**Severity:** Low — cosmetic/structural; no runtime impact

**Description:**  
Two naming/clarity issues in the expression cell implementation that accumulated during the DataCellWidget migration:

**1. `ConstraintSubCell` (cell_widget.py:91) name does not match responsibilities.**  
The class handles four sub-types: `constraint`, `condition`, `initial_condition`, and `recursion`. The name `ConstraintSubCell` reflects only the first sub-type. Downstream, `_sub_cells: list[ConstraintSubCell]` and method signatures like `_remove_sub_cell(sub: ConstraintSubCell)` imply a homogeneous constraint-only list, hiding the fact that the list may contain recursion rules or initial conditions. Rename to `SubCell` or `ExprSubCell` for accuracy.

**2. `hasattr` guards in `_eval_cell` (cell_list.py:534) are unreachable.**  
Every call to `constraint_exprs`, `condition_exprs`, `recurrence_expr`, `initial_condition_exprs`, `set_preview`, and `set_data_mode` is wrapped in `hasattr(cell, ...)`. In the actual control flow, `_eval_cell` only ever receives `CellWidget` instances — sliders `continue` before reaching it, and folders/comments are filtered from `evaluable` before the DAG run. The guards imply a heterogeneous type that does not exist and make the method harder to read.

**Fix:**  
Rename `ConstraintSubCell` → `SubCell` (global search-replace across `cell_widget.py`, `session.py`, and tests). Remove the `hasattr` wrappers in `_eval_cell` and replace with direct method calls.

---

### BUG-034 — `_eval_cell` can spawn a blocking `QMessageBox` dialog mid-rebuild

**Status:** Open  
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
def add_sub_cell(self, sub_type: str = "constraint") -> ConstraintSubCell:
    sub = ConstraintSubCell(sub_type=sub_type, parent=self)
    if self._data_mode:
        sub.content_changed.connect(self._mark_data_stale)
    else:
        sub.content_changed.connect(self._on_text_changed)
    ...
```

---

### BUG-032 — `test_phase10` tests use stale 4-arg `_on_bounds_changed` signature; current impl takes 6 args

**Status:** Closed (fixed 2026-05-22)  
**Logged:** 2026-05-22  
**Severity:** Low — test failures only; no runtime impact on users

**Description:**  
5 tests in `tests/test_phase10.py` fail because they call `win._on_bounds_changed(x_min, x_max, y_min, y_max)` with 4 positional arguments, and unpack `bounds_changed` signal tuples as 4-tuples. The current implementation (app.py:639 and ViewSettingsWidget.bounds_changed signal) uses a 6-argument form that adds `z_min` and `z_max`.

The mismatch is pre-existing from a prior bounds-widget expansion and was not caught when z-bounds were added. The docstring in `view_settings.py:6` still says `bounds_changed(x_min, x_max, y_min, y_max)` (4 args) while the `pyqtSignal` on line 28 is `pyqtSignal(float, float, float, float, float, float)` (6 args).

**Failing tests:**  
- `TestViewSettingsWidget::test_bounds_changed_signal_on_apply`  
- `TestPringleWindowViewSettings::test_bounds_change_updates_grid`  
- `TestPringleWindowViewSettings::test_bounds_preserves_resolution`  
- `TestPringleWindowViewSettings::test_resolution_preserves_bounds`  
- `TestPringleWindowViewSettings::test_bounds_change_triggers_cell_reevaluation`

**Fix:**  
Update the 5 failing tests to call `_on_bounds_changed` with 6 args and unpack received signals as 6-tuples. Also fix the stale docstring in `view_settings.py`.

---

### BUG-031 — RNG seeding breaks CellWidget data-mode → run button (always produces same draws)
**Status:** Closed (fixed 2026-05-22)  
**Logged:** 2026-05-22  
**Severity:** High — user's manual re-sample action has no effect

**Description:**  
After the BUG-029 RNG state fix, clicking the `→` button on a data-mode `CellWidget` (e.g., `M = random.random((10, 2)) * 6 - 3`) no longer produces new random draws. The scene does not update at all for random expressions. The intent of the → button is to let the user explicitly re-sample; the RNG fix inadvertently made all equation cells deterministic with no escape hatch.

**Root cause:**  
`_on_run_requested` ([cell_list.py](../pringle/cell_list.py)) calls `_rebuild_namespace()`. The RNG fix inside `_rebuild_namespace` restores `cell._rng_state` before every equation cell eval — including the cell the user just clicked →on. So the re-eval produces the same draws as before, making → a no-op for random cells.

**Fix:**  
In `_on_run_requested`, clear `_rng_state` on the specific cell **before** calling `_rebuild_namespace()`. This allows that cell's next eval to capture the current MT position (producing new draws) while all other cells retain their saved states:

```python
def _on_run_requested(self, cell_id: str) -> None:
    idx = self._index_of(cell_id)
    if idx >= 0:
        self._cells[idx]._rng_state = None   # force fresh draws on explicit re-run
    self._rebuild_namespace()
```

---

### BUG-030 — `DataCellWidget` is a zombie class; architecture docs describe old design
**Status:** Closed (fixed 2026-05-22)  
**Logged:** 2026-05-22  
**Severity:** Medium — no runtime failure, but the code/docs mismatch creates confusion and leaves dead code in the codebase

**Description:**  
`CellWidget` now has a full `data_mode` that replicates the original role of `DataCellWidget` — stale indicator, `→` run button, sub-cell menu offering `recursion` / `initial_condition`, and render-mode style options. The `+ Data cell` UI button was removed. Despite this, `DataCellWidget` remains as a live class, reachable only via `restore_cell_list` when loading YAML files with `type: data`. The `_data_cell_ns` dict, `_run_data_cell`, `_on_data_cell_*` handlers, and `add_data_cell()` all still exist in `cell_list.py` but are never triggered from the UI.

**Affected files:**  
- `pringle/data_cell_widget.py` — zombie class  
- `pringle/data_panel.py` — also appears to be dead (references old data panel widget)  
- `pringle/cell_list.py` — `add_data_cell`, `_run_data_cell`, `_on_data_cell_visibility_toggled`, `_on_data_cell_render_mode_changed`, `_data_cell_ns`  
- `pringle/session.py` — `restore_cell_list` still creates `DataCellWidget` instances for `type: data` YAML  
- `pringle/app.py` — `_on_open` auto-run loop still targets `DataCellWidget` instances  

**Design doc inaccuracies (multiple docs still describe the old architecture):**  
- `design-docs/06-panel-architecture.md`: ASCII diagram lists `[data cells]` as a distinct type; "Data Cells" section describes the old per-cell run chain; boot sequence refers to `DataCellWidget` auto-run; Cell State table includes `data` as a valid `type`  
- `design-docs/07-cell-types-and-blocks.md` (line 184): "Data cells are added via `+ Data cell`" — button no longer exists  
- `design-docs/11-recurrence-relations.md` (line 5): "live in the data panel" — inaccurate  
- `design-docs/12-user-input-and-interaction.md`: "Run All button", "Cell type label chip" — neither exists  
- `design-docs/14-bug-backlog.md` (BUG-029): framed as a `DataCellWidget` bug, but the actual manifestation was on a data-mode `CellWidget`  

**Remaining behavioral differences between the two paths (relevant to migration decision):**  

| Aspect | `CellWidget` data mode | `DataCellWidget` |
|---|---|---|
| → click triggers | `_rebuild_namespace()` (all eq cells) | `_run_data_cell()` (this cell only) |
| Namespace | Regular `shared` dict from eq eval pass | Separate `_data_cell_ns` (persists between rebuilds) |
| AST safety check | Enforced | Bypassed (`is_data_cell=True`) |
| `np` full alias | Not available | Available |
| Auto-updates with sliders | Yes (re-runs in every rebuild) | No (stale until user clicks →) |

**Migration plan (pending decision):**  
1. For each `type: data` entry in existing YAML sessions: migrate to `type: equation` and verify the source is compatible with `build_equation_namespace()` (no bare `import`, no `np.*` calls outside the whitelist)  
2. Remove `DataCellWidget`, `data_panel.py`, `add_data_cell`, `_run_data_cell`, `_data_cell_ns`, `_on_data_cell_*` from `cell_list.py`  
3. Remove `DataCellWidget` branch from `session.py:cell_to_dict` and `restore_cell_list`  
4. Remove `DataCellWidget` auto-run loop from `app.py:_on_open`  
5. Update all five design docs listed above  

---

### BUG-029 — Session load and passive rebuilds re-sample random equation cells
**Status:** Closed (fixed 2026-05-21)  
**Logged:** 2026-05-20  
**Severity:** Medium — data loss from user's perspective; no crash, but the scene changes on every slider drag and every load

**Description:**  
When an equation cell contains a random sampling expression (e.g. `M = random.random((10, 2)) * 6 - 3`), the sampled array changes on every passive rebuild (slider drag, upstream edit) and on every session reload. This makes it impossible to build a stable scene around a particular random sample.

**Root cause — no RNG state pinning in `_rebuild_namespace`:**  
`_rebuild_namespace` re-evaluates all equation cells in DAG order. Each cell draws fresh random values from numpy's global MT19937 RNG at whatever position the MT is at that moment — which varies with every slider tick. On session load, `restore_cell_list` called `_rebuild_namespace` with no saved RNG context, producing a new sample on every open.

**What randomness is accessible in cells:**  
`random` in the cell namespace is `numpy.random`. All sampling functions (`random.random`, `random.randn`, `random.choice`, etc.) and scipy distributions draw from numpy's global MT19937 RNG. This makes global-state snapshotting effective for the vast majority of realistic usage. The only gap is `np.random.default_rng()`, which creates an independent PCG64 generator not affected by `np.random.set_state()`.

**Fix — per-cell RNG state snapshot inside `_rebuild_namespace`:**  
Before each equation cell's `_eval_cell` call, capture or restore the MT19937 state:
- **First eval** (no `_rng_state` on cell): snapshot current MT state into `cell._rng_state`
- **Subsequent evals** (saved state exists): restore that state before evaluating → same draws every time
- **Explicit `→` click** (`_on_run_requested`): clears `cell._rng_state = None` before calling `_rebuild_namespace` → next eval captures a fresh MT position → new random sample

The full 5-tuple state `('MT19937', uint32[624], pos, has_gauss, gauss_val)` is captured so that `randn`-style calls (which internally cache a Gaussian deviate) also reproduce correctly.

**Session persistence:**  
`cell_to_dict` serializes `rng_state` (624-element uint32 list), `rng_pos`, `rng_has_gauss`, and `rng_gauss` for any cell that has a pinned state. `restore_cell_list` stashes these into `cell._pending_rng_state`; the next `_rebuild_namespace` call promotes the pending state to `_rng_state` before evaluating.

**Implementation touchpoints:**

| File | Change |
|---|---|
| `cell_list.py:_rebuild_namespace` | Save/restore `_rng_state` before each equation cell eval; promote `_pending_rng_state` if present |
| `cell_list.py:_on_run_requested` | Clear `_rng_state = None` on target cell before `_rebuild_namespace` to force fresh draws |
| `session.py:cell_to_dict` | Serialize `rng_state` + `rng_pos` + `rng_has_gauss` + `rng_gauss` for cells that have a pinned state |
| `session.py:restore_cell_list` | Stash deserialized state into `cell._pending_rng_state` for all cell types |

**Known limitation:** `np.random.default_rng()` creates an independent PCG64 generator; `set_state` has no effect on it. Cells using `default_rng()` would produce different samples on each rebuild. Uncommon in practice.

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

