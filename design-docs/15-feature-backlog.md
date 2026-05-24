# Pringle — Feature Backlog

Desired features and enhancements are logged here as they are identified. Each entry includes a description, motivation, and implementation notes or open questions where known.

See [14-bug-backlog.md](14-bug-backlog.md) for the bug backlog.  
See [17-closed-features.md](17-closed-features.md) for implemented features.

---

### FEAT-062 — Revert: Enter in slider min/max/step fields should not create a new cell
**Status:** Closed (implemented 2026-05-24)  
**Logged:** 2026-05-24  
**Reverts:** FEAT-051 (partial)

**Description:**  
FEAT-051 wired all five slider fields — value spinbox, min, max, step, and name — so that pressing Enter creates a new cell below the slider. After UX testing, this behavior is undesirable for the min/max/step fields: users press Enter to commit a numeric value and are surprised when a new empty cell appears. The revert applies only to `_ExprBox` (used by min, max, and step); the value spinbox (`_SpinBox`) and name field (`_NameLineEdit`) retain their Enter-to-new-cell behavior.

**Motivation:**  
Min, max, and step are auxiliary configuration fields. Users tab or click through them while adjusting slider bounds and do not expect focus to jump to a brand-new cell after editing a range limit. The value spinbox and name field are primary interaction points where the progression to the next cell is more natural.

---

**Changes required:**

**`slider_widget.py` — `_ExprBox.keyPressEvent` (lines ~152–155):**

Remove the `new_cell_requested` emission from the Enter key branch. The Enter handler should only commit the value:

```python
if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
    self.editingFinished.emit()   # commit value; do NOT emit new_cell_requested
    return
```

**`slider_widget.py` — `SliderWidget._build_ui` (lines ~329–330):**

Remove the connections that forward `new_cell_requested` from the three range boxes to `enter_pressed`:

```python
# Delete this entire block:
for box in (self._min_box, self._max_box, self._step_box):
    box.new_cell_requested.connect(lambda: self.enter_pressed.emit(self.cell_id))
```

**`slider_widget.py` — `_ExprBox` class:**

With no remaining callers, `new_cell_requested = pyqtSignal()` on `_ExprBox` can be removed entirely to keep the class clean.

**No changes needed elsewhere.** `CellListWidget._on_enter_pressed`, `SliderWidget.enter_pressed`, and the connections for `_spinbox` and `_name_edit` are all unaffected.

---

**Tests to add / update:**

- `tests/test_feat051.py` — update the four cases that assert Enter in `_min_box`, `_max_box`, `_step_box`, and any combined range-field test. These should now assert that Enter does **not** emit `enter_pressed` from the slider. The value-spinbox and name-field cases are unchanged.
- Add a new test: Enter in `_min_box` while the panel has a focused slider commits the value (`_min_box.committed` fires) but does not call `add_cell` and does not change the cell count.

---

### FEAT-061 — Auto-scroll expression panel to reveal newly added cell
**Status:** Closed (implemented 2026-05-24)  
**Logged:** 2026-05-24

**Description:**  
When a new cell is added below the currently visible portion of the expression panel — via the add button, Enter, or any other means — the panel should scroll down so the new cell is visible. Currently, `add_cell` calls `self._scroll.ensureWidgetVisible(cell)` (added in FEAT-046), but this call fires before Qt has processed the layout change, so the cell has no geometry yet and the scroll position does not update.

**Root cause:**  
Qt layout changes (`insertWidget`, `addWidget`) are not applied synchronously. When `ensureWidgetVisible(cell)` is called immediately after inserting a widget into the layout, the cell's geometry is still `QRect(0, 0, 0, 0)` (or the default). Qt cannot compute the correct scroll offset for a widget it has not positioned yet, so the call is effectively a no-op for widgets that would require scrolling.

**Fix:**  
Defer the `ensureWidgetVisible` call via `QTimer.singleShot(0, ...)` so it runs after the current event loop iteration — by which point Qt has processed the layout event and the cell has a valid geometry.

---

**Implementation (`cell_list.py`):**

Replace the two `ensureWidgetVisible` calls inside `add_cell` that fire after a user-initiated insert (i.e., when `not self._skip_rebuild`):

```python
# Before (lines ~452 and ~469):
self._scroll.ensureWidgetVisible(cell)

# After:
QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(cell))
```

