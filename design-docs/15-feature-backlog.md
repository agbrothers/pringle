# Pringle — Feature Backlog

Desired features and enhancements are logged here as they are identified. Each entry includes a description, motivation, and implementation notes or open questions where known.

See [14-bug-backlog.md](14-bug-backlog.md) for the bug backlog.  
See [17-closed-features.md](17-closed-features.md) for implemented features.

---

### FEAT-051 — Auto-scroll cell list to follow keyboard navigation focus

**Status:** Open  
**Logged:** 2026-05-23

**Description:**  
When the user navigates between cells using the Up/Down arrow keys (cross-cell navigation), the cell panel's scroll bar stays fixed even if the newly focused cell lies outside the visible scroll area. The scroll area should automatically scroll the minimum distance needed to keep the focused cell fully visible — the standard behavior of any scrollable panel that contains focusable inputs.

**Motivation:**  
A session with many cells extends past the visible panel height. Navigating down with the arrow key should feel continuous; having the focused cell disappear below the visible area breaks the editing flow and forces the user to manually scroll.

**Affected navigation paths:**
- Arrow-key cross-cell navigation (`_on_navigate_down`, `_on_navigate_up` in `cell_list.py`)
- `Enter` to add a new cell below and focus it
- `Backspace` on an empty cell (deletes cell, focuses the one above — that cell may be above the viewport if the user was near the bottom)
- Morph operations that replace a widget (slider morph, comment morph) — focus lands on the replacement widget

**Implementation (`cell_list.py`):**

`QScrollArea.ensureWidgetVisible(widget)` scrolls the minimum amount to make `widget` fully visible in the scroll area viewport. It is the correct Qt API for this use case.

**Step 1 — store the scroll area as an instance variable:**

In `CellListWidget.__init__`, the local variable `scroll` is created but not retained. Change:

```python
scroll = QScrollArea()
# ... configure ...
scroll.setWidget(self._container)
```

to:

```python
self._scroll = QScrollArea()
# ... configure (same as before, replacing `scroll` with `self._scroll`) ...
self._scroll.setWidget(self._container)
```

**Step 2 — ensure visibility after navigation:**

In `_on_navigate_down` and `_on_navigate_up`, after calling `setFocus()` on the target widget, immediately call `ensureWidgetVisible`:

```python
def _on_navigate_down(self, cell_id: str) -> None:
    targets = self._focus_targets()
    idx = next((i for i, (cid, _) in enumerate(targets) if cid == cell_id), None)
    if idx is not None and idx + 1 < len(targets):
        widget = targets[idx + 1][1]
        widget.setFocus()
        self._scroll.ensureWidgetVisible(widget)

def _on_navigate_up(self, cell_id: str) -> None:
    targets = self._focus_targets()
    idx = next((i for i, (cid, _) in enumerate(targets) if cid == cell_id), None)
    if idx is not None and idx > 0:
        widget = targets[idx - 1][1]
        widget.setFocus()
        self._scroll.ensureWidgetVisible(widget)
```

**Step 3 — ensure visibility after new cell creation:**

When a new cell is added and focused (e.g. after Enter), the adding method should also call `self._scroll.ensureWidgetVisible(new_cell)` after the cell is inserted and focus is set.

**Step 4 — ensure visibility after morph / deletion:**

After any operation that moves focus to a different widget (morph, backspace-delete), call `self._scroll.ensureWidgetVisible(focused_widget)` on the widget that receives focus.

**Note on `ensureWidgetVisible` arguments:**  
`QScrollArea.ensureWidgetVisible(childWidget, xmargin=50, ymargin=50)` accepts optional margin arguments. The defaults (50 px) add a small cushion so the focused widget isn't flush against the viewport edge. The defaults are reasonable; no tuning needed initially.

**Tests to add:**
- Navigate down past the bottom of the visible area; verify `ensureWidgetVisible` is called on the newly focused widget.
- Navigate up past the top; same check.
- Press Enter on the last visible cell; new cell below should be visible after creation.
- Backspace on an empty cell at the bottom of the list; the cell above (which receives focus) should be visible.

---

### FEAT-050 — Integer-type casting for array indexing in equation cells

**Status:** Open  
**Logged:** 2026-05-23

**Description:**  
Add `int_` (and `intp`) to the equation namespace whitelist so users can explicitly cast float values to integer type for use as array indices. This fills the gap between slider auto-promotion (which converts whole-number slider floats to Python `int` automatically) and equation-cell outputs (which remain numpy floats and cannot be used as array indices without explicit casting).

**Motivation:**  
Slider values are automatically promoted to Python `int` when they are whole numbers (e.g. `path[:time]` works when `time` is a slider). But when an index is derived from an equation cell — such as `n = floor(k * 10)` — the result is a `np.float64` scalar. NumPy raises `IndexError: only integer scalar arrays can be converted to a scalar index` when a float scalar is used as an index. Currently there is no in-namespace way to perform this cast without reaching for `int()` (which works only for Python scalars, not numpy arrays).

**What already exists:**  
- `int` is already in the equation namespace (`namespace.py:97`) and works for Python scalar → int conversion.  
- `floor` and `ceil` return `np.float64`, not `np.int_`.  
- `round` is in the namespace but also returns `np.float64`.

**Proposed additions to `build_equation_namespace()` (`namespace.py`):**

```python
from numpy import int_, intp   # add to the top-level import block

# in the ns dict:
"int_":  int_,   # numpy default integer type; scalar or array casting
"intp":  intp,   # pointer-sized integer; correct type for array indices
```

Usage examples:
```python
n = int_(round(k * 10))   # cast scalar float to numpy int
arr[n]                     # now legal — n is np.int_

mask = arange(100)
indices = int_(mask / 2)   # element-wise int cast on an array
arr[indices]               # fancy indexing
```

**Safety:** `np.int_` and `np.intp` are numpy scalar/array type constructors — their call signatures accept only numeric arguments. They cannot trigger I/O, imports, or class traversal. Both are safe to add under the existing security model (namespace restriction + AST checker).

**`int` vs `int_`:**  
`int` (already present) accepts Python scalars and returns a Python `int`. `int_` accepts numpy scalars and arrays and returns `np.int_` (or an array of `np.int_`). Users working with numpy outputs should prefer `int_`; the `int` alias remains for compatibility with the existing documented pattern `int(round(t))`.

**Documentation update (`design-docs/03-expression-evaluation.md`):**  
Add to the Expression Language Conventions section:

> **Integer casting for array indices:** Use `int_(expr)` to cast a float scalar or array to integer type for use as an array index. For scalars, `int(expr)` also works (Python builtin, already in namespace). Prefer `int_(round(expr))` over `int_(floor(expr))` to avoid floating-point off-by-one errors at whole numbers. The `intp` type is equivalent but sized for indexing on the current platform — either is acceptable.

