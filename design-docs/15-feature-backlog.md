# Pringle — Feature Backlog

Desired features and enhancements are logged here as they are identified. Each entry includes a description, motivation, and implementation notes or open questions where known.

See [14-bug-backlog.md](14-bug-backlog.md) for the bug backlog.  
See [17-closed-features.md](17-closed-features.md) for implemented features.

---

### FEAT-045 — Expression references in slider bounds and axis limits

**Status:** Open  
**Logged:** 2026-05-22

**Description:**  
Currently, the min, max, and step fields on constant sliders (`SliderWidget`) and the axis bounds fields in `ViewSettingsWidget` only accept numeric literals — they are `QDoubleSpinBox` or the custom `_SpinBox` subclass. This feature allows the user to type a variable name or simple expression (e.g. `pi`, `a`, `b * 2`) into any of those fields. The value is resolved against the current shared namespace when committed; the resolved float drives behavior at runtime while the expression string is persisted in YAML so it re-resolves on reload.

**Motivation:**  
- Sweep ranges are naturally described relative to other parameters. `a` ranges from `0` to `b` is more meaningful than `0` to `5.0`.
- Constants like `pi`, `e`, and `sqrt(2)` (all already in the namespace via `namespace.py`) should be usable without looking up decimals.
- Axis bounds that track slider parameters — e.g. `x_min = -a`, `x_max = a` — let the viewport stay centered on a moving feature as a slider animates.

**Scope:**  
1. **Slider min/max/step** (`slider_widget.py`) — primary ask.  
2. **Axis bounds** (`view_settings.py`, fields `_x_min`, `_x_max`, `_y_min`, `_y_max`, `_z_min`, `_z_max`) — secondary, same mechanism.

---

**New widget: `_ExprBox` (replace `_SpinBox` on sliders)**

Create a `QLineEdit`-based replacement for `_SpinBox` that holds either a plain float or an expression string:

```python
class _ExprBox(QLineEdit):
    """A numeric input that also accepts expression strings resolvable to a scalar."""
    committed = pyqtSignal(float)   # emits the resolved value on commit

    def __init__(self, value: float = 0.0, parent=None):
        super().__init__(str(value), parent)
        self._raw_expr: str | None = None   # None → plain float mode
        self._last_valid: float = value
        self.editingFinished.connect(self._on_commit)

    def set_resolve(self, fn: Callable[[str], float | None]) -> None:
        """Inject namespace resolver; None = numeric-only mode."""
        self._resolve = fn

    def value(self) -> float:
        return self._last_valid

    def setValue(self, v: float) -> None:
        self._last_valid = v
        self._raw_expr = None
        self.setText(str(v))

    def expr(self) -> str | None:
        """The stored expression string, or None if plain numeric."""
        return self._raw_expr

    def _on_commit(self) -> None:
        text = self.text().strip()
        try:
            v = float(text)
            self._last_valid = v
            self._raw_expr = None
            self.committed.emit(v)
            return
        except ValueError:
            pass
        # Try namespace resolution
        resolved = self._resolve(text) if hasattr(self, "_resolve") else None
        if resolved is not None and isinstance(resolved, (int, float)) and np.isfinite(resolved):
            self._last_valid = float(resolved)
            self._raw_expr = text
            self.setText(text)   # keep expression visible
            self.committed.emit(self._last_valid)
        else:
            # Invalid — revert display to last valid value or expression
            self.setText(self._raw_expr if self._raw_expr else str(self._last_valid))
            self._indicate_error()   # brief red border flash

    def re_resolve(self, fn: Callable[[str], float | None]) -> None:
        """Called when the namespace changes; re-evaluate stored expressions."""
        if self._raw_expr is None:
            return
        resolved = fn(self._raw_expr)
        if resolved is not None and isinstance(resolved, (int, float)) and np.isfinite(resolved):
            self._last_valid = float(resolved)
            self.committed.emit(self._last_valid)
        # If resolution now fails (e.g., referenced slider deleted): keep last value silently.
```

