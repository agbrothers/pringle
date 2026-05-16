# Pringle — Bug & Feature Backlog

Items are logged here as they are identified. Each entry includes a description, reproduction steps or context, and a suggested fix or approach where known.

---

## Bugs

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

### BUG-002 — Zero-size buffer crash when slider reaches zero
**Status:** Open  
**Logged:** 2026-05-15

**Description:**  
When a slider constant reaches zero and the surface becomes a flat plane (or all-NaN), `gfx.Geometry` raises `ValueError: Buffer size cannot be zero`, then aborts.

**Reproduction:**  
Add cell `z = a*x + y`. Add slider `a = 1`. Drag slider to 0. App crashes with:
```
File "pringle/renderer.py", line 174, in make_surface_mesh
    geo = gfx.Geometry(positions=positions, indices=indices, normals=normals)
ValueError: Buffer size cannot be zero.
Abort trap: 6
```

**Root cause:**  
After clipping, `indices` can be an empty `(0, 3)` array. `gfx.Geometry` rejects zero-size buffers.

**Fix:**  
In `make_surface_mesh`, guard before constructing `gfx.Geometry`: if `indices` is empty (0 triangles), return a minimal invisible placeholder mesh instead of crashing.

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

### BUG-002 — Zero-size buffer crash when slider reaches zero
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