**Tests to add:**
- `int_(np.float64(3.5))` returns an integer-typed scalar equal to `3`.
- `int_(np.array([1.9, 2.1, 3.0]))` returns an integer array `[1, 2, 3]`.
- `arr[int_(round(k))]` does not raise `IndexError` in an equation cell when `k` is a float cell output.
- `intp` is available and behaves identically for indexing purposes.
- Neither `int_` nor `intp` can be used to access dangerous attributes (AST check still applies).

---

### FEAT-049 — Crosshair shadow

**Status:** Open  
**Logged:** 2026-05-23

**Description:**  
When the shadow overlay is enabled, also cast a projected shadow for the orbit-target crosshair onto the z_min floor plane. The crosshair shadow follows the orbit target just like the crosshair itself does, making the target's XY position readable at a glance relative to the floor plane even when the camera is at an oblique angle.

**Motivation:**  
The shadow toggle currently projects scene objects (surfaces, curves, scatter) onto the floor. The crosshair, which marks the camera's orbit pivot, is excluded. Adding its shadow makes it consistent with the rest of the shadow system and reinforces the crosshair's role as a 3D position indicator.

**Scope:**  
- Only the X and Y arms are projected (horizontal arms cast a visible shadow line at the floor level).  
- The Z arm is vertical; its shadow collapses to a single point at the crosshair's XY position and is omitted.
- The shadow renders using `_shadow_color` and `_shadow_opacity` — consistent with all other shadows.
- Visibility rule: shown when `_shadow_visible AND _crosshair_visible`; hidden when either is off.

**Implementation (`renderer.py`, `PringleRenderer`):**

**New instance variable:**
```python
self._crosshair_shadow_group: gfx.Group | None = None
```
Initialized alongside `_crosshair_group` in `__init__` via a `_rebuild_crosshair()` call (which already runs at startup).

**Extend `_rebuild_crosshair` to also build the shadow group:**

```python
def _rebuild_crosshair(self) -> None:
    # --- existing crosshair teardown ---
    if self._crosshair_group is not None:
        self._scene.remove(self._crosshair_group)
    if self._crosshair_shadow_group is not None:
        self._scene.remove(self._crosshair_shadow_group)

    xn, xx, yn, yx, zn, zx = self._overlay_bounds
    arm = max(xx - xn, yx - yn, zx - zn) * 0.0125

    # --- existing crosshair build (unchanged) ---
    group = gfx.Group()
    for p0, p1, color in [
        ((-arm, 0, 0), (arm, 0, 0),  (0.85, 0.35, 0.35, 1.0)),
        ((0, -arm, 0), (0, arm, 0),  (0.35, 0.75, 0.35, 1.0)),
        ((0, 0, -arm), (0, 0, arm),  (0.35, 0.50, 0.90, 1.0)),
    ]:
        ...
    group.visible = self._crosshair_visible
    self._scene.add(group)
    self._crosshair_group = group

    # --- new: crosshair shadow (X and Y arms only, at local z=0) ---
    z_floor = float(self._overlay_bounds[4]) + 1e-3  # same offset as _make_shadow_object
    sc = (*self._shadow_color, self._shadow_opacity)
    shadow_group = gfx.Group()
    for p0, p1 in [
        ((-arm, 0, 0), (arm, 0, 0)),   # X arm
        ((0, -arm, 0), (0, arm, 0)),   # Y arm
    ]:
        pts = np.array([p0, p1], dtype=np.float32)
        geo = gfx.Geometry(positions=pts)
        mat = gfx.LineMaterial(color=sc, thickness=2.5)
        shadow_group.add(gfx.Line(geo, mat))
    shadow_group.visible = self._shadow_visible and self._crosshair_visible
    self._scene.add(shadow_group)
    self._crosshair_shadow_group = shadow_group
```

The shadow group's arms are built identically to the crosshair's X/Y arms (same local coordinates). Its `local.position` is tracked to `(target.x, target.y, z_floor)` each frame — this places the arms at world z = z_floor regardless of the target's z height.

**Per-frame position update (existing render loop, `renderer.py` ~line 1231):**

```python
if self._crosshair_group is not None:
    t = self._controller.target
    self._crosshair_group.local.position = (float(t[0]), float(t[1]), float(t[2]))

# new: shadow tracks XY of target but stays at floor z
if self._crosshair_shadow_group is not None:
    z_floor = float(self._overlay_bounds[4]) + 1e-3
    self._crosshair_shadow_group.local.position = (float(t[0]), float(t[1]), z_floor)
```

**Visibility updates — extend existing toggle methods:**

```python
def set_crosshair_visible(self, visible: bool) -> None:
    self._crosshair_visible = visible
    if self._crosshair_group is not None:
        self._crosshair_group.visible = visible
    if self._crosshair_shadow_group is not None:
        self._crosshair_shadow_group.visible = self._shadow_visible and visible

def set_shadow_visible(self, visible: bool) -> None:
    self._shadow_visible = visible
    for cell_id, shadow in self._shadow_objects.items():
        src = self._objects.get(cell_id)
        shadow.visible = visible and (src is None or src.visible)
    # new: also toggle crosshair shadow
    if self._crosshair_shadow_group is not None:
        self._crosshair_shadow_group.visible = visible and self._crosshair_visible
```

**Color updates — extend `set_shadow_color_for_bg` and `set_shadow_opacity`:**

Both methods iterate `self._shadow_objects` to update color/opacity. They must also update the crosshair shadow lines:

```python
# in set_shadow_opacity and set_shadow_color_for_bg:
if self._crosshair_shadow_group is not None:
    new_color = (*self._shadow_color, self._shadow_opacity)
    for line in self._crosshair_shadow_group.children:
        line.material.color = new_color
```

**z_min change handling:**  
`_rebuild_crosshair` is already called from `set_overlay_bounds` when z_min changes (`renderer.py:929`). Since the shadow group is rebuilt inside `_rebuild_crosshair`, it is automatically rebuilt with the new z_floor whenever bounds change. No additional call site needed.

**No session persistence needed:**  
The crosshair shadow is a derived visual from the existing `show_shadow` and `show_crosshair` session flags. No new YAML field is required.

**Tests to add:**
- With shadows on and crosshair on, two `gfx.Line` objects (X and Y arms) exist in `_crosshair_shadow_group`.
- Shadow group z-position equals z_floor (z_min + 1e-3) regardless of orbit target z.
- Toggling crosshair off hides the shadow group.
- Toggling shadows off hides the shadow group.
- Changing shadow opacity updates line material color on the crosshair shadow group.
- z_min change triggers `_rebuild_crosshair` and the shadow group uses the new z_floor.

