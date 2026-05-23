# Session Format (YAML)

## Overview

All Pringle session state is serialized to a portable YAML file. This enables:
- **Lightweight saves** — a session is a single human-readable file
- **Version control** — YAML diffs are meaningful and reviewable
- **Sharing** — send a `.yaml` file; open it in Pringle
- **Reproducibility** — exact cell content, slider values, and viewport state are captured

The YAML file is the source of truth for a session. The UI is a view over this file; saving writes the current UI state to it, loading reads it back.

## Actual File Structure (v1)

The on-disk format written and read by `pringle/session.py`:

```yaml
version: 1

grid:
  x_min: -5.0
  x_max: 5.0
  y_min: -5.0
  y_max: 5.0
  z_min: -5.0      # controls wireframe/axes visual z extent
  z_max: 5.0
  n: 64            # grid points per axis

view:
  show_axes: true
  show_bbox: true
  show_crosshair: true
  show_light_bg: false
  camera_position: [6.0, -8.0, 6.0]
  orbit_target: [0.0, 0.0, 0.0]

cells:
  - id: "550e8400-..."
    type: equation          # equation | slider | data | folder | comment
    source: "z = sin(x) * cos(y)"
    visible: true
    folder_id: null         # null = top-level; UUID string = member of that folder
    style:
      color: [0.22, 0.40, 0.88, 1.0]   # RGBA floats 0–1
      opacity: 1.0
      line_width: 0.05
      point_size: 0.1
      colormap: null                    # null or matplotlib colormap name
      colormap_reversed: false
      scatter_render_mode: "circles"    # "circles" | "line" | "spheres" | "arrows"
      normalize_arrows: false
    rng_seed: 0                 # integer seed for per-cell RandomState; omitted = 0
    sub_cells:
      - type: constraint           # constraint | condition | initial_condition | recursion
        source: "x**2 + y**2 < 4"

  - id: "..."
    type: slider
    source: "a = 2"
    name: "a"
    value: 2.0           # current position (may differ from source if dragged)
    min_val: 0.0
    max_val: 10.0
    step: 0.1
    min_expr: "b"        # optional: expression string for min; re-resolved on load
    max_expr: "pi"       # optional: expression string for max
    step_expr: "dt"      # optional: expression string for step
    is_playing: false
    anim_mode: "pingpong"   # "pingpong" | "loop"
    style:
      color: [0.85, 0.33, 0.33, 1.0]
    sub_cells: []

  - id: "..."
    type: data
    source: |
      T = linspace(0, 10, 100)
      path = zeros((100, 3))
    style:
      color: [0.33, 0.75, 0.41, 1.0]
    sub_cells:
      - type: initial_condition
        source: "path[0] = array([1.0, 0.0, 0.0])"
      - type: recursion
        source: "path[n] = path[n-1] * 0.95"

  - id: "folder-uuid-..."
    type: folder
    name: "Helper Functions"
    collapsed: false
    visible: true           # folder viewport visibility (eye icon state)
    style:
      color: [0.55, 0.55, 0.55, 1.0]

  - id: "..."
    type: comment
    source: "# This is a note"

  - id: "member-uuid-..."
    type: equation
    source: "z = cos(x) * sin(y)"
    folder_id: "folder-uuid-..."   # member of the folder above
    visible: true
    style:
      color: [0.13, 0.53, 0.20, 1.0]
```

## Cell Types

| `type` | Description |
|---|---|
| `equation` | Any expression — surface, curve, scatter, parametric, lambda. Auto-detected at eval time. |
| `slider` | Scalar assignment. Has `name`, `value`, `min_val`, `max_val`, `step`, `is_playing`, `anim_mode` fields. |
| `data` | Arbitrary numpy/scipy code, run on demand via ▷. Can have `initial_condition` and `recursion` sub-cells. |
| `folder` | Collapsible group. Has `name`, `collapsed`, `visible` fields; no source. Member cells reference it via `folder_id`. |
| `comment` | Free text beginning with `#`. Never evaluated; no namespace contribution. |

## Sub-cell Types

| `type` | Used on | Description |
|---|---|---|
| `constraint` | equation | Boolean mask; sets z=NaN where False |
| `condition` | equation | Piecewise branch selector |
| `initial_condition` | data | Seed value for a recurrence |
| `recursion` | data | Recurrence rule, e.g. `path[n] = path[n-1] * 0.9` |

## Style Fields

All `CellStyle` fields are persisted per cell. Fields added after the initial v1 format use `style_data.get(key, default)` fallbacks in `restore_cell_list` for backward compatibility with older session files.

| Field | Type | Default | Notes |
|---|---|---|---|
| `color` | RGBA list | `[0.22, 0.40, 0.88, 1.0]` | Assigned cyclically from palette on cell creation |
| `opacity` | float | `1.0` | |
| `line_width` | float | `0.05` | World-space units |
| `point_size` | float | `0.1` | World-space units |
| `colormap` | str or null | `null` | matplotlib colormap name; null = flat color |
| `colormap_reversed` | bool | `false` | |
| `scatter_render_mode` | str | `"circles"` | `"circles"` \| `"line"` \| `"spheres"` \| `"arrows"` |
| `normalize_arrows` | bool | `false` | Pin all flow/vector arrows to equal length |

Old session files with boolean `scatter_as_line` or `scatter_as_spheres` flags are migrated to `scatter_render_mode` by a `_load_scatter_mode()` helper in `session.py`.

## Grid Config

`z_min`/`z_max` control how the wireframe bounding box and axis overlays are drawn in the 3D scene. They do **not** affect expression evaluation (which only uses `x`, `y` grids). Changing them via the Axis Bounds panel and clicking "Apply Bounds" updates the overlay immediately without re-evaluating cells.

## Versioning

The `version: 1` field enables future migration. `load_session` raises `ValueError` for unrecognised version numbers. Old sessions without `z_min`/`z_max` default to ±5.0.

## Diff Example

A YAML diff for changing a slider range is readable:

```diff
   type: slider
   source: "a = 2"
-  max_val: 10.0
+  max_val: 20.0
```

This makes session history meaningful in git — each commit represents a meaningful state of the visualization.
