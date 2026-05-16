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
**Status:** Open  
**Logged:** 2026-05-15

**Description:**  
Pressing CMD, W, or other keys while the viewer is focused triggers:
```
AttributeError: 'KeyboardEvent' object has no attribute 'get'
```

**Reproduction:**  
Launch the app, click into the 3D viewport, press CMD or W.

**Root cause:**  
`PringleRenderer._on_key` accesses the event as `event.get("key", "")` (dict-style), but pygfx delivers a typed `KeyboardEvent` object with attribute access.

**Fix:**  
Replace `event.get("key", "")` with `getattr(event, "key", "")`. Also add a guard to skip modifier-only keys (CMD, Shift, Alt, Control) that have no movement mapping.

---

## Features

### FEAT-001 — Axis visualization with toggle
**Status:** Open  
**Logged:** 2026-05-15

**Description:**  
Display X/Y/Z axis lines in the 3D viewport. User can toggle them on/off via a control in the ViewSettingsWidget.

**Design:**  
- Colored axis lines: red=X, green=Y, blue=Z (Desmos convention).
- Optional tick marks and/or labels (lower priority).
- Implementation: permanent `gfx.Line` objects in the scene under an "axes" group node; `set_visible` on the group when toggled.
- Toggle exposed in `ViewSettingsWidget` as a checkbox or button.

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
**Status:** Open  
**Logged:** 2026-05-15

**Description:**  
Render a thin wireframe cube around the axis bounds to give the user a spatial reference frame while rotating/zooming — equivalent to the grey box Desmos 3D draws. Without it, it's easy to lose orientation when the plot is small or sparse.

**How Desmos does it:**  
Desmos 3D draws 12 line segments forming the edges of the `[x_min, x_max] × [y_min, y_max] × [z_min, z_max]` box. The z range is either fixed (e.g. ±z_scale) or derived from the current data bounding box. The box is a static scene object that doesn't move with the data — it represents the coordinate space, not the data range.

**Implementation plan:**  
- Compute the 8 corners of the axis-bounds box: `x ∈ {x_min, x_max}`, `y ∈ {y_min, y_max}`, `z ∈ {z_min, z_max}`. For z, use the axis x/y range as a symmetric default (e.g. `z_min = x_min`, `z_max = x_max`) or derive from data bounding sphere.
- Build 12 edges as a single `gfx.Line` with disjoint segments (or a `gfx.LineSegments`).
- Add to the scene as a named permanent object (`"__bbox__"`), outside the per-cell object dict.
- Rebuild when axis bounds change (`_on_bounds_changed`).
- Toggle visibility via a checkbox in `ViewSettingsWidget`.

---

### FEAT-004 — WASD pans orbit target in world space
**Status:** Closed (implemented 2026-05-15)  
**Fix:** `_on_key` now calls `_pan_target(dx, dy, dz)` which moves both `controller.target` and `camera.local.position` by the same world-space delta. Step = 5% of current camera-to-target distance. W=+Y, S=−Y, A=−X, D=+X, Space=+Z, Shift=−Z. Focus gating is automatic (canvas only receives key events when it has Qt focus).

---

### FEAT-005 — Orbit target crosshair indicator
**Status:** Closed (implemented 2026-05-15)  
**Fix:** A `gfx.Group` with three short ±X/Y/Z line segments (muted R/G/B, 2.5% of axis range) is added to the scene and repositioned to `controller.target` every frame in `render()`. Toggled via "Crosshair" checkbox in ViewSettingsWidget.

---

## Closed

### BUG-002 — Zero-size buffer crash when slider reaches zero
**Status:** Closed (fixed 2026-05-15, commit `ff20120`)  
**Fix:** `make_surface_mesh` returns an invisible placeholder mesh when the clipped index array is empty.