**Namespace resolver:**  
The resolver is a simple closure over the shared namespace — evaluate the expression with `eval()` in a restricted scope:

```python
def _make_resolver(shared_ns: dict) -> Callable[[str], float | None]:
    safe_ns = {k: v for k, v in shared_ns.items()
               if isinstance(v, (int, float, np.floating, np.integer))}
    # Also include numpy constants already in namespace (pi, e, inf, etc.)
    def resolve(expr: str) -> float | None:
        try:
            result = eval(expr, {"__builtins__": {}}, safe_ns)
            if isinstance(result, (int, float, np.floating, np.integer)):
                return float(result)
        except Exception:
            pass
        return None
    return resolve
```

Note: `safe_ns` is filtered to scalar values only. Arrays, magic variables (`x`, `y`, `z`, `xyz`, etc.), and non-numeric values are excluded. This prevents nonsensical expressions from reaching the bounds fields.

---

**Changes to `SliderWidget` (`slider_widget.py`):**

1. Replace `_min_box`, `_max_box`, `_step_box` (`_SpinBox`) with `_ExprBox` instances.
2. Connect `_ExprBox.committed` where `_SpinBox.valueChanged` was connected (i.e., `_on_range_changed` and the step box consumer).
3. Add a method `set_resolver(fn)` that calls `set_resolve(fn)` on all three boxes. Called by `CellListWidget` after construction and after each namespace rebuild.
4. Add a method `re_resolve(fn)` that calls `re_resolve(fn)` on all three boxes. Called by `CellListWidget` after each `_rebuild_namespace()`.
5. Expose `min_expr()`, `max_expr()`, `step_expr()` that return each box's `expr()`.

**Changes to `session.py`:**

`cell_to_dict` for slider cells: write both the resolved float and the expression string:

```python
base["min_val"] = float(cell._min)
base["max_val"] = float(cell._max)
base["step"] = float(cell._step_box.value())
# Expression strings (None → key omitted)
if cell._min_box.expr():
    base["min_expr"] = cell._min_box.expr()
if cell._max_box.expr():
    base["max_expr"] = cell._max_box.expr()
if cell._step_box.expr():
    base["step_expr"] = cell._step_box.expr()
```

`restore_cell_list` for slider cells: after setting numeric values, restore expression strings:

```python
if "min_expr" in data:
    cell._min_box._raw_expr = data["min_expr"]
    cell._min_box.setText(data["min_expr"])
if "max_expr" in data:
    cell._max_box._raw_expr = data["max_expr"]
    cell._max_box.setText(data["max_expr"])
if "step_expr" in data:
    cell._step_box._raw_expr = data["step_expr"]
    cell._step_box.setText(data["step_expr"])
```

Expression strings are restored as text immediately; their values are re-resolved on the first `_rebuild_namespace()` pass (after all cells are loaded).

**Changes to `CellListWidget` (`cell_list.py`):**

After each `_rebuild_namespace()` completes and `self._shared_ns` is updated, re-resolve all slider bounds:

```python
resolver = _make_resolver(self._shared_ns)
for cell in self._cells:
    if isinstance(cell, SliderWidget):
        cell.re_resolve(resolver)
```

This is also called when a slider is first constructed:

```python
slider = SliderWidget(...)
slider.set_resolver(_make_resolver(self._shared_ns))
```

---

**Axis bounds (`view_settings.py`):**

Apply the same `_ExprBox` replacement to the six `QDoubleSpinBox` fields (`_x_min`, `_x_max`, `_y_min`, `_y_max`, `_z_min`, `_z_max`) in `ViewSettingsWidget`. The resolver is injected from `PringleWindow` via a new `set_resolver(fn)` method on `ViewSettingsWidget`, called after each `_rebuild_namespace()` in the same pass as the slider re-resolution.

`bounds_changed` is only emitted when the user clicks "Apply" — so axis bound expressions are not re-applied automatically when the namespace changes. Only on next Apply or explicit re-resolve. This avoids the viewport jumping during animation.