---

### FEAT-048 — Cross-cell find and replace

**Status:** Open  
**Logged:** 2026-05-22

**Description:**  
A panel (UI TBD — to be refined) that lets the user search for text across all cells and optionally replace matches, covering the primary use case of renaming a variable across an entire session in one action. Find is plain-text substring matching by default; a whole-word option handles the variable-rename case cleanly.

**Motivation:**  
Renaming a variable used in many cells currently requires editing each cell manually. A session-wide find-and-replace brings this to a single action.

**Scope:**  
Search and replace operates on all non-comment cells. Comment cells are skipped (their source is not evaluated). Folder and slider cells are included.

---

**UI — deferred; to be refined in a follow-up.** Rough intent:
- A small panel (floating dialog or collapsible section at the top of the left panel) with Find and Replace text inputs.
- "Find All" highlights all matches across cells.
- "Replace All" applies the substitution and triggers a single namespace rebuild.
- Options: case-sensitive toggle, whole-word toggle (required for safe variable rename).
- Keyboard shortcut to open: `Cmd+H` / `Ctrl+H` (standard across editors).

---

**Implementation sketch (`cell_list.py`):**

```python
def find_replace_all(
    self,
    find: str,
    replace: str,
    *,
    case_sensitive: bool = True,
    whole_word: bool = False,
) -> int:
    """Replace all occurrences of find with replace across all cells.
    Returns the number of cells modified."""
    import re
    if not find:
        return 0
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.escape(find)
    if whole_word:
        pattern = r"\b" + pattern + r"\b"
    rx = re.compile(pattern, flags)
    modified = 0
    with self._suppress_rebuilds():   # suppress per-cell rebuilds during batch
        for cell in self._cells:
            old = cell.source()
            new = rx.sub(replace, old)
            if new != old:
                cell.set_source(new)
                modified += 1
    if modified:
        self._rebuild_namespace()
    return modified
```

`_suppress_rebuilds()` is a context manager that sets a flag to skip `_rebuild_namespace()` inside `_on_cell_changed`, equivalent to the existing `_suppress_rebuild` flag used during bulk session restore.

For **highlighting** (find-without-replace), iterate cells and call `setExtraSelections()` on their `CellTextEdit` with all match ranges. Clearing highlights = call with an empty list.

**Whole-word matching for variable names:**  
`\b` word boundaries work correctly for Python identifiers because identifier characters (`[A-Za-z0-9_]`) are all `\w`. Searching for `a` with whole-word on will not match `alpha` or `_a`. This is the safe default for variable rename.

**Session persistence:**  
Find/replace state is not persisted to YAML — it is transient UI state only.

**Tests to add:**

- `find_replace_all("a", "b", whole_word=True)` renames standalone `a` but does not touch `alpha` or `a_val`.
- Returns correct count of modified cells.
- No rebuild fires during the batch; exactly one `_rebuild_namespace()` fires after.
- Empty `find` string is a no-op and returns 0.
- Case-insensitive replace: `find_replace_all("Pi", "pi", case_sensitive=False)` matches `PI`, `Pi`, `pi`.

---

### FEAT-047 — Cmd+L / Ctrl+L: select current line in focused cell

**Status:** Open  
**Logged:** 2026-05-22

**Description:**  
Pressing `Cmd+L` (macOS) or `Ctrl+L` (Linux/Windows) in a focused `CellTextEdit` selects the entire current line, matching the VSCode behavior. No cross-cell behavior; this is purely a within-cell cursor operation.

**Implementation (`cell_widget.py`, `CellTextEdit.keyPressEvent`):**

Add a branch before the `super()` call:

```python
ctrl = Qt.KeyboardModifier.ControlModifier
if key == Qt.Key.Key_L and mod == ctrl:
    cursor = self.textCursor()
    cursor.select(QTextCursor.SelectionType.LineUnderCursor)
    self.setTextCursor(cursor)
    return
```

`QTextCursor.SelectionType.LineUnderCursor` selects from the start to end of the line the cursor is on, excluding the trailing newline — identical to VSCode `Cmd+L`. No additional imports required (`QTextCursor` is already imported in `cell_widget.py`).

On macOS, `Qt.KeyboardModifier.ControlModifier` maps to the Command key, so this fires on `Cmd+L` on Mac and `Ctrl+L` on Linux/Windows — consistent with the `QKeySequence("Ctrl+/")` pattern used elsewhere.

**Note:** `Ctrl+L` in web browsers focuses the address bar. Since Pringle is a desktop Qt app (not browser-embedded), there is no conflict.

**Tests to add:**

- With cursor on `z = x**2 + y**2`, pressing `Ctrl+L` selects the full line text.
- With cursor on the second line of a multi-line cell, only that line is selected (not the whole cell).
- Works in `_CommentEdit` as well (comment cells inherit the same `keyPressEvent` override or the same change is applied there).

---

### FEAT-036 — Critical point markers on surfaces (toggle for animation performance)
**Status:** Open  
**Logged:** 2026-05-20

**Description:**  
Overlay small markers on a surface at every point where `∂z/∂x = 0` and `∂z/∂y = 0` simultaneously — the critical points (local minima, maxima, and saddle points). Markers are all the same neutral color; classification by type is intentionally omitted since the surface geometry makes type self-evident and extra colors increase visual clutter. The feature is **off by default** and must be explicitly toggled on because it requires sharing the normal computation path with the renderer.

**Motivation:**  
Visually locating fixed points of a parameterized surface (e.g. identifying how extrema move as a slider sweeps through values) is difficult by eye. Static markers make this immediate. The primary use case is parameter sweeps — watching markers migrate across the surface as `a` changes — which makes the toggle critical: users running animated sweeps should be able to disable the overlay to recover framerate.

**UI:**  
A checkbox in the style popover labeled "Critical points", stored as `CellStyle.show_critical_points: bool = False`. Visible for all surface-type cells. Checking it triggers an immediate re-render; unchecking removes the marker overlay with no recomputation.

**Gradient sharing — zero marginal cost for the `np.gradient` call:**

`_grid_normals` in `renderer.py` already computes `dz_dx` and `dz_dy` via `np.gradient` (lines 35–36) in order to build the Phong shading normals. These values are used internally and then discarded. Critical point detection needs exactly the same two arrays on the same grid.

A critical point (∂z/∂x = 0, ∂z/∂y = 0) corresponds to the surface normal pointing straight up — `n = (0, 0, 1)` — since the unnormalized normal is `(-∂z/∂x, -∂z/∂y, 1)`. The gradient information is therefore already encoded in the normal vectors: `dz_dx = -nx/nz`, `dz_dy = -ny/nz`. However, recovering it from the normalized float32 normals amplifies precision error for near-vertical faces, so the cleaner approach is to share the raw gradients directly.