`QTimer` is already imported in `cell_list.py` (used by other callers). The lambda captures `cell` by closure — safe because the cell is a local in `add_cell` and the timer fires within the same Qt event loop iteration.

Apply the same deferral to the equivalent calls in `add_comment_cell` and `add_folder` if they exhibit the same issue (the same root cause applies wherever `ensureWidgetVisible` is called synchronously after a layout insertion).

**Scope note:** Do not defer the `ensureWidgetVisible` calls that occur during session restore (inside `_skip_rebuild` blocks or the YAML restore loop) — those already defer scroll via `_skip_rebuild` and scroll explicitly to the focused cell at the end of restore. Only the user-triggered insertion paths need the timer.

---

**Tests to add:**

- After calling `add_cell(after_id=last_cell_id)` with the panel at maximum scroll, process events (`app.processEvents()`), then assert `_scroll.verticalScrollBar().value() == _scroll.verticalScrollBar().maximum()` (or that the new cell is within the visible viewport rect).
- Same test for the add-button path (click the `+` button while scrolled to top with a full panel).
- Regression: session restore does not scroll to the bottom (the last-focused cell remains in view, not the final cell in the list).

---

### FEAT-060 — Consolidate Qt styles into a central `theme.qss` stylesheet
**Status:** Closed (implemented 2026-05-24)
**Logged:** 2026-05-24

**Description:**  
Migrate the ~40 scattered inline `setStyleSheet()` calls across the UI files into a single `pringle/theme.qss` file loaded once at `QApplication` startup. Static and structural styles (backgrounds, borders, fonts, spacing, hover states) move to QSS. A small number of genuinely data-driven `setStyleSheet()` calls (color dots, error/stale state indicators) remain in Python but are minimized.

**Motivation:**  
All visual appearance is currently defined inline across seven files, making a UI overhaul require hunting across the codebase. A central stylesheet enables rapid iteration — changing a font size or color scheme is a one-line edit rather than a grep-and-replace session. It also eliminates a class of Python boilerplate: `enterEvent`/`leaveEvent` overrides that toggle style strings manually can be replaced by QSS `:hover` pseudo-states.

**Files with inline styles today (all in scope):**  
`cell_widget.py`, `cell_list.py`, `slider_widget.py`, `folder_cell_widget.py`, `comment_cell_widget.py`, `style_popover.py`, `app.py`

---

**What moves to `theme.qss`:**

- All static background colors, borders, padding, font sizes, and colors.
- Hover states — the `_IDLE`/`_HOVER`/`_ACTIVE` string constants on `_DeleteButton` in `cell_widget.py` (lines 45–82) become a single `:hover` rule; the `enterEvent`/`leaveEvent` overrides are removed.
- Shared button styles currently copy-pasted as local variables (`_btn_style` in `cell_list.py`, `_rb_style` and `_BTN_STYLE` in `style_popover.py`) — defined once under a shared selector.
- Separator line colors, label colors, scroll area backgrounds.

**What stays in Python `setStyleSheet()`:**

| Call site | Why it stays |
|---|---|
| `cell_widget.py:671` — color dot background | Per-instance color from `CellStyle.color_qss()`; inherently dynamic |
| `cell_widget.py:484` — `_DATA_DOT` state (idle/stale/running/done) | State-driven color change per data cell |
| `cell_widget.py:618` — status dot reset | Same `_DATA_DOT` state machine |
| `slider_widget.py:159` — flash red border on conflict | Transient animation (500ms timer), not a stable state |
| `slider_widget.py:465` — invalid name border | Validation state, toggled on/off |
| `slider_widget.py:534–535` — min/max out-of-range red | Same |
| `style_popover.py:224,241` — reverse/swatch buttons | Per-instance color from `CellStyle` |

All other `setStyleSheet()` calls are static strings that belong in the QSS file.

---

**Implementation:**

**1. Create `pringle/theme.qss`**

Organize by component section with comments:

```css
/* ── Cell list ──────────────────────────────────────── */
QScrollArea#cell_scroll { background: #171717; border: none; }
QWidget#cell_container  { background-color: #171717; }
...

/* ── Cell widget ─────────────────────────────────────── */
QPlainTextEdit#cell_edit { border: none; background: transparent; }
QLabel#delete_btn        { color: transparent; font-size: 14px; padding: 0; }
QLabel#delete_btn:hover  { color: #aaa; }
...
```