Session persistence for axis bounds (`session.py`, view block): add `x_min_expr`, `x_max_expr`, etc. alongside the existing float values, mirroring the slider pattern.

---

**Error indication (`_indicate_error` on `_ExprBox`):**

A brief (500 ms) red border on the field is sufficient — consistent with how validation errors are typically shown in Qt forms. No popup or status bar message needed:

```python
def _indicate_error(self) -> None:
    self.setStyleSheet("border: 1px solid #c0392b;")
    QTimer.singleShot(500, lambda: self.setStyleSheet(""))
```

---

**Edge cases:**

- **Self-reference:** `a`'s min set to `a` — the resolver filters to scalar values from the shared namespace; `a`'s value is the slider's current value at resolution time. No circular dependency issue since min/max don't feed back into the namespace. The value will just be whatever `a` currently evaluates to.
- **Deleted reference:** `min_expr = "b"` and slider `b` is deleted → `re_resolve` silently keeps `_last_valid`. The stale expression string remains displayed, visually indicating to the user that it needs updating.
- **Animation:** During slider animation, `_rebuild_namespace()` is called at 60 fps. The `re_resolve` call in the rebuild loop must be fast. Since `safe_ns` construction and `eval` are both O(n) in namespace size and called N_sliders times per frame, this should be sub-millisecond for typical session sizes. If profiling reveals a cost, cache the resolver and only rebuild it when the namespace structure changes (not on every value update).

---

**Tests to add:**

- Typing `pi` into a slider min field resolves to `3.14159...` and emits the correct value.
- Typing `a` into a slider max field (where `a` is another slider with value 5.0) resolves to `5.0` and updates when `a` changes (via `re_resolve`).
- Invalid expression (e.g. `not_a_var`) causes a brief red border and reverts to the previous value.
- Array-valued expression (e.g. `x`) is rejected (not a scalar).
- Session round-trip: save slider with `max_expr = "pi"`, reload, verify `_max_box.expr() == "pi"` and `_last_valid ≈ 3.14159`.
- Old sessions without `*_expr` fields load cleanly with `_raw_expr = None`.

---

### FEAT-044 — Text editing improvements: tab width, scroll pass-through, bracket wrapping

**Status:** Open  
**Logged:** 2026-05-22

**Scope:** All changes are confined to `CellTextEdit` in `cell_widget.py` and (where noted) `_CommentEdit` in `comment_cell_widget.py`. `SubCell` uses `CellTextEdit` directly so it inherits all fixes automatically.

---

**Part A — 4-space tab width**

Qt's default `QPlainTextEdit` tab stop is 80 px, which renders as ~8–9 character widths in a monospace font. Set it to exactly 4 character widths in `CellTextEdit.__init__`:

```python
from PyQt6.QtGui import QFontMetricsF
self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(' ') * 4)
```

This affects how `\t` characters are *displayed*. If actual space indentation (rather than a tab character) is preferred, also intercept Tab in `keyPressEvent` before the `super()` call:

```python
if key == Qt.Key.Key_Tab:
    self.insertPlainText("    ")   # 4 literal spaces
    return
```

Both are small, independent changes. Apply the same `setTabStopDistance` call to `_CommentEdit` for consistency.

---

**Part B — Wheel-event pass-through (no internal scroll)**

Scrollbars are already disabled on `CellTextEdit` (`ScrollBarAlwaysOff`), and auto-height is implemented via `documentSizeChanged`. However, `QAbstractScrollArea` (the base of `QPlainTextEdit`) still consumes wheel events even when the scrollbar is hidden, so scrolling the mouse wheel while the cursor is inside a cell does not scroll the outer panel. `_CommentEdit` already fixes this with `wheelEvent → event.ignore()`; `CellTextEdit` is missing it.

Add to `CellTextEdit`:

```python
def wheelEvent(self, event) -> None:
    event.ignore()   # propagate to CellListScrollArea
```

---

**Part C — Bracket wrapping (VSCode-style)**

When text is selected and the user presses an opening bracket key, wrap the selection with the bracket pair instead of replacing it. This is a standard editor affordance that Qt doesn't provide out of the box but is straightforward to add in `keyPressEvent`.