**Required refactor of `_grid_normals`:** Extract gradient computation into a standalone helper, then pass the result to both the normal builder and critical point detection:

```python
def _grid_gradients(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (dz_dx, dz_dy) via central finite differences. Used by both
    _grid_normals and critical point detection — compute once, share."""
    return np.gradient(z, x[0, :], axis=1), np.gradient(z, y[:, 0], axis=0)

def _grid_normals(dz_dx: np.ndarray, dz_dy: np.ndarray) -> np.ndarray:
    """Accept pre-computed gradients; signature change from (x, y, z)."""
    nx = -dz_dx;  ny = -dz_dy;  nz = np.ones_like(dz_dx)
    length = np.sqrt(nx**2 + ny**2 + nz**2)
    ...
```

`make_surface_mesh` calls `_grid_gradients` once, passes the result to both. When `show_critical_points=False`, the gradients are only used for normals — no extra work. When `True`, the same arrays are also passed to `_find_critical_points`. The `np.gradient` call is paid exactly once regardless.

**Important:** use the pre-clip gradients (before `_clip_mesh_to_mask` runs), since the clipped normals array grows with boundary midpoint vertices and can no longer be reshaped to `(rows, cols)`. The seam is between lines 194 and 198 of the current `make_surface_mesh`.

**Algorithm — detection:**

`dz_dx` and `dz_dy` are already available from `_grid_gradients` — no additional `np.gradient` call needed. Scan for cells where both gradient components have a sign change. For each 2×2 block `(i,j)`:

```python
# sign change in gx across the cell (either row)
sx = (gx[i, j] * gx[i, j+1] < 0) | (gx[i+1, j] * gx[i+1, j+1] < 0)
# sign change in gy across the cell (either column)
sy = (gy[i, j] * gy[i+1, j] < 0) | (gy[i, j+1] * gy[i+1, j+1] < 0)
candidates = np.where(sx & sy)   # fully vectorized; no Python loop
```

For a 128×128 grid this is ~16K boolean comparisons — sub-millisecond.

**Algorithm — refinement (no extra z evaluations):**

Refinement uses only already-computed gradient values at the four corners of each candidate cell. One Newton step with the local Hessian assembled from finite differences of `gx`/`gy`:

```python
for i, j in zip(*candidates):
    # gradient at cell center (bilinear interpolation of corners)
    g0 = np.array([
        (gx[i, j] + gx[i+1, j] + gx[i, j+1] + gx[i+1, j+1]) / 4,
        (gy[i, j] + gy[i+1, j] + gy[i, j+1] + gy[i+1, j+1]) / 4,
    ])
    # local Hessian from finite differences of the gradient arrays
    J = np.array([
        [(gx[i, j+1] - gx[i, j]) / dx,  (gx[i+1, j] - gx[i, j]) / dy],
        [(gy[i, j+1] - gy[i, j]) / dx,  (gy[i+1, j] - gy[i, j]) / dy],
    ])
    if abs(np.linalg.det(J)) > 1e-10:
        delta = np.linalg.solve(J, -g0)
        delta = np.clip(delta, -0.5, 0.5)   # stay within cell
        x_crit = x1d[j] + delta[0] * dx
        y_crit = y1d[i] + delta[1] * dy
    else:
        x_crit, y_crit = x1d[j] + dx/2, y1d[i] + dy/2   # fallback to midpoint
    z_crit = float(z_raw[i, j])   # nearest grid value (or bilinear interp)
    critical_pts.append((x_crit, y_crit, z_crit))
```

The Newton step uses only values already in `gx` and `gy` — zero additional `z` evaluations. The cost is one 2×2 linear solve per candidate. With K critical points (typically K ≪ N²), this adds negligible time.

**No classification:** The Hessian determinant and sign check (for min/max/saddle distinction) are intentionally skipped. All markers are rendered identically.

**Rendering:**  
Critical points are collected into an `(K, 3)` float32 array and passed to `make_scatter_mesh` with a fixed neutral style (light gray, small size). The scatter object is keyed as `cell_id + ":crits"` in `_objects`, so `remove_object(cell_id)` must also remove `cell_id + ":crits"`. When `show_critical_points=False`, the entry is absent entirely (not hidden — removed) so it imposes no render cost.

**Performance profile:**

| Component | Cost | Notes |
|---|---|---|
| `_grid_gradients` (`np.gradient`) | **0 ms marginal** | Already computed for Phong normals; shared via refactor |
| Vectorized sign-change scan | < 0.1 ms | Pure NumPy boolean ops |
| Newton refinement (K steps) | < 0.1 ms | Typically K < 20; 2×2 solve per candidate |
| Total marginal overhead | **< 0.2 ms at 128×128** | Essentially free on top of normal surface render |

The gradient computation was originally listed as ~0.5 ms, but this is eliminated by sharing `dz_dx`/`dz_dy` from `_grid_normals` (which already pays this cost unconditionally for Phong shading). The true marginal cost of enabling critical point detection is just the sign-change scan and refinement.

With `show_critical_points=False`, the gradient arrays are still computed (they are needed for Phong normals regardless), but the sign-change scan is skipped entirely.

**Integration in `_on_cell_result` (`app.py`):**  
After `make_surface_mesh` produces the surface mesh, and only when `style.show_critical_points` is True:

```python
crits = _find_critical_points(result.data, result.x, result.y,
                               z_raw=result.data_unmasked)
if len(crits) > 0:
    crit_mesh = make_scatter_mesh(crits, color=(0.85, 0.85, 0.85, 1.0),
                                  size=0.04)
    vp.add_object(cell_id + ":crits", crit_mesh)
else:
    vp.remove_object(cell_id + ":crits")
```

`_find_critical_points` is a standalone function in `renderer.py` taking `(z, x_grid, y_grid)` and returning an `(K, 3)` array. Keeping it separate makes it testable and lets the toggle short-circuit before calling it.

**Constraint interaction:**  
Use `z` (the NaN-masked data) for gradient computation so that masked regions (constraint sub-cells) produce NaN gradients. Cells adjacent to a NaN value will have unreliable gradient estimates via `np.gradient`'s edge handling — in practice this means a few spurious candidates near the constraint boundary. These are filtered out by checking that `z_crit` is not NaN.

---

### FEAT-035 — User-supplied variable as colormap data source ("colormap by")
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
Allow the user to specify any same-shaped array from the expression namespace as the data source that drives a colormap, instead of the built-in default (z-values for surfaces, parametric index for curves). The primary use case is gradient-magnitude coloring: define `grad_norm` in a cell, then pin the colormap of a surface to `grad_norm` to visually locate fixed points and track how they move as parameters change.

