# Pringle — Bug & Feature Backlog

Items are logged here as they are identified. Each entry includes a description, reproduction steps or context, and a suggested fix or approach where known.

---

## Open Bugs

### BUG-006 — Camera moves when toggling cell visibility
**Status:** Open  
**Logged:** 2026-05-15

**Description:**  
Toggling a cell's visibility (eye icon) back on causes the camera to rotate or shift slightly. Also observed when adding/removing expressions. The camera should be completely unaffected by visibility changes; only explicit user navigation (orbit, pan, zoom, WASD) should move it.

**Reproduction:**  
Add `p = array([[0, 0, 0], [1, 1, 1]])`. Toggle visibility off, then back on. Camera rotates.

**Root cause hypothesis:**  
`fit_camera()` or `show_object()` is likely being called somewhere on the re-add code path for visibility toggle, which repositions the camera even though the cell already exists in the scene.

**Fix:**  
Visibility toggle should only swap material opacity or `world.visible` on the existing object — never call `fit_camera()` or `show_object()` from the visibility path.

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

## Open Features

*(none — see Closed section below)*

---

## Closed

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

---

### FEAT-002 — Slider widget redesign
**Status:** Closed (implemented 2026-05-16)  
**Fix:** Complete 2-row layout redesign:
- Row 1: `[color dot] [name] [value spinbox (stretch)] [✕]`
- Row 2: `[▷ play] [min] [slider (stretch)] [max] · step [step]`
- Up/down ticker buttons removed (`NoButtons`)
- Smart decimal display — integers show without decimal point; trailing zeros stripped
- Range auto-expand on creation (if initial value exceeds default max, range doubles)
- Slider snaps to multiples of the step value when dragged

---

### FEAT-001 — Axis visualization with toggle
**Status:** Closed (implemented 2026-05-15, commit `41a40fe`)  
**Fix:** Three `gfx.Line` objects (red=X, green=Y, blue=Z) added as permanent overlay scene objects; `set_axes_visible()` toggles them. Axis labels and tick marks deferred to v2.

---

### FEAT-003 — Desmos-style wireframe bounding box
**Status:** Closed (implemented 2026-05-15, commit `41a40fe`)  
**Fix:** 12 `gfx.Line` objects tracing the box edges added as permanent overlay objects; `set_bbox_visible()` toggles them.

---

### FEAT-004 — WASD pans orbit target in world space
**Status:** Closed (implemented 2026-05-15, commit `98bcbdb`/`852a7e5`)  
**Fix:** Continuous pan via Qt `keyPressEvent`/`keyReleaseEvent`; `event.accept()` suppresses macOS accent popover.

---

### FEAT-005 — Orbit target crosshair indicator
**Status:** Closed (implemented 2026-05-15, commit `98bcbdb`)  
**Fix:** `gfx.Group` with three short axis lines, repositioned to `controller.target` every frame in `render()`. Toggled via "Crosshair" checkbox.

---

### FEAT-006 — Unified cell list (data + equation cells in one panel)
**Status:** Closed (implemented 2026-05-16)  
**Description:** Merged equation panel and data panel into a single scrollable `CellListWidget`. Two add buttons — `+ Equation` and `+ Data cell` — replace the old single `+ Add expression`. Data cells are skipped during reactive evaluation (marked stale) and run on demand via their ▷ button. Data cell exports persist in `_data_cell_ns` and seed the equation namespace.

---

### FEAT-007 — Inline value previews for equation cells
**Status:** Closed (implemented 2026-05-16)  
**Description:** Non-rendered cells now show small gray text below the cell body:
- Scalar results (e.g. `value = sum(p)`) — value shown left-aligned
- Non-rendered 1D arrays (e.g. `p = array([1,1,1])`) — elements shown left-aligned, truncated with `...` if too wide
- Rendered arrays (surfaces, curves, scatter) — shape shown right-aligned, e.g. `(64, 64)`
- Bare expressions (no assignment) — same preview rules apply, value captured via `eval`

---

### FEAT-008 — Z bounds spinboxes in Axis Bounds panel
**Status:** Closed (implemented 2026-05-16)  
**Description:** The axis bounds loop only built X and Y rows; Z existed in `GridConfig` but had no UI. Added Z row. Session save/load now persists `z_min`/`z_max`. Loading a session restores the spinboxes and overlay bounds. `_on_bounds_changed` now takes 6 parameters.

---

### FEAT-009 — Fix equalize axes to use Z span
**Status:** Closed (implemented 2026-05-16)  
**Description:** "Equalize Axes" previously used the scene bounding sphere radius. Now reads `z_min`/`z_max` from spinboxes, computes span, and sets x and y to `[−span/2, +span/2]` so all three axes have equal length.

---

### FEAT-010 — Unified line/dot size control
**Status:** Closed (implemented 2026-05-16)  
**Description:** Style popover "Line width" renamed to "Size". The control now sets both `line_width` (curves) and `point_size` (scatter dots) to the same value. Range extended from 10 to 20.
