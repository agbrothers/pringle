# Pringle — Bug & Feature Backlog

Items are logged here as they are identified. Each entry includes a description, reproduction steps or context, and a suggested fix or approach where known.

---

## Bugs

### BUG-006 — Camera moves when toggling cell visibility
**Status:** Open  
**Logged:** 2026-05-15

**Description:**  
Toggling a cell's visibility (eye icon / checkbox) back on causes the camera to rotate or shift slightly. Also observed when adding/removing expressions. The camera should be completely unaffected by visibility changes; only explicit user navigation (orbit, pan, zoom, WASD) should move it.

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
The triangle-clipping patch (`_clip_mesh_to_mask` in `renderer.py`) is not producing visibly smoother edges at the current grid resolution. The staircase pattern remains prominent (see attached screenshot from 2026-05-15 session).

**Reproduction:**  
Add a constrained surface, e.g. `z = x**2 - y**2` with constraint `x**2 + y**2 < 1`. Rotate to view the boundary edge.

**Hypothesis / investigation needed:**  
- The clipping logic may be correct but the grid step size is too coarse for the improvement to be visible.
- Or: clipped boundary vertices are not being interpolated correctly along the true constraint boundary.
- Or: the midpoint interpolation in `_bv()` does not move the vertex to the actual constraint boundary (it moves to the midpoint of the edge, not the exact zero-crossing).

**Possible approaches:**  
- Compute the exact zero-crossing position along each boundary edge rather than the midpoint (linear interpolation on the mask value, i.e. the signed distance to the constraint boundary).
- Adaptive grid refinement near the boundary.
- Smoothing at the shader/material level (e.g. anti-aliased edges via alpha).

---


### BUG-003 — `KeyboardEvent` has no `.get()` attribute
**Status:** Closed (fixed 2026-05-15, commit `41a40fe`)  
**Fix:** Keyboard handling moved entirely to the Qt level (`keyPressEvent`/`keyReleaseEvent` on `PringleViewport`). The wgpu-level `_on_key` handler was removed. `event.accept()` also suppresses the macOS press-and-hold accent popover.

---

## Features

### FEAT-001 — Axis visualization with toggle
**Status:** Closed (implemented 2026-05-15, commit `41a40fe`)  
**Fix:** Three `gfx.Line` objects (red=X, green=Y, blue=Z) added as permanent overlay scene objects; `set_axes_visible()` toggles them. Axis *labels* and tick marks remain deferred to v2.

---

### FEAT-002 — Slider widget layout: min/max below the bar
**Status:** Open  
**Logged:** 2026-05-15

**Description:**  
The min/max input boxes currently sit on the same row as the slider bar, making the row crowded. Desired layout:

```
[ slider bar ————————————— ] [ value ] [ Run ]
  min_val                          max_val
```

Top row: slider bar + current value + Run button.  
Bottom row (below bar, flush left/right): min on the left, max on the right.

**Scope:** Layout-only change in the slider cell widget.

---

### FEAT-003 — Desmos-style wireframe bounding box
**Status:** Closed (implemented 2026-05-15, commit `41a40fe`)  
**Fix:** 12 `gfx.Line` objects tracing the box edges added as permanent overlay objects; `set_bbox_visible()` toggles them. Z range = max(|x|, |y|) half-range, kept in sync with `set_overlay_bounds()` on every bounds change. "Equalize Axes" button also updates the z range to match the bounding sphere radius.

---

---

## Closed

### BUG-007 — Zero-size buffer crash in scatter/line when slider reaches zero
**Status:** Closed (fixed 2026-05-16)  
**Fix:** `make_scatter_mesh` and `make_line_mesh` now return an invisible 1-point placeholder when the input array is empty, matching the existing guard in `make_surface_mesh`. All three render-path functions are now protected.

### BUG-002 — Zero-size buffer crash in surface when slider reaches zero
**Status:** Closed (fixed 2026-05-15, commit `ff20120`)  
**Fix:** `make_surface_mesh` returns an invisible placeholder mesh when the clipped index array is empty.

### BUG-003 — `KeyboardEvent` has no `.get()` attribute
**Status:** Closed (fixed 2026-05-15, commit `41a40fe`)  
**Fix:** Keyboard handling moved to Qt level; wgpu `_on_key` handler removed entirely.

### FEAT-001 — Axis visualization with toggle
**Status:** Closed (implemented 2026-05-15, commit `41a40fe`)

### FEAT-003 — Desmos-style wireframe bounding box
**Status:** Closed (implemented 2026-05-15, commit `41a40fe`)

### FEAT-004 — WASD pans orbit target in world space
**Status:** Closed (implemented 2026-05-15, commit `98bcbdb`/`852a7e5`)  
**Fix:** Continuous pan via Qt `keyPressEvent`/`keyReleaseEvent`; `event.accept()` suppresses macOS accent popover; `focusOutEvent` clears held keys.

### FEAT-005 — Orbit target crosshair indicator
**Status:** Closed (implemented 2026-05-15, commit `98bcbdb`)  
**Fix:** `gfx.Group` with three short axis lines, repositioned to `controller.target` every frame in `render()`. Toggled via "Crosshair" checkbox.