**UI:**  
Add an optional text-input row below the colormap swatch row in `StylePopoverWidget`, visible only when a colormap is selected:
```
Colormap:  [▒▒▒▒▒][▓▓▓▓▓][░░░░░][▒▒▒▒▒][▓▓▓▓▓] [⇄]
by: [_________________________]
```
The field has placeholder text `variable name…`. Typing a name and pressing Enter (or leaving the field) updates the style. Clearing the field reverts to default coloring. Selecting a colormap swatch while the field is empty keeps the default source; the field is independent of swatch selection so a user can switch colormaps while keeping the same data source.

**Implementation — `CellStyle` (`style.py`):**  
Add one field:
```python
colormap_expr: str | None = None   # variable name to drive colormap; None = default
```
Persisted to YAML as `colormap_expr`. Read back in `restore_cell_list` with fallback `None`.

**Implementation — `style_popover.py`:**  
After the `cmap_row` block, add a conditional row:
```python
self._cmap_expr_edit = QLineEdit()
self._cmap_expr_edit.setPlaceholderText("variable name…")
self._cmap_expr_edit.setText(self._style.colormap_expr or "")
self._cmap_expr_edit.setFixedWidth(130)
self._cmap_expr_edit.editingFinished.connect(self._on_cmap_expr_changed)
expr_row = QHBoxLayout()
expr_row.addWidget(QLabel("by:"))
expr_row.addWidget(self._cmap_expr_edit)
expr_row.addStretch()
layout.addLayout(expr_row)
```
The row is always present but could be hidden when no colormap is selected (style cleanup concern, not functional). `_on_cmap_expr_changed` updates `self._style.colormap_expr` to the stripped text (or `None` if empty) and emits `style_changed`.

**Implementation — `app.py` (`_on_cell_result`):**  
Resolve the variable name to an array from the shared namespace immediately before calling mesh builders:
```python
cmap_data: np.ndarray | None = None
if style.colormap and style.colormap_expr:
    raw = self._cell_list._shared_ns.get(style.colormap_expr.strip())
    if isinstance(raw, np.ndarray):
        cmap_data = raw.astype(np.float32)
    # if lookup fails or wrong type: cmap_data stays None → fallback to default
```
Pass `cmap_data` to each mesh builder as a new `colormap_data: np.ndarray | None = None` parameter.

**Implementation — `renderer.py` (mesh builders):**  
Add `colormap_data` parameter to `make_surface_mesh`, `make_line_mesh`, `make_scatter_mesh`. When present and shape-valid, use it as the scalar array for `_apply_colormap` instead of the built-in default:

*Surface:*
```python
if colormap is not None:
    if colormap_data is not None and colormap_data.size == z.size:
        color_vals = colormap_data.ravel()
    elif colormap_data is not None:
        # Shape mismatch: fall back, mark warning
        color_vals = positions[:, 2]
    else:
        color_vals = positions[:, 2]   # default: z-value
    colors = _apply_colormap(color_vals, colormap, colormap_reversed)
```
The shape check `colormap_data.size == z.size` ensures the array matches the N×M surface grid. After clipping, `positions` may have more vertices (boundary midpoints), so `colormap_data.ravel()` is indexed before clipping and matched to the original grid. The cleanest approach is: compute colors for all N×M grid positions using the custom data, then let the clip pass rearrange them in sync with vertices.  
This requires threading `colormap_data`-derived colors through the clip as a per-vertex attribute alongside positions/normals — a moderate refactor. An alternative is to map the custom data onto the clipped vertices by nearest-grid-index, which is simpler but approximate at boundaries.

*Curve / scatter:*
```python
if colormap is not None:
    if colormap_data is not None and len(colormap_data.ravel()) == len(pts):
        color_vals = colormap_data.ravel()
    else:
        color_vals = np.linspace(0.0, 1.0, len(pts), dtype=np.float32)
    colors = _apply_colormap(color_vals, colormap, colormap_reversed)
```

**Shape-mismatch handling:**  
When `colormap_data` is provided but has the wrong shape, fall back to default coloring silently. Optionally surface a warning via the cell's `set_warning` mechanism: since the warning must be set before the mesh builder is called (the builder has no access to the cell widget), the check and warning should happen in `_on_cell_result` before the builder call.

**Dependency tracking limitation:**  
If the surface cell's source does not reference `colormap_expr` (e.g., the cell is `z = f(x, y)` and `grad_norm` is defined in a separate cell), a change to `grad_norm`'s cell will trigger `_rebuild_namespace` and re-evaluate `grad_norm` — but the surface cell `z = f(x, y)` has no syntactic dependency on `grad_norm` and will not re-evaluate. The surface will therefore keep its old coloring until some other change forces a rebuild.

In the typical use case (gradient arrays derived from the same slider parameters that drive the surface), this is not a problem: changing `a` re-evaluates both `z = f(x, y, a)` and `grad_norm = g(x, y, a)`, and the surface rebuilds picking up the new `grad_norm`. The edge case only arises if `grad_norm` depends on variables the surface doesn't share.

**Session persistence (`session.py`):**  
`cell_to_dict` writes `colormap_expr` from `style.colormap_expr`. `restore_cell_list` reads it with `style_data.get("colormap_expr", None)`.

---

---

### FEAT-030 — Camera inertia: orbit continues spinning after mouse release
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
When the user releases the mouse after rotating the viewport, the scene should continue spinning at the release velocity and gradually decelerate to a stop — matching the behavior in Desmos 3D. Slow deliberate releases produce a gentle glide; fast flicks produce a prolonged spin. Any new mouse-down immediately cancels the coast.

**Desmos reference:** see `01-desmos-3d-overview.md` — Camera Inertia section, updated 2026-05-18.