Object names (`setObjectName`) are already present on many widgets; add them to any that are missing so QSS selectors can target them precisely.

**2. Load in `app.py` at startup**

```python
from importlib.resources import files

def _load_theme(app: QApplication) -> None:
    qss = files("pringle").joinpath("theme.qss").read_text()
    app.setStyleSheet(qss)
```

Called once before `MainWindow` is constructed. `importlib.resources` keeps the path portable when the package is installed.

**3. Remove redundant Python code**

- Delete `_DeleteButton._IDLE`, `_HOVER`, `_ACTIVE` class attributes and the `enterEvent`/`leaveEvent` overrides in `cell_widget.py`.
- Delete the `_btn_style`, `_rb_style`, `_BTN_STYLE` local variables in `cell_list.py` and `style_popover.py`.
- Remove the `setStyleSheet()` calls that are now covered by `theme.qss`.

**Naming note:**  
The existing `style.py` is named for `CellStyle` — it covers 3D rendering metadata (color, opacity, line width) and has nothing to do with Qt appearance. The new Qt theme file should be `theme.qss` (and a thin loader in `app.py`) to avoid conflating the two concerns.

**v1 scope:**  
Dark theme only — move the current appearance into `theme.qss` unchanged. Light mode / theme switching (FEAT-017) is a natural follow-on once a single stylesheet exists, but is out of scope here.

---

**Tests to add:**

- `theme.qss` loads without error and `QApplication.styleSheet()` is non-empty after startup.
- `_DeleteButton` no longer defines `enterEvent`/`leaveEvent` (assert via `hasattr`).
- Dynamic style calls still function: color dot reflects `CellStyle.color`, error borders appear on invalid slider name, data-dot cycles through idle/stale/running states.

---

### FEAT-059 — Parametric surface rendering from `xyz = (3, N, M)` assignment
**Status:** Closed (implemented 2026-05-24)
**Logged:** 2026-05-24

**Description:**  
When a cell assigns `xyz` to a `(3, N, M)` array, render it as a smooth parametric surface mesh. Currently the `parametric` render type in `app.py` only handles the `(N, 3)` curve case; `(3, N, M)` hits `else: vp.remove_object(cell_id)` and produces nothing. This feature wires up the full surface path.

**Motivation:**  
This unlocks a class of shapes that cannot be expressed as height fields (`z = f(x, y)`): spheres, tori, Möbius strips, Klein bottles, and any other surface parametrized over a 2D `(u, v)` domain. The `u` and `v` grids are already injected into the evaluation namespace and span `[0, 2π]` each by default, making these the natural choice for closed surfaces.

**Are there good reasons not to support this?**  
No architectural blockers. The triangle index builder (`_grid_indices`) is already grid-shape agnostic and reusable unchanged. The main addition is a new normal computation function (cross product of tangent vectors rather than the height-field shortcut), a new `make_parametric_surface_mesh` builder, and a one-line routing change in `app.py`. Constraint sub-cells and in-place re-render are not supported for v1 — see below.

---

**New helper — `_parametric_normals` (`renderer.py`):**

The height-field normal shortcut `n = (-dz/dx, -dz/dy, 1)` doesn't apply here. Normals must be the cross product of the two surface tangent vectors:

```python
def _parametric_normals(xyz: np.ndarray) -> np.ndarray:
    """Per-vertex normals for a parametric surface (3, N, M) via tangent cross product.
    Returns (N*M, 3) float32."""
    dPdu = np.gradient(xyz, axis=2)   # (3, N, M) tangent along u
    dPdv = np.gradient(xyz, axis=1)   # (3, N, M) tangent along v
    nx = dPdu[1] * dPdv[2] - dPdu[2] * dPdv[1]
    ny = dPdu[2] * dPdv[0] - dPdu[0] * dPdv[2]
    nz = dPdu[0] * dPdv[1] - dPdu[1] * dPdv[0]
    length = np.sqrt(nx**2 + ny**2 + nz**2)
    length = np.where(length < 1e-10, 1.0, length)   # guard against poles / degenerate pts
    nx /= length; ny /= length; nz /= length
    return np.stack([nx.ravel(), ny.ravel(), nz.ravel()], axis=1).astype(np.float32)
```