**Feasibility:** Fully achievable. `CellTextEdit` already overrides `keyPressEvent`; checking `cursor.hasSelection()` before `super()` is all that's needed.

Add a module-level constant and extend `keyPressEvent`:

```python
_WRAP_PAIRS: dict[int, tuple[str, str]] = {
    Qt.Key.Key_ParenLeft:   ('(', ')'),
    Qt.Key.Key_BracketLeft: ('[', ']'),
    Qt.Key.Key_BraceLeft:   ('{', '}'),
}

# inside keyPressEvent, before super():
if key in _WRAP_PAIRS and self.textCursor().hasSelection():
    open_, close = _WRAP_PAIRS[key]
    cursor = self.textCursor()
    selected = cursor.selectedText()
    cursor.insertText(open_ + selected + close)
    return
```

**Other VSCode-style editing features that are also achievable** (not in scope for this issue but worth noting):
- **Auto-close brackets** — type `(` without a selection → inserts `()` with cursor placed between them. Same `keyPressEvent` hook, different branch.
- **Smart backspace** — when cursor is between a matching pair `(|)`, delete both. Requires checking the character before and after the cursor.
- **Auto-indent on newline** — when Enter is pressed inside brackets, indent the new line by one level. Requires inspecting the line context at `keyPressEvent` for `Key_Return`.
- **Quote wrapping** — add `Qt.Key.Key_Apostrophe` and `Qt.Key.Key_QuoteDbl` to `_WRAP_PAIRS` (both open and close are the same character). This is a one-line addition to the constant.

**Tests to add:**
- Tab key inserts exactly 4 spaces (not a tab character) into a `CellTextEdit`.
- `setTabStopDistance` is set to 4 character widths on construction.
- Wheel event on a `CellTextEdit` calls `event.ignore()` (propagates to parent).
- Selecting `abc` and pressing `(` produces `(abc)` with the full wrapped text selected or cursor placed after `)`.
- Pressing `(` with no selection falls through to default behavior (inserts `(`).

---

### FEAT-039 — Compact per-cell RNG seed (replace full MT19937 state in YAML)

**Status:** Open  
**Logged:** 2026-05-22

**Description:**  
The current approach for persisting random-cell reproducibility stores the full MT19937 generator state per cell: 624 `uint32` values plus position, gauss cache, and gauss value. At scale this is extremely verbose — the `memory.yml` example file is 20,921 lines, almost entirely RNG state. The proposed replacement is a per-cell `RandomState` seeded by a compact integer that increments with each manual re-run (→ button press), shrinking the YAML footprint from ~630 values per cell to a single integer.

**Current implementation (touch points):**

| Location | What it does |
|---|---|
| `namespace.py` | `random = np.random` — global module alias injected into equation namespaces |
| `cell_list.py:674–686` | On each `_rebuild_namespace`: restores `np.random.set_state(cell._rng_state)` before exec if pinned; captures `np.random.get_state()` after if no pinned state |
| `cell_list.py:790` | `_on_run_requested`: clears `_rng_state = None` to allow fresh draws |
| `session.py:124–129` | `cell_to_dict`: serialises state as `rng_state` (624-element list), `rng_pos`, `rng_has_gauss`, `rng_gauss` |
| `session.py:296–301` | `restore_cell_list`: reconstructs the MT tuple and assigns to `cell._pending_rng_state` |

**Proposed approach — per-cell `RandomState` with integer seed:**

Each cell stores a single integer seed (`_rng_seed: int`). On evaluation, a fresh `numpy.random.RandomState(_rng_seed)` is created and injected as `random` into the cell's local namespace. After evaluation, the seed is captured (it doesn't change; only `→` increments it). On explicit re-run (→ press), `_rng_seed` is incremented by 1 (modulo `2**32` to stay within MT seed range).