**Why pygfx's built-in `damping` is not sufficient:**  
`gfx.OrbitController` is constructed with `damping=4` (default). This parameter smooths the camera response *during* active drag (so fast pointer jerks don't cause instantaneous jumps). It does not produce any rotation after `pointerup` — once the mouse is released and the drag action ends, the controller stops updating the camera entirely. Post-release inertia requires a separate "coast" state that must be driven by the application's own render loop.

**Implementation approach:**

The coast state needs to live outside `OrbitController` since there is no hook for it inside pygfx. The natural place is `PringleViewport._tick()` (or the equivalent per-frame callback), which already drives WASD movement.

1. **Intercept pointer events from wgpu canvas.** The wgpu canvas (`rendercanvas`) delivers `pointer_up` and `pointer_move` events to registered handlers. Register a secondary handler (alongside the controller's handler) that:
   - On each `pointer_move` while the primary mouse button is held: records `(Δazimuth, Δelevation, timestamp)` into a fixed-length deque (e.g. capacity 10 samples, ~100 ms window). Δazimuth and Δelevation are computed the same way the `OrbitController` does: `dx / viewport_width * π` and `dy / viewport_height * π` (approximate; exact formula in `_orbit.py`).
   - On `pointer_up`: reads the deque, computes time-weighted average velocity `(ω_az, ω_el)` in rad/s, stores it as `_coast_velocity`. If the deque is empty or the release was stationary, sets velocity to zero (no coast).

2. **Coast loop in `_tick()`.** Each frame while `|_coast_velocity| > threshold`:
   ```python
   DECAY = 0.88          # fraction of velocity retained per second
   STOP_RAD_S = 0.005    # stop threshold

   dt = elapsed_since_last_tick()
   if _coast_velocity and magnitude(_coast_velocity) > STOP_RAD_S:
       daz, del_ = _coast_velocity[0] * dt, _coast_velocity[1] * dt
       controller.rotate(daz, del_)     # pygfx public API
       _coast_velocity = (
           _coast_velocity[0] * DECAY ** dt,
           _coast_velocity[1] * DECAY ** dt,
       )
   else:
       _coast_velocity = None
   ```
   `controller.rotate()` is the same method the OrbitController uses internally and is part of the public API.

3. **Cancel coast on new drag.** The `pointer_down` handler sets `_coast_velocity = None` before the OrbitController's handler takes over. This ensures the user always gets direct control immediately.

4. **Interaction with WASD pan (BUG-013 context).** The coast loop and the WASD loop both write to the camera via the controller. The existing BUG-013 notes that simultaneous WASD + mouse drag causes conflicts; coasting after release does not conflict with WASD (no mouse button is held), so this is a safe combination.

**Tuning parameters to expose:**  
- `DECAY` (0.0 = instant stop, 1.0 = never stops) — reasonable default ~0.88 per second  
- `STOP_RAD_S` threshold — default 0.005 rad/s  
- These can be hardcoded initially; a UI slider in the axis settings panel could expose them later if users want control.

---


### FEAT-025 — Save button and unsaved-changes indicator
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
Add a visible save button and/or an unsaved-changes indicator to the UI. The app already tracks `_modified` and keyboard shortcuts (`Cmd+S` / `Ctrl+S`) work, but there is no on-screen affordance communicating save state or providing a click target for users who don't know the shortcut.

**What's already in place (`app.py:324–335`):**  
- `_modified: bool` is set on every cell/slider change and cleared on save.
- `_update_title()` prepends `"* "` to the window title when modified — e.g. `"* pringle — rossler.yml"`.
- `Cmd+S` / `Ctrl+S` (save) and `Cmd+Shift+S` / `Ctrl+Shift+S` (save-as) shortcuts are registered.

**What's missing:**

1. **Native macOS close-button dot:** Qt provides `QMainWindow.setWindowModified(bool)` and a `[*]` placeholder in `setWindowTitle`. When used together, Qt automatically shows the native dot inside the red traffic-light close button on macOS (and an asterisk in the title on other platforms). The current code uses a manual `"* "` prefix instead, so the macOS dot never appears. Fix: replace the manual prefix with the standard Qt mechanism:
   ```python
   # _update_title in app.py
   self.setWindowTitle(f"pringle — {name}[*]")   # [*] is Qt's placeholder
   self.setWindowModified(self._modified)          # drives the dot on macOS
   ```

2. **On-screen save button / indicator:** The window title `*` is easy to miss. An explicit UI element (location and style TBD — to be discussed) would make the save state more prominent. Options to consider:
   - A small `●` dot or `Save` button in the top bar / toolbar area that is highlighted when `_modified` is True and grayed out when clean.
   - A floppy-disk icon button (`💾` or a custom SVG) that triggers `_on_save` on click.
   - A pill-shaped status label (e.g. `"Unsaved"` / `"Saved"`) styled similarly to how the cell status area works.
   - A thin colored border or highlight on the left panel header when unsaved (minimal footprint, no extra button).

**Cross-platform notes:**  
- **macOS:** native dot on the red close button via `setWindowModified` (free once the `[*]` fix above is applied). No extra work needed for the title bar — macOS renders `[*]` as a bullet `•` before the filename automatically.
- **Windows/Linux:** `setWindowModified` causes Qt to substitute `[*]` with `*` in the title. An explicit on-screen indicator matters more on these platforms since there's no native close-button equivalent.

**Open questions (to discuss before implementing):**  
- Where should the save button live? Top-left of the left panel? Inline in the menu/toolbar area? Inside the axis settings popup?
- Should it be icon-only, text-only, or icon+text?
- Should "Save" and "Save As…" both be surfaced, or just "Save"?

---

### FEAT-017 — Dark vs light mode toggle
**Status:** Open  
**Logged:** 2026-05-16

**Description:**  
Add a toggle (checkbox or button) to switch the application between a dark and a light color scheme. Both the Qt UI panels and the 3D viewport background should update consistently.

**Implementation notes:**
- Qt side: apply a `QApplication.setStyleSheet(...)` swap. A minimal dark palette can be constructed from `QPalette` without a full third-party theme library.
- Viewport background: `renderer.background` (the wgpu canvas clear color) needs to change — currently hardcoded in `renderer.py`. Expose a `set_background_color` method and call it on toggle.
- Axis/bbox/crosshair line colors may need to invert or adjust for legibility against the new background.
- Persist the preference in the session YAML or a user config file so the chosen mode survives restarts.
- The toggle could live in the new Axis Settings popup (FEAT-012) or in a top-level View menu.

---

### FEAT-016 — Color defaults and color picker/slider in style popup
**Status:** Open  
**Logged:** 2026-05-16

**Description:**  
Extend the existing per-cell style popover (`style_popover.py`) with a proper color picker and opacity slider, replacing the current color dot (which only cycles through a fixed palette). Also establish a global default color sequence so new cells get predictable, Desmos-like colors in order.

**Implementation notes:**
- Qt provides `QColorDialog` out of the box; it can be launched from a "Custom…" button inside the popover to let the user pick any RGBA color.
- Alternatively, embed a compact HSL/RGB slider widget directly in the popover (avoids opening a separate window).
- Opacity slider: a `QSlider` mapped to the alpha channel of the cell's RGBA color; the viewport material's `opacity` and `is_transparent` flag must be updated on change.
- Default sequence: define an ordered list of RGBA defaults (matching Desmos's palette or similar) in `style.py`; `CellListWidget` assigns the next unused color when a cell is created.
- The color dot in the cell row should update live as the picker changes.

---

---

### FEAT-018 — Load external data files into data cells
**Status:** Open  
**Logged:** 2026-05-17

**Description:**  
Allow a data cell to load an external file by providing a quoted path as the RHS of an assignment. When the user presses ▷, the app detects that the source is a path literal, attempts to load the file, and exposes the result as a numpy array in the shared namespace — identical to any other data cell output. Load errors (bad path, unsupported format, malformed content) are surfaced in the cell's status area with a descriptive message rather than crashing.

**UX flow:**
```
d = "path/to/data.npy"
```
1. User types the above in a data cell and presses ▷.
2. The loader detects the string literal RHS and dispatches to the appropriate format handler.
3. On success: the cell shows `ok` status, exports `d` (the array or dict) into the shared namespace, and displays the shape in the preview area (e.g. `(1000, 3)`).
4. On failure: the cell shows an `error` status with a plain-language message (e.g. "File not found: path/to/data.npy" or "CSV parse error: non-numeric value in column 2, row 47"). No popup — consistent with how other cell errors are handled.

**Supported formats:**

| Extension | Loader | Notes |
|-----------|--------|-------|
| `.npy` | `np.load(path, allow_pickle=False)` | Single array; see security note below |
| `.npz` | `np.load(path, allow_pickle=False)` | Zip of named arrays; expose as a dict `{"x": arr, ...}` and also unpack each key as `d_x`, `d_y`, etc. into the namespace |
| `.csv` | `np.loadtxt(path, delimiter=",", comments="#")` | Falls back to `np.genfromtxt` with `invalid_raise=False` for files with missing values; skip header rows that can't be parsed as floats |
| `.tsv` | Same as CSV with `delimiter="\t"` | |
| `.txt` | `np.loadtxt(path)` (whitespace-delimited) | |
| `.mat` | `scipy.io.loadmat(path)` | Optional — only if scipy is available; expose the variable dict, let the user index it like `d["x"]` |
| `.json` | `json.load` → `np.array(...)` | Only if the JSON structure is a flat list or list-of-lists; reject otherwise with a clear error |

Other formats (HDF5, Parquet, Excel) are out of scope for v1 — they pull in large optional dependencies and have complex internal structure; log them as "unsupported format" rather than silently failing.

**Implementation sketch:**

Detection happens in `_run_data_cell` (or a new `_load_file_cell` helper called from it) before the usual `run_cell` path:
```python
import ast, re
source = cell.source().strip()
# Match:  name = "some/path"  or  name = 'some/path'
m = re.fullmatch(r'(\w+)\s*=\s*(["\'])(.+?)\2', source)
if m:
    var_name, _, file_path = m.group(1), m.group(2), m.group(3)
    _load_file_into_cell(cell, var_name, Path(file_path))
    return
```
`_load_file_into_cell` resolves the path, dispatches by suffix, wraps the loader call in a `try/except`, and writes the result into `_data_cell_ns` exactly as a computed array would be.

**Security considerations — read carefully:**

- **Pickle deserialization / RCE** (`np.load`): Numpy `.npy` and `.npz` files that contain Python object arrays require pickling. A maliciously crafted `.npy` file with a pickled payload can execute arbitrary code on load. **Always call `np.load(path, allow_pickle=False)`.** If the file requires pickle, numpy raises a `ValueError`; surface it as: "File requires pickle deserialization, which is disabled for security. Re-save the array with `np.save()` using a numeric dtype." Similarly, `scipy.io.loadmat` uses pickle internally for some object types — use only the non-pickle code path if scipy is added.

- **Path traversal**: A relative path like `../../.ssh/id_rsa` resolves relative to the process working directory and could read sensitive files. The loader should call `Path(file_path).resolve()` and optionally warn if the resolved path escapes a user-configured data directory. At minimum, log the resolved absolute path in the cell status so the user can see exactly what was read.

- **Zip bombs** (`.npz`): `.npz` is a zip archive. A malicious file could decompress to gigabytes from a small on-disk size. Add a size cap: check `os.path.getsize(path)` before loading and reject files above a reasonable threshold (e.g. 500 MB) with a clear error. Note this does not fully protect against zip bombs — a more robust approach is to open the zip and check member sizes before extracting.

- **Large file / memory exhaustion**: Even legitimate files can be arbitrarily large. The 500 MB cap above applies here too. Surface the file size in the cell's `ok` preview (e.g. `(1000000, 3) — 22.9 MB`) so the user has visibility.

- **`open()` is currently blocked in equation cells** (`safety.py:23`) but data cells are explicitly more permissive. File loading must stay confined to data cells and the dedicated loader path — it should not be possible to trigger file I/O from an equation cell expression.

---

### FEAT-037 — GPU-accelerated expression evaluation (design decision log)
**Status:** Open — decision pending  
**Logged:** 2026-05-20  
**Related:** PERF-002, PERF-003, PERF-004 in [18-performance-backlog.md](18-performance-backlog.md)

**Background:**  
The expression evaluation pipeline (numpy CPU → numpy arrays → wgpu GPU upload) has three distinct cost layers: the expression computation itself, the Python-loop geometry construction, and the GPU buffer upload. PERF-003/004 address the geometry loops. This entry documents the options for accelerating the computation layer and reducing the GPU upload cost, and records why each option was or was not selected.

**The core constraint: GPU-to-GPU transfer is not free.**  
Moving expression evaluation to a GPU-accelerated library (JAX, PyTorch, CuPy) does not automatically enable sharing data with wgpu. Each library exposes tensors backed by GPU memory (CUDA or Metal), but wgpu's buffer API accepts numpy arrays or raw bytes — not foreign GPU tensors. The practical path for all of these libraries is still `tensor.cpu().numpy()` → `gfx.Geometry` → wgpu upload. At n=128 the CPU roundtrip costs ~0.5ms; this is a real overhead but small compared to the compute savings.

True zero-copy GPU-to-GPU transfer would require either DLPack interop (not currently implemented in pygfx/wgpu-py) or writing compute shaders inside wgpu itself (see option G below).

---

**Option A — JAX**  
`jax.numpy` is nearly API-compatible with numpy. Supports JIT compilation, GPU via XLA (CUDA or Metal via `jax-metal`), and full autodiff via `jax.grad`.

*Advantages:* Near-identical API; autograd opens new mathematical capabilities (parameter-space gradients, implicit surface finding); JIT compilation can speed expression evaluation by 5–50×.

*Blockers for Pringle:*  
- **Immutability.** JAX arrays are immutable; in-place operations (`arr[n] = f(arr[n-1])`) silently fail or raise. The recurrence relation engine (`recurrence.py`) is built around mutable numpy arrays — rewriting it for `jax.lax.scan` would be a major redesign.  
- **Cross-platform uncertainty.** `jax-metal` (macOS) is an experimental backend with inconsistent coverage of JAX ops. Linux/Windows CUDA installs require matching driver versions.  
- **Dependency weight.** JAX adds ~500MB of compiled XLA binaries. Current pringle install is trivially lightweight.

*Verdict: Not recommended as primary backend. Immutability blocks recurrence.*

---

**Option B — PyTorch**  
Widely used GPU tensor library with MPS (Metal) and CUDA backends.

*Advantages:* Mature, widely supported, large ecosystem.

*Blockers for Pringle:*  
- **Immutability.** PyTorch tensors support in-place ops syntactically (`a[i] = x`) but these don't compose with autograd. Same recurrence problem as JAX.  
- **API divergence.** `torch.sum(x, dim=0)` vs `np.sum(x, axis=0)` — argument names differ; the namespace whitelist would need significant reworking.  
- **CUDA version fragmentation.** PyTorch ships different wheels per CUDA version; users must match their driver. This complexity is incompatible with `pip install pringle`.  
- **Size.** PyTorch CPU-only is ~250MB; GPU variant is ~1.5GB.

*Verdict: Not recommended. Worse than JAX on every relevant dimension for this use case.*

---

**Option C — CuPy**  
A near-exact numpy drop-in (`import cupy as np`) for CUDA GPUs. Minimal API changes — most expressions would work unmodified.

*Advantages:* Essentially zero expression-layer refactor; no immutability issue; recurrence engine works as-is; mutable arrays; identical numpy semantics.

*Blockers for Pringle:*  
- **CUDA-only.** CuPy has no Metal or CPU fallback. macOS users (the current development platform) get nothing. A numpy fallback could be made automatic, but this creates a two-code-path maintenance burden.  
- **CUDA dependency.** Same driver-matching problem as PyTorch.

*Verdict: The cleanest API story, but platform exclusion is a hard blocker for now. Worth revisiting if cross-platform GPU compute becomes a requirement and WGSL shaders are not yet ready.*

---

**Option D — Numba**  
JIT compiler for Python + numpy code. Can target CPU (LLVM) or CUDA GPU. Does **not** require changing the expression namespace at all — applies to the renderer's Python-loop bottlenecks rather than user expressions.

*Advantages:*  
- `@numba.njit` on `_clip_mesh_to_mask` (PERF-004, 170ms at n=128) would likely reduce it to ~1ms with zero changes to the public API or user-facing expression semantics.  
- No immutability issue — numba compiles standard Python with mutable numpy arrays.  
- Lightweight dependency; CPU-mode requires no GPU driver.  
- Could accelerate expression evaluation via `@numba.njit` on lambdas, though eval'd lambdas from `exec()` don't compose directly with numba's AOT compilation model.

*Verdict: **Best near-term option for geometry acceleration.** Does not address expression computation on GPU, but PERF-004 is the dominant bottleneck before expression compute matters. Investigate as part of PERF-004 fix.*

---

**Option E — MLX (Apple)**  
Apple's open-source ML framework. Metal-native, numpy-like API, runs on Apple Silicon GPU. Has autograd.

*Advantages:* Native Metal GPU; numpy-like; would achieve zero-copy with wgpu on macOS (both use Metal) if DLPack support were added to pygfx.

*Blockers:*  
- macOS/Apple Silicon only — not usable on Linux or Windows.  
- DLPack interop with wgpu not currently implemented.

*Verdict: Interesting for macOS-only optimization, but platform exclusion makes it unsuitable as a primary backend.*

---

**Option F — Taichi**  
A Python-embedded DSL that compiles to Metal, CUDA, Vulkan, OpenGL, or CPU. Designed for physics simulation and visualization.

*Advantages:* Truly cross-platform GPU (covers macOS, Linux, Windows); could in principle share Metal/Vulkan buffers with wgpu since both target the same backends; data-oriented programming model suits grid computations.

*Blockers:*  
- Not numpy-compatible — users write Taichi kernels, not numpy expressions. The expression namespace would need a complete redesign.  
- Large dependency; less mature than numpy/scipy ecosystem.

*Verdict: Interesting for the geometry layer (compute shaders for `_clip_mesh_to_mask`), less so for user-facing expressions.*

---

**Option G — WGSL compute shaders (native wgpu) — Recommended long-term path**  
Write the surface evaluation and geometry construction as compute shaders executing directly inside wgpu. Results live in `GPUBuffer` objects that feed the vertex shader with zero CPU involvement. This is the "v2 GLSL compile" path referenced in the architecture design docs.

*Advantages:*  
- True zero-copy: compute result → vertex buffer, no CPU roundtrip at all.  
- Cross-platform: wgpu targets Metal, Vulkan, DX12 — all major platforms.  
- No new dependencies: wgpu is already a dependency.  
- Eliminates both PERF-002 (GPU upload) and the expression compute cost in one architecture.

*Cost:*  
- Requires an expression → WGSL transpiler. The current `exec()`-based eval model cannot be used; a compilable subset of expressions must be defined.  
- User expressions would be restricted to what can be represented in WGSL (no arbitrary Python, no scipy calls).  
- Significant implementation effort — effectively a v2 eval engine.  
- Data cells and recurrence relations would remain on CPU/numpy regardless.

*Verdict: The correct long-term architecture. Should be designed as an optional fast path alongside the existing numpy eval engine rather than a replacement — so that arbitrary Python expressions remain supported for correctness and scipy/recurrence use cases, while simple grid expressions opt into the WGSL path for animation performance.*

---

**Summary table:**

| Option | Platform | API change | Recurrence | Dependency | Zero-copy GPU | Recommendation |
|--------|----------|-----------|------------|------------|--------------|----------------|
| JAX | CUDA + Metal (exp.) | Low | ✗ breaks | Heavy | No | Blocked by recurrence |
| PyTorch | CUDA + MPS | Medium | ✗ breaks | Very heavy | No | Not recommended |
| CuPy | CUDA only | Near-zero | ✓ works | Medium | No | Blocked by platform |
| **Numba** | **All (CPU+CUDA)** | **None** | **✓ works** | **Light** | **No** | **Best near-term** |
| MLX | macOS only | Low | ✓ works | Medium | Possible | Platform blocker |
| Taichi | All | High | ✓ works | Medium | Possible | Complex |
| **WGSL shaders** | **All** | **N/A (opt-in)** | **✓ unchanged** | **None** | **✓ Yes** | **Best long-term** |

**Recommended path:**  
1. **Now:** Fix PERF-004 (`_clip_mesh_to_mask`) with Numba `@njit` as a targeted optimization — no architecture change, no new user-facing API.  
2. **Later:** Design the WGSL compute shader path as an opt-in fast path for simple grid expressions, keeping numpy eval as the fallback for arbitrary Python and scipy/recurrence cells.

---