`np.gradient` along `axis=2` gives ∂P/∂u (varying column, fixed row); along `axis=1` gives ∂P/∂v. The cross product is then the surface normal pointing outward (direction depends on parametrization orientation — consistent within a session, may need negation for inside-out surfaces, which can always be corrected by swapping u/v in the expression).

**New mesh builder — `make_parametric_surface_mesh` (`renderer.py`):**

```python
def make_parametric_surface_mesh(
    xyz: np.ndarray,
    color: tuple = (0.2, 0.4, 0.9, 1.0),
    opacity: float = 1.0,
    colormap: str | None = None,
    colormap_reversed: bool = False,
) -> gfx.Mesh:
    """Build a pygfx Mesh from a (3, N, M) parametric surface array."""
    _, rows, cols = xyz.shape
    positions = xyz.reshape(3, -1).T.astype(np.float32)
    indices   = _grid_indices(rows, cols)
    normals   = _parametric_normals(xyz)
    if colormap is not None:
        colors = _apply_colormap(positions[:, 2], colormap, colormap_reversed)
        geo = gfx.Geometry(positions=positions, indices=indices, normals=normals, colors=colors)
        mat = gfx.MeshBasicMaterial(color_mode="vertex", side="both")
    else:
        geo = gfx.Geometry(positions=positions, indices=indices, normals=normals)
        mat = gfx.MeshPhongMaterial(color=color, side="both")
    if opacity < 1.0:
        mat.opacity = opacity
        mat.alpha_mode = "weighted_blend"
    return gfx.Mesh(geo, mat)
```

`_grid_indices` is unchanged — it generates the same quad tessellation regardless of whether the positions come from a height field or a parametric map.

**Routing change — `app.py` (`_on_cell_result`):**

Replace the existing parametric branch (lines 693–702):

```python
elif result.render_type == "parametric":
    pts = np.asarray(result.data, dtype=np.float32)
    if pts.ndim == 3 and pts.shape[0] == 3:
        mesh = make_parametric_surface_mesh(
            pts, color=style.color, opacity=style.opacity,
            colormap=cmap, colormap_reversed=cmap_rev,
        )
        vp.add_object(cell_id, mesh)
    elif pts.ndim == 2 and pts.shape[1] in (2, 3):
        # Parametric curve: (N, 3) — existing scatter path
        scatter = make_scatter_mesh(pts, color=style.color, opacity=style.opacity,
                                    size=style.point_size,
                                    as_spheres=(style.scatter_render_mode == "spheres"),
                                    colormap=cmap, colormap_reversed=cmap_rev)
        vp.add_object(cell_id, scatter)
    else:
        vp.remove_object(cell_id)
```

**v1 limitations:**

- **No constraint sub-cells.** Constraints currently mask against `z` (the height). For parametric surfaces, no single scalar is appropriate. Constraint sub-cells attached to a parametric cell are silently ignored for v1.
- **No in-place re-render.** The fast in-place update path (`_try_inplace_render`) assumes a height field and updates z-column of `positions` only. Parametric surfaces fall through to the full `make_parametric_surface_mesh` + `add_object` rebuild on every slider tick. This is acceptable for v1; the in-place path can be extended later.
- **Polar degeneracy.** At parameter-space poles (e.g., top/bottom of a sphere where all u values map to the same world point), tangent vectors collapse to zero and normals become arbitrary. The `1e-10` guard prevents NaN normals, but triangles at poles will look slightly wrong (pinched). This is a standard limitation of quad-grid tessellation at poles, independent of Pringle's design. A UV-sphere with slightly offset pole rows (`v ∈ [ε, π − ε]`) is the standard workaround.
- **Colormap default is world-space z.** For height-field surfaces this is the natural default. For parametric surfaces it is less natural (e.g., for a vertical torus, z-coloring produces horizontal bands rather than contours along the surface). A future improvement is to default to the `v` parameter value instead. For now, the user can always override with FEAT-035 (`colormap_expr`).