```python
# Evaluation:
rng = np.random.RandomState(cell._rng_seed)
local_ns["random"] = rng

# Re-run (→ press), in _on_run_requested:
cell._rng_seed = (cell._rng_seed + 1) % (2**32)

# YAML write:
base["rng_seed"] = cell._rng_seed  # one integer

# YAML read:
cell._rng_seed = int(data.get("rng_seed", 0))
```

`numpy.random.RandomState` has the same interface as the `numpy.random` module for all commonly used functions (`random`, `randn`, `randint`, `choice`, etc.), so existing user expressions like `random.random((10, 2))` are unaffected.

**Initial seed value:**  
Start at `0` on the first evaluation of a new cell. This is predictable and deterministic, which is desirable for session reproducibility. Alternatively, pick a random start seed from `numpy.random.randint(0, 2**32)` on first creation — this gives different-looking defaults across sessions but makes the "first state" less predictable. Recommend starting at `0` (simple and reproducible).

**Tradeoffs vs. current full-state approach:**

| Property | Current (MT full state) | Proposed (seed integer) |
|---|---|---|
| YAML size per random cell | ~630 values (~2500 chars) | 1 integer |
| Reproducibility on reload | Bit-for-bit identical regardless of expression | Same sequence only if expression hasn't changed |
| Re-run behavior | Next → produces globally fresh draws | Next → produces draws from seed+1 |
| Interface change | `random = np.random` (module) | `random = RandomState(seed)` (instance) — same API |
| Backward compat | — | Old sessions with `rng_state` must be migrated |

**Key tradeoff to communicate to users:**  
With the per-seed approach, loading an old session and *then changing an expression* will not reproduce the visual output that was saved, because the seed only guarantees the same draw sequence for the same number and type of calls. The full-state approach was expression-independent. For exploratory/interactive use this doesn't matter; for archival reproducibility it matters.

**Backward compatibility:**  
`restore_cell_list` should check for the presence of `rng_state` (old key) and migrate in-memory:

```python
if "rng_state" in data:
    # Old format: ignore the full state; start at seed 0 (or log a migration warning)
    cell._rng_seed = 0
elif "rng_seed" in data:
    cell._rng_seed = int(data["rng_seed"])
else:
    cell._rng_seed = 0
```

Old sessions will lose pinned randomness on the first load but will otherwise work correctly. A one-time migration note in the status bar or console is appropriate.

**Implementation steps:**
1. Add `_rng_seed: int = 0` to `CellWidget` (or manage it entirely in `CellListWidget`)
2. In `_rebuild_namespace` (cell_list.py), replace the `get_state`/`set_state` block with `local_ns["random"] = np.random.RandomState(cell._rng_seed)`
3. In `_on_run_requested`, replace `cell._rng_state = None` with `cell._rng_seed = (cell._rng_seed + 1) % 2**32`
4. In `session.py:cell_to_dict`, replace the 4-field RNG block with `base["rng_seed"] = cell._rng_seed`
5. In `session.py:restore_cell_list`, add migration from `rng_state` to `_rng_seed = 0`
6. Remove `_rng_state` and `_pending_rng_state` from `CellWidget`; remove `np.random.set_state`/`get_state` calls from `CellListWidget`

**Tests to add:**
- A cell with `M = random.random((10, 2))` evaluated twice with the same seed produces identical output; with seed+1 produces different output.
- Session round-trip: save with `rng_seed`, reload, verify seed is restored.
- Old session with `rng_state` key loads without error and sets `_rng_seed = 0`.
- `np.random` global state is NOT mutated by cell evaluation (i.e., other cells without RNG are unaffected).

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

### FEAT-015 — Application icon
**Status:** Open  
**Logged:** 2026-05-16

**Description:**  
Add a custom icon for the application window and macOS Dock entry.

**Implementation notes:**
- Set via `QMainWindow.setWindowIcon(QIcon("path/to/icon.png"))` and `QApplication.setWindowIcon(...)` early in startup.
- macOS Dock icon additionally requires a `.icns` file referenced in the app bundle's `Info.plist` (relevant if packaging with PyInstaller or py2app).
- A simple `.png` (256×256 or 512×512) is sufficient for the window title bar on all platforms.

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