**`u_max` and `v_max` in the UI:**  
The `u` and `v` grids are currently hardcoded at `[0, 2π]` each in `GridConfig` and not exposed in `ViewSettingsWidget`. For a sphere, `v` needs to span `[0, π]`, requiring a `v/2` remapping in the expression (e.g. `sin(v/2)` instead of `sin(v)`). Exposing `u_min`, `u_max`, `v_min`, `v_max` as editable bounds in the axis settings panel is a natural companion feature but is out of scope here.

**Tests to add:**

- `xyz = array([cos(u), sin(u), v])` (helix-like cylinder) produces a `parametric` result with shape `(3, n, n)` and renders as a `gfx.Mesh`.
- `xyz = array([(2 + cos(v)) * cos(u), (2 + cos(v)) * sin(u), sin(v)])` (torus) renders without error.
- Normals are unit-length at non-degenerate points.
- Opacity < 1.0 enables WBOIT alpha mode.
- `(N, 3)` curve data still routes to `make_scatter_mesh` (regression test for the existing curve path).

---

### FEAT-057 — Axis bound variables in the expression namespace
**Status:** Open  
**Logged:** 2026-05-23

**Description:**  
Expose the six axis bounds — `x_min`, `x_max`, `y_min`, `y_max`, `z_min`, `z_max` — as named variables in the expression namespace. This works bidirectionally:

- **Read (bounds → namespace):** Any cell can reference `x_min`, `x_max`, etc. to parametrize its expression by the current viewport bounds (e.g. `z = sin(x_max * x)`).
- **Write (cell → bounds):** A cell can assign to these names (e.g. `x_max = t`, where `t` is a slider) to drive the axis bounds programmatically — enabling animated pan/zoom.

**Motivation:**  
Users frequently want to adapt expressions to the visible range (e.g., scale a wave frequency to fill the viewport) or animate the visible window as part of a recording. Both require reading and writing the axis bounds from cells, which is currently impossible — bounds live only in the `ViewSettingsWidget` and have no presence in the evaluation namespace.

---

**Read direction — injection before evaluation:**

In `_rebuild_namespace` (`cell_list.py`), inject the current bound values into `shared` before the cell evaluation loop. `CellListWidget` already owns `self._grid` (a `Grid` object built from `GridConfig`), so the bound values are directly accessible:

```python
# Inject axis bounds as readable namespace variables
cfg = self._grid.config
shared["x_min"] = float(cfg.x_min)
shared["x_max"] = float(cfg.x_max)
shared["y_min"] = float(cfg.y_min)
shared["y_max"] = float(cfg.y_max)
shared["z_min"] = float(cfg.z_min)
shared["z_max"] = float(cfg.z_max)
```

These are injected before the topological evaluation loop, so any cell in any order can read them. The DAG's undefined-name check (`undefined_names`) must treat these six names as provided system names, analogous to how slider names are known before evaluation — otherwise cells referencing `x_min` without defining it will emit spurious "Undefined" warnings.

**Write direction — bound override after evaluation:**

After the cell evaluation loop completes and `_shared_ns` is populated, check whether any cell exported values for these names and, if so, notify the app to update the viewport:

```python
_BOUND_NAMES = ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")

# After the eval loop, check for bound overrides
overrides = {k: shared[k] for k in _BOUND_NAMES if k in shared}
current = {
    "x_min": cfg.x_min, "x_max": cfg.x_max,
    "y_min": cfg.y_min, "y_max": cfg.y_max,
    "z_min": cfg.z_min, "z_max": cfg.z_max,
}
if any(overrides.get(k) != current[k] for k in _BOUND_NAMES):
    self.bounds_override.emit(
        float(overrides.get("x_min", cfg.x_min)),
        float(overrides.get("x_max", cfg.x_max)),
        float(overrides.get("y_min", cfg.y_min)),
        float(overrides.get("y_max", cfg.y_max)),
        float(overrides.get("z_min", cfg.z_min)),
        float(overrides.get("z_max", cfg.z_max)),
    )
```

`CellListWidget` gains a new signal:
```python
bounds_override = pyqtSignal(float, float, float, float, float, float)
```

In `app.py`, connect it at startup:
```python
self._cell_list.bounds_override.connect(self._on_bounds_override)
```

`_on_bounds_override` calls `_view_settings.set_bounds(...)`, which both updates the spinboxes and emits `bounds_changed`, which in turn calls `_on_bounds_changed` to rebuild the grid and re-render. One important guard: `set_bounds` triggers `bounds_changed` which calls `update_grid` which calls `_rebuild_namespace` — a potential loop. The loop is broken by not re-emitting `bounds_override` when `_rebuild_namespace` is entered because of a grid update (i.e., the injected values and the grid config will now agree, so the override comparison finds no change).

**Priority of bound values:**  
The last cell in topological order that assigns to `x_min` (or any bound name) wins. This is consistent with how any other name in the shared namespace is resolved — later cells in topo order overwrite earlier ones.

**No validation on override values:**  
The write path does not clamp or validate the values emitted — that is `ViewSettingsWidget`'s responsibility, same as when the user types a value manually. If a cell produces a non-finite float, the existing guard in `ViewSettingsWidget` should handle it.

**DAG dependency tracking:**  
A cell that reads `x_min` without assigning to it should have a DAG edge from the "bounds" provider (similar to a slider). The cleanest implementation is to make the six bound names appear in the DAG's provided-names set, so they are treated as roots with no dependencies. Cells that write `x_max = ...` will correctly appear in topological order — the override is processed after all cells have been evaluated, so a cell writing `x_max` does not affect the grid used for other cells in the same eval pass. The new bounds take effect on the next `_rebuild_namespace` call triggered by `_on_bounds_changed`.

**Animation behavior:**  
When a slider drives `x_max = a * t`, slider animation fires `_rebuild_namespace` repeatedly. Each pass: evaluates cells → detects `x_max` changed → emits `bounds_override` → `_on_bounds_override` → `set_bounds` → `bounds_changed` → `update_grid` → `_rebuild_namespace` again. This double-rebuild per animation tick is unavoidable if bounds must change the grid (and they must, since the evaluation grid `x, y` arrays depend on the bounds). The second rebuild uses the new bounds and produces the correctly-windowed surface. Performance impact: two full evals per animation tick instead of one; acceptable for simple expressions, potentially significant for heavier sessions. A future optimization could short-circuit the second rebuild when the only namespace change was the bound values themselves.

---

**Open questions:**

1. **Name collision:** `x_min`, `x_max`, etc. are generic names a user might want for their own local variables unrelated to axis bounds. Should there be a prefix (e.g. `view_x_min`) or should the design accept this collision as intentional (the feature is specifically about coupling these names to the bounds)?
2. **Write-back to spinboxes:** When a cell drives `x_max`, the spinbox in `ViewSettingsWidget` updates to reflect the override. Is this desirable? It means the spinbox value "jumps" during animation. An alternative is to show a visual indicator (e.g., a small lock icon or tinted spinbox) that bounds are currently overridden by a cell.
3. **Restore behavior:** On session load, cell values are restored first, then `_rebuild_namespace` runs. If a cell drives `x_max`, the bounds will be overridden before the saved YAML bounds can take effect. This may be correct, but it means the `x_max_expr` in the session's `view` block is irrelevant whenever a cell also writes `x_max`. Should the session format mark bound names as "cell-driven" vs. "UI-driven" to avoid confusion?

---

**Tests to add:**

- Cell `x_max = 5` causes `x_max` to read back as `5.0` in the namespace; subsequent cells can reference it.
- Surface cell referencing `x_max` in its expression evaluates without an "Undefined" warning.
- Slider `a` connected via `x_max = a` fires `bounds_override` on slider change.
- If no cell writes to bound names, `bounds_override` is not emitted.
- Read-only use: `z = sin(x_max * x)` evaluates correctly and uses the current spinbox value.

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

### FEAT-056 — Default color sequence for new cells
**Status:** Open  
**Logged:** 2026-05-23

**Description:**  
Establish a global default color sequence so new cells get predictable, Desmos-like colors in order (split from FEAT-016). A `PALETTE` list already exists in `style.py`; the missing piece is that `CellListWidget` does not yet assign colors from it in sequence — all new cells get the same default blue.

**Implementation notes:**
- `CellListWidget` should track a `_next_color_idx: int` counter, incrementing each time a new equation or data cell is added.
- Pass `palette_color(_next_color_idx)` as the default `style.color` when calling `add_cell()`.
- Skip sliders, folders, and comments (they don't render in the viewport).
- On session restore, do not advance the counter (colors come from YAML).
- Consider wrapping at `len(PALETTE)` (already handled by `palette_color()`).

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
